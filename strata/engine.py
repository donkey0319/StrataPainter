"""Engine: project state + all GPU subsystems. Has no UI dependency, so it runs headless.

A project is one mesh split into texture sets (one per material). Each texture set has its own
resolution, mesh-map bakes, layer stack and compositor. `engine.layers`, `engine.comp`,
`engine.bakes`, `engine.res` and `engine.selected` refer to the active texture set.
"""
from __future__ import annotations

import hashlib
import copy
import io
import json
import math
import os
from types import SimpleNamespace
import zipfile
import uuid
import time
from dataclasses import is_dataclass

import moderngl
import numpy as np

from .baker import Baker, BakeSet, BakeSettings, PAD
from .compositor import Compositor
from .gpu import GPU, GPUMesh
from .layers import (Brush, Layer, MaskGen, Effect, Projection, group as make_group,
                     MASK_EFFECTS, CONTENT_EFFECTS, bind_anchor_references, renew_persistent_ids)
from .channels import CHANNEL_DESCRIPTORS, BY_KEY, N_CH
from .mesh import BUILTIN_MESHES, Mesh, load_high_poly
from .painter import Painter, Stroke, Surface, View, TOOL_CLONE, TOOL_SMUDGE
from .presets import SMART_MATERIALS
from .renderer import Camera, Renderer
from .resources import Resources, BUILTIN_ALPHAS
from .viewinput import UVMapping, uv_triangle
from . import meshmap
from .paintstore import PaintTextures
from . import deltas
from .color import ColorPipeline
from .journal import Journal, freeze_brush
from . import projectio
from .transactions import EditTransaction, capture_properties, restore_properties, properties_equal
from .materials import projection_changes, channel_settings

UNDO_LIMIT = 24
SAVE_VERSION = 3  # projects containing independent mask paint require v4


class TextureSet:
    def __init__(self, name: str, materials: list, tri_ids: np.ndarray, res: int, key: str):
        self.name = name
        self.materials = list(materials)
        self.tri_ids = np.asarray(tri_ids, np.int64)
        self.res = int(res)
        self.key = key
        self.visible = True          # session-only 3D viewport visibility
        self.bakes: BakeSet | None = None
        self.comp: Compositor | None = None
        self.layers: list[Layer] = []
        self.selected = -1
        self.focus: Layer | None = None          # selected layer when it sits inside a group
        self.quick: moderngl.Texture | None = None
        self.bake_settings = BakeSettings()
        self.dirty = True
        self.paint_dirty = False
        self.description = ""
        self.pid = uuid.uuid4().hex
        self.tiles = None             # optional material-owned multi-tile raster state

    @property
    def tile_addresses(self):
        from .tiles import TileAddress
        return self.tiles.addresses if self.tiles is not None else (TileAddress(),)

    def release(self):
        if self.tiles is not None:
            self.tiles.close()
            self.tiles = None
        for o in (self.comp, self.bakes):
            if o is not None:
                o.release()
        if self.quick is not None:
            self.quick.release()
        self.comp = self.bakes = self.quick = None


class Engine:
    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        self.gpu = GPU(ctx)
        self.color = ColorPipeline()
        self.resources = Resources(self.gpu, self.color)
        self.baker = Baker(self.gpu)
        self.painter = Painter(self.gpu, self.resources)
        self.renderer = Renderer(self.gpu)
        self.camera = Camera()
        self.brush = Brush()
        self.mesh: Mesh | None = None
        self.gm: GPUMesh | None = None
        self.sets: list[TextureSet] = []
        self.active = 0
        self.normal_strength = 1.0
        self.undo_stack, self.redo_stack = [], []
        self.history_limit = UNDO_LIMIT
        self.history_budget_bytes = 1536 * 1024 ** 2
        self.memory_notice = ""
        self.journal = Journal()
        self._stroke: Stroke | None = None
        self._tile_stroke = None
        self._stroke_layer = None
        self.view_size = (1, 1)
        self._vp = np.eye(4)
        self._last_pick = None
        self.clone_source = None          # screen px of the clone source
        self.clone_offset = None
        self.clone_uv_source = self.clone_uv_offset = None
        self.quick_mask_enabled = False
        self.high_meshes = {}             # path -> high-poly Mesh (in this project's space)
        self._high_hashes = {}
        self.last_replay = None           # substance.apply.ReplayStats of the last Painter import
        self.import_state = None
        self.import_reports = []
        self.export_settings = {}
        self._edit_serial = 0             # bumped by every undoable edit (paint, masks, layer tree)
        self._serial_counter = 0
        self._saved_serial = 0
        self._saved_sig = None            # project fingerprint at the last new / open / save
        self.project_path = None
        self.reimport_checkpoint = None
        self.project_resources = []
        self.project_diagnostics = []
        self._project_tempdir = None
        self._edit_transaction = None
        self._edit_before_serial = 0

    @property
    def user_channels(self):
        return self.resources.user_channels

    @user_channels.setter
    def user_channels(self, value):
        self.resources.user_channels = value

    @property
    def shader_workflow(self):
        return self.resources.shader_workflow

    @shader_workflow.setter
    def shader_workflow(self, value):
        self.resources.shader_workflow = value

    def add_user_channel(self, name, default=0., label=None):
        from .userchannels import validate
        key = name if name.startswith("user:") else "user:" + name
        if key in self.user_channels:
            raise ValueError("Channel already exists")
        definitions = dict(self.user_channels, **{key: {"label": label or key[5:], "default": default}})
        validate(definitions, self.shader_workflow)
        self.set_properties(self, user_channels=definitions)
        return key

    def set_user_channel(self, key, layer=None, **changes):
        from .userchannels import layer_values
        layer = layer or self.layer
        self._validate_edit_target(layer)
        if key not in self.user_channels:
            raise ValueError("Declare the user channel first")
        values = copy.deepcopy(layer.user_channels)
        setting = values.setdefault(key, {"value": self.user_channels[key]["default"], "enabled": True, "blend": -1, "opacity": 1.})
        setting.update(changes)
        layer_values(values, self.user_channels)
        return self.set_properties(layer, user_channels=values)

    def set_shader_workflow(self, **changes):
        value = dict(copy.deepcopy(self.shader_workflow), **changes)
        return self.set_properties(self, shader_workflow=value)

    def paint_user_channel(self, key=None, value=1.):
        from .userchannels import unit_value
        if key is not None and key not in self.user_channels:
            raise ValueError("Declare the user channel first")
        self.end_stroke()
        self.brush.user_channel, self.brush.user_value = key, unit_value(value)
        self.brush.target = 0
        if key is not None and self.layer is not None:
            self.set_user_channel(key, enabled=True)

    # ------------------------------------------------------------------ active texture set
    def enable_tiles(self, ts_index=None, resident_bytes=None):
        """Opt in a material to tiled raster ownership; UI dispatch is separate."""
        from .materialtiles import MaterialTiles
        if self.shader_workflow["displacement_meters"]:
            raise ValueError("Disable vertex displacement before enabling material tiles")
        self.commit_edit()
        self.end_stroke()
        ts = self.sets[self.active if ts_index is None else ts_index]
        if ts.tiles is not None:
            return ts.tiles
        if any(any(candidate is layer for candidate in self._walk(other.layers))
               for layer in self._walk(ts.layers) for other in self.sets if other is not ts):
            raise ValueError("Detach shared layer instances before enabling material tiles")
        staged = MaterialTiles(self, ts, resident_bytes)
        try:
            staged.import_legacy_base()
        except Exception:
            staged.close()
            raise
        ts.tiles = staged
        self.mark_modified()
        return staged

    def paint_tiles_uv(self, points, mapping, brush=None):
        """One undoable global-UV path, streamed through the active material's tiles."""
        if self.ts is None or self.ts.tiles is None:
            raise ValueError("Enable this material's tiles before painting a tiled UV path")
        self.commit_edit()
        self.end_stroke()
        return self.ts.tiles.paint_uv(points, mapping, brush)

    def evaluate_tile(self, address, ts_index=None, resolution=None):
        """Context manager yielding detached tile output; textures expire on exit."""
        from .tiles import TileAddress
        ts = self.sets[self.active if ts_index is None else ts_index]
        if ts.tiles is None:
            raise ValueError("Enable material tiles before evaluating a tile")
        return ts.tiles.evaluate(address if isinstance(address, TileAddress) else TileAddress(*address), resolution)

    def assign_tile_sequence(self, layer, channel, paths, ts_index=None):
        """Assign explicit UDIM/image paths; None removes the channel override."""
        ts = self.sets[self.active if ts_index is None else ts_index]
        if ts.tiles is None:
            raise ValueError("Enable material tiles before assigning an image sequence")
        self.commit_edit()
        self.end_stroke()
        return ts.tiles.assign_sequence(layer, channel, paths)

    @property
    def ts(self) -> TextureSet | None:
        return self.sets[self.active] if 0 <= self.active < len(self.sets) else None

    @property
    def layers(self) -> list:
        return self.ts.layers if self.ts else []

    @layers.setter
    def layers(self, value):
        if self.ts:
            self.ts.layers = value

    @property
    def selected(self) -> int:
        return self.ts.selected if self.ts else -1

    @selected.setter
    def selected(self, value):
        if self.ts:
            self.ts.selected = int(value)
            self.ts.focus = None

    @property
    def comp(self) -> Compositor | None:
        return self.ts.comp if self.ts else None

    @property
    def bakes(self) -> BakeSet | None:
        return self.ts.bakes if self.ts else None

    @property
    def res(self) -> int:
        return self.ts.res if self.ts else 2048

    @property
    def dirty(self) -> bool:
        return any(t.dirty or t.paint_dirty for t in self.sets)

    @dirty.setter
    def dirty(self, value):
        for t in self.sets:
            t.dirty = bool(value)

    def set_active(self, idx: int):
        self.commit_edit()
        if 0 <= idx < len(self.sets):
            if idx != self.active:
                self._finish_stroke()
                self.clone_uv_source = self.clone_uv_offset = None
            self.active = idx

    # ------------------------------------------------------------------ editable document properties
    @property
    def edit_active(self):
        return self._edit_transaction is not None

    @staticmethod
    def _property_contains(root, target, seen=None):
        if root is target:
            return True
        seen = set() if seen is None else seen
        if id(root) in seen:
            return False
        seen.add(id(root))
        if is_dataclass(root):
            return any(Engine._property_contains(getattr(root, name), target, seen)
                       for name in root.__dataclass_fields__
                       if name not in ("tex", "mask_tex", "uid", "pid", "children"))
        if isinstance(root, dict):
            return any(Engine._property_contains(value, target, seen) for value in root.values())
        if isinstance(root, (list, tuple)):
            return any(Engine._property_contains(value, target, seen) for value in root)
        return False

    def _property_owners(self, targets):
        owners = []
        for layer in self.all_layers_all_sets():
            if any(self._property_contains(layer, target) for target in targets):
                owners.append(layer)
        return owners

    def _validate_edit_target(self, target):
        if target is self or any(target is ts or target is ts.bake_settings for ts in self.sets):
            return
        if isinstance(target, Brush) or not self._property_owners([target]):
            raise ValueError("Property target does not belong to the open document")

    def _invalidate_properties(self, targets, owners=None):
        owners = self._property_owners(targets) if owners is None else owners
        for ts in self.sets:
            if (any(target is self or target is ts or target is ts.bake_settings for target in targets) or
                    any(layer is owner for layer in self._walk(ts.layers) for owner in owners)):
                ts.dirty = True
                ts.paint_dirty = False
                if ts.comp is not None:
                    ts.comp.invalidate_cache()

    def begin_edit(self, targets=None, label="Edit"):
        """Begin a continuous metadata edit. Commit once or cancel without history."""
        if self.edit_active:
            raise RuntimeError("An edit is already active; commit or cancel it first")
        self._finish_stroke()
        for ts in self.sets:
            bind_anchor_references(ts.layers)
        transaction = EditTransaction(label)
        if targets is not None:
            values = targets if isinstance(targets, (list, tuple)) else [targets]
            for target in values:
                self._validate_edit_target(target)
                transaction.touch(target)
        self._edit_before_serial = self._edit_serial
        self._edit_transaction = transaction
        return transaction

    def set_properties(self, target, **changes):
        """Undoable property assignment; joins an active continuous/multitarget edit."""
        self._validate_edit_target(target)
        if target is self and "export_settings" in changes:
            from .exportsettings import validate as validate_export_settings
            changes["export_settings"] = validate_export_settings(changes["export_settings"])
        from .userchannels import validate as validate_channels, layer_values
        if target is self and ("user_channels" in changes or "shader_workflow" in changes):
            definitions = changes.get("user_channels", self.user_channels)
            workflow = changes.get("shader_workflow", self.shader_workflow)
            validate_channels(definitions, workflow)
            from .userchannels import validate_resolution
            for ts in self.sets:validate_resolution(definitions, ts.res)
            for layer in self.all_layers_all_sets():
                layer_values(layer.user_channels, definitions)
            if workflow["displacement_meters"]:
                from .uvprep import meters_per_project_unit
                meters_per_project_unit(self.mesh)
                if any(ts.tiles is not None for ts in self.sets):
                    raise ValueError("Vertex displacement currently requires a single-tile material")
        if isinstance(target, Layer) and "user_channels" in changes:
            layer_values(changes["user_channels"], self.user_channels)
        if isinstance(target, Effect) and "params" in changes and changes["params"].get("user_channel"):
            if target.kind not in ("invert", "levels", "blur", "brightness_contrast", "graph"):
                raise ValueError("Unsupported scalar content effect")
            if changes["params"]["user_channel"] not in self.user_channels:
                raise ValueError("Effect references an undeclared user channel")
        if isinstance(target, Projection):
            changes = projection_changes(changes)
        elif isinstance(target, Layer) and "proj" in changes:
            value = changes["proj"]
            values = ({name: getattr(value, name) for name in Projection.__dataclass_fields__}
                      if isinstance(value, Projection) else value)
            if not isinstance(values, dict):
                raise ValueError("Expected projection property mapping")
            changes["proj"] = projection_changes(values)
        if isinstance(target,Layer) and "authored" in changes and changes["authored"] is not None:
            from .authored import validate
            if target.kind!="fill":raise ValueError("Authored objects require a fill-material layer")
            for ts in self.sets:
                if any(item is target for item in self._walk(ts.layers)):validate(changes["authored"],self.mesh,ts.tri_ids)
            if changes["authored"]["kind"]=="text":
                from .authored import font_atlas
                font_atlas(changes["authored"],min(256,self.res))
            elif changes["authored"].get("alpha") and changes["authored"].get("alpha")!=(target.authored or {}).get("alpha"):
                self.resources.alpha(changes["authored"]["alpha"])
        if isinstance(target, Effect) and target.kind == "graph" and "params" in changes:
            from .graphs import validate
            validate(changes["params"].get("graph"))
            if type(changes["params"].get("channel", 0)) is not int or not 0 <= changes["params"].get("channel", 0) < N_CH:
                raise ValueError("Native graph content requires one channel")
        if isinstance(target,Projection):
            mode=changes.get("mode",target.mode);decal=changes.get("decal",target.decal)
            if decal and mode not in (0,2):raise ValueError("Decal placement requires UV or planar mapping")
            if mode not in (0,2) and any(layer.authored and layer.authored["kind"]=="text" and layer.proj is target for layer in self.all_layers_all_sets()):raise ValueError("Text placement requires UV or planar mapping")
        implicit = not self.edit_active
        if implicit:
            self.begin_edit(label="Edit " + type(target).__name__)
        try:
            changed = self._edit_transaction.apply(target, changes)
            if changed:
                self._invalidate_properties([target])
            if implicit:
                self.commit_edit()
            return changed
        except Exception:
            if implicit:
                self.cancel_edit()
            raise

    def set_property(self, target, name, value):
        return self.set_properties(target, **{name: value})

    def assign_fill_map(self, layer, key, path_or_none):
        """Assign and enable a decoded bitmap as one reversible document edit."""
        self._validate_edit_target(layer)
        if not isinstance(layer, Layer) or layer.kind != "fill":
            raise ValueError("Bitmap slots belong to fill layers")
        if key in self.user_channels:
            path = None if path_or_none in (None, "") else os.path.abspath(os.path.expanduser(os.fspath(path_or_none)))
            if path is not None:self.resources.texture(path, "data")
            maps = dict(layer.maps)
            settings = copy.deepcopy(layer.user_channels)
            if path is None:
                maps.pop(key, None)
            else:
                maps[key] = path
                settings[key] = dict(settings.get(key, {"value":self.user_channels[key]["default"],"blend":-1,"opacity":1.}), enabled=True)
            return self.set_properties(layer, maps=maps, user_channels=settings)
        if not isinstance(key, str) or key not in BY_KEY:
            raise ValueError("Unknown material channel: " + str(key))
        path = None if path_or_none in (None, "") else os.path.abspath(os.path.expanduser(os.fspath(path_or_none)))
        enabled = list(layer.enabled)
        if ((path is not None and (layer.maps or {}).get(key) == path and enabled[BY_KEY[key].index]) or
                (path is None and key not in (layer.maps or {}))):
            return False
        if path is not None:
            # Decode and upload before recording history, so unreadable images and
            # allocation errors leave the existing bitmap and redo branch intact.
            self.resources.texture(path, BY_KEY[key].resource_kind)
        maps = dict(layer.maps or {})
        if path is None:
            maps.pop(key, None)
        else:
            maps[key] = path
            enabled[BY_KEY[key].index] = True
        return self.set_properties(layer, maps=maps, enabled=enabled)

    def set_projection(self, layer, **changes):
        """Undoable numeric/direct-manipulation edit of a fill projection."""
        self._validate_edit_target(layer)
        if not isinstance(layer, Layer) or layer.kind != "fill":
            raise ValueError("Projection editing requires a fill layer")
        return self.set_properties(layer.proj, **projection_changes(changes))

    def set_channel_settings(self, layer, key, blend=None, opacity=None):
        """Set one channel's overrides while preserving the remaining channels."""
        self._validate_edit_target(layer)
        if isinstance(layer, Layer) and key in self.user_channels:
            values = {name:value for name,value in (("blend",blend),("opacity",opacity)) if value is not None}
            return self.set_user_channel(key, layer, **values)
        if not isinstance(layer, Layer) or key not in BY_KEY:
            raise ValueError("Expected a document layer and existing channel")
        values = channel_settings(blend, opacity)
        changes = {}
        if "blend" in values:
            modes = list(layer.chan_blend)
            modes[BY_KEY[key].index] = values["blend"]
            changes["chan_blend"] = modes
        if "opacity" in values:
            opacities = list(layer.chan_opacity)
            opacities[BY_KEY[key].index] = values["opacity"]
            changes["chan_opacity"] = opacities
        return self.set_properties(layer, **changes)

    def commit_edit(self):
        transaction = self._edit_transaction
        if transaction is None:
            return False
        self._edit_transaction = None
        if not transaction.changed:
            return False
        states = [(target, state) for target, state in transaction.before_states
                  if not properties_equal(state, capture_properties(target))]
        owners = self._property_owners([target for target, _ in states])
        self._push_undo(("properties", states, self._edit_before_serial, transaction.label, owners))
        self._invalidate_properties([target for target, _ in states], owners)
        return True

    def cancel_edit(self):
        transaction = self._edit_transaction
        if transaction is None:
            return False
        self._edit_transaction = None
        transaction.cancel()
        self._invalidate_properties([target for target, _ in transaction.before_states])
        return True

    # ------------------------------------------------------------------ project
    def new_project(self, mesh: Mesh | str, res: int = 2048, ao_samples: int = 96, progress=None,
                    with_default_layer=True, bake_settings: BakeSettings | None = None,
                    split_materials=True, resolutions: dict | None = None, color_settings=None, tangent_basis="legacy",
                    uv_settings=None, source_unit=None):
        color = ColorPipeline(color_settings)
        scene = self.renderer.program_for(color)
        environment = None
        if isinstance(mesh, str):
            mesh = BUILTIN_MESHES[mesh]()
        if uv_settings is not None or source_unit is not None:
            from .uvprep import prepare_mesh
            mesh = prepare_mesh(mesh, uv_settings, source_unit)
        if tangent_basis not in ("legacy", "mikk"):
            raise ValueError("Unknown tangent basis")
        if tangent_basis == "mikk":
            from .tangents import mikk_mesh
            mesh = mikk_mesh(mesh)
        if self.renderer.env_path and color.managed != self.color.managed:
            environment = SimpleNamespace(gpu=self.gpu, env_tex=None, env_path=None, pipeline=color)
            Renderer.load_environment(environment, self.renderer.env_path)
        if mesh is not self.mesh:
            self.high_meshes = {}
            self._high_hashes = {}
        self._release_project()
        self.resources.release()
        from .userchannels import DEFAULT_WORKFLOW
        self.user_channels = {}
        self.shader_workflow = copy.deepcopy(DEFAULT_WORKFLOW)
        self.brush.user_channel = None
        self.color, self.resources.pipeline = color, color
        self.renderer.scene, self.renderer.pipeline = scene, color
        if environment is not None:
            if self.renderer.env_tex is not None:
                self.renderer.env_tex.release()
            self.renderer.env_tex, self.renderer.env_path = environment.env_tex, environment.env_path
        self.clone_uv_source = self.clone_uv_offset = None
        # Brushes and the display environment intentionally carry into new projects.
        # Retain their extracted dependencies rather than deleting live file paths.
        retained = {self.brush.alpha, self.brush.stencil, self.renderer.env_path}
        retained.update(self.brush.maps.values())
        retained.update(self.brush.proj_maps.values())
        self.project_resources = [r for r in self.project_resources if r.get("resolved") in retained]
        retained_ids = {r["id"] for r in self.project_resources}
        self.project_diagnostics = [d for d in self.project_diagnostics if d.get("resource_id") in retained_ids]
        if self._project_tempdir is not None and not any(r.get("embedded") for r in self.project_resources):
            self._project_tempdir.cleanup()
            self._project_tempdir = None
        self.project_path = None
        self.mesh = mesh
        self.gm = GPUMesh(self.gpu, mesh)
        mats = np.asarray(mesh.tri_material) if split_materials else np.zeros(len(mesh.indices), np.int32)
        groups = [(int(m), np.nonzero(mats == m)[0]) for m in np.unique(mats)]
        self.sets = []
        for k, (m, tris) in enumerate(groups):
            name = mesh.material_names[m] if split_materials and m < len(mesh.material_names) else "Default"
            r = int((resolutions or {}).get(name, res))
            ts = TextureSet(name, [m], tris, r, f"ts{k}")
            if bake_settings is not None:
                ts.bake_settings = BakeSettings.from_dict(bake_settings.to_dict())
            ts.bake_settings.ao_samples = int(ao_samples)
            self.gm.add_subset(ts.key, tris)
            self.sets.append(ts)
        n = len(self.sets)
        for i, ts in enumerate(self.sets):
            prog = (lambda f, i=i: progress((i + f) / n)) if progress else None
            ts.bakes = self._bake(ts, prog)
            ts.comp = Compositor(self.gpu, ts.res, ts.bakes, mesh, self.resources)
        self.active = 0
        self.camera.frame(mesh.center, mesh.radius)
        self.undo_stack.clear(); self.redo_stack.clear()
        if with_default_layer:
            for i in range(len(self.sets)):
                self.active = i
                self.add_layer("paint", record=False)
            self.active = 0
        preparation = mesh.extra.get("uv_preparation", {})
        if preparation.get("settings", {}).get("tile_count", 1) > 1:
            from .tiles import partition, TileAddress
            for i, ts in enumerate(self.sets):
                if any(address != TileAddress() for address in partition(mesh, ts.materials).pages):
                    self.enable_tiles(i)
        self.dirty = True
        self.mark_saved()

    def _release_project(self):
        self.cancel_edit()
        self._cancel_stroke()
        doomed = {}
        for ts in self.sets:
            doomed.update({id(l): l for l in self._walk(ts.layers)})
            doomed.update({id(f): f for l in self._walk(ts.layers) for f in l.effects + l.mask_effects})
        for e in self.undo_stack + self.redo_stack:
            if e[0] in ("stack", "tile_stack"):
                doomed.update({id(l): l for l in self._tree_layers(e[2])})
                doomed.update({id(f): f for f in self._tree_effects(e[2])})
            elif e[0] in ("tex", "mask") or (e[0] == "delta" and e[4] != "quick"):
                doomed[id(e[1])] = e[1]
            elif e[0] == "properties":
                doomed.update({id(l): l for l in e[4]})
            elif e[0] == "resources":
                doomed.update({id(l): l for l, _ in e[1]["layers"]})
            self._release_entry(e, force=True)
        for lay in doomed.values():
            self._release_layer(lay, force=True)
        self.mask_paint_target = None
        self.reimport_checkpoint = None
        self.import_state, self.import_reports, self.last_replay = None, [], None
        self.export_settings = {}
        self.journal = Journal()
        self.undo_stack, self.redo_stack = [], []
        for ts in self.sets:
            ts.release()
        self.sets = []
        if self.gm is not None:
            self.gm.release()
            self.gm = None
        self.painter.release()
        self.gpu.release_scratch()

    def _bake(self, ts: TextureSet, progress=None):
        high = self._high_for(ts)
        cage = self._cage_for(ts)
        if ts.tiles is not None and (ts.bake_settings.ray_correction_pid or ts.bake_settings.distance_correction_pid):
            address = ts.tiles.addresses[0]
            with ts.tiles._geometry(address) as (_, gm), ts.tiles.store.lease(ts.pid, address) as lease:
                fields = self._corrections_for(ts, lease)
                ts.bake_settings.correction_hashes = self._hash_corrections(fields)
                result = self.baker.bake(gm, ts.res, progress=progress, subset=ts.key, settings=ts.bake_settings,
                                         high=high, cage=cage, **fields)
        else:
            fields = self._corrections_for(ts)
            ts.bake_settings.correction_hashes = self._hash_corrections(fields)
            result = self.baker.bake(self.gm, ts.res, progress=progress, subset=ts.key, settings=ts.bake_settings,
                                     high=high, cage=cage, **fields)
        result._source_hashes = [self._high_hashes.get(p) for p in ts.bake_settings.high_poly]
        try:
            for key, record in ts.bake_settings.external_maps.items():
                if record.get("set_pid") != ts.pid:
                    raise ValueError("External mesh map belongs to a different texture set")
                values, refreshed = meshmap.read_map(record["path"], key, ts.res, record["interpretation"])
                record.update(refreshed)
                _, attribute, dtype = meshmap.SLOTS[key]
                texture = self.gpu.texture((ts.res, ts.res), 4, values, dtype=dtype, filt=key != "id")
                old = getattr(result, attribute)
                setattr(result, attribute, texture)
                if old is not None:
                    old.release()
        except Exception:
            result.release()
            raise
        result._settings_snapshot = meshmap.settings_provenance(ts.bake_settings)
        return result

    def set_bake_correction(self, kind, layer=None):
        if kind not in ("ray", "distance"):
            raise ValueError("Correction kind must be ray or distance")
        if layer is not None and (not any(item is layer for item in self._walk(self.ts.layers)) or layer.kind != "paint" or
                                  layer.has_mask or layer.effects or layer.mask_effects):
            raise ValueError("Correction fields require this material's unmasked paint layer without effects")
        self.begin_edit([self.ts.bake_settings] + ([layer] if layer is not None else []), label="Bind bake correction")
        try:
            self.set_properties(self.ts.bake_settings, **{kind + "_correction_pid": layer.pid if layer is not None else ""})
            if layer is not None:
                self.set_properties(layer, enabled=[False] * N_CH, visible=True)
            self.commit_edit()
        except Exception:
            self.cancel_edit()
            raise

    def _corrections_for(self, ts, lease=None):
        fields = {}
        for kind, channel in (("ray", "N"), ("distance", "H")):
            pid = getattr(ts.bake_settings, kind + "_correction_pid")
            if not pid:
                continue
            owner = next((layer for layer in self._walk(ts.layers) if layer.pid == pid and layer.kind == "paint"), None)
            if owner is None:
                raise ValueError("Bake correction layer is missing; restore it or clear the correction binding")
            textures = getattr(ts, "_correction_textures", {}).get(pid, owner.tex)
            fields[kind + "_correction"] = (lease.get(pid + ":" + channel) if lease is not None else textures.get(channel))
        return fields

    @staticmethod
    def _hash_corrections(fields):
        result = {}
        for key, texture in fields.items():
            content = b"empty" if texture is None else (str((texture.size, texture.components, texture.dtype)).encode() + texture.read())
            result[key.removesuffix("_correction")] = hashlib.sha256(content).hexdigest()
        return result

    def _current_correction_hashes(self, ts):
        try:
            if ts.tiles is None:
                return self._hash_corrections(self._corrections_for(ts))
            with ts.tiles.store.lease(ts.pid, ts.tiles.addresses[0]) as lease:
                return self._hash_corrections(self._corrections_for(ts, lease))
        except ValueError:
            # Missing bound layers remain recoverable metadata; rebake reports
            # the missing owner, while save preserves the prior baked output.
            return {kind: hashlib.sha256(("missing:" + getattr(ts.bake_settings, kind + "_correction_pid")).encode()).hexdigest()
                    for kind in ("ray", "distance") if getattr(ts.bake_settings, kind + "_correction_pid")}

    def _cage_for(self, ts):
        path = ts.bake_settings.cage_path
        if not path:
            return None
        from .bakecontrol import validate_cage
        with open(path, "rb") as source:
            digest = hashlib.sha256(source.read()).hexdigest()
        from .mesh import load_mesh
        cage = load_mesh(path, xform=self.mesh.extra.get("xform") or ([0., 0., 0.], 1.), light=True, require_uvs=False)
        validate_cage(self.mesh, cage)
        with open(path, "rb") as source:
            if hashlib.sha256(source.read()).hexdigest() != digest:
                raise ValueError("Cage changed while loading; retry the bake")
        ts.bake_settings.cage_hash = digest
        return cage

    def _high_for(self, ts: TextureSet):
        paths = list(ts.bake_settings.high_poly or [])
        meshes = []
        for p in paths:
            if p.startswith("<mesh:"):
                if p not in self.high_meshes:
                    raise ValueError("High-poly source was in memory in an earlier session; relink or clear it before rebaking")
                hm = self.high_meshes[p]
                self._high_hashes[p] = hashlib.sha256(hm.positions.tobytes() + hm.indices.tobytes()).hexdigest()
            else:
                try:
                    with open(p, "rb") as source:
                        digest = hashlib.sha256(source.read()).hexdigest()
                    if p not in self.high_meshes or self._high_hashes.get(p) != digest:
                        self.high_meshes[p] = load_high_poly(p, self.mesh)
                        self._high_hashes[p] = digest
                except Exception as e:
                    raise ValueError(f"High-poly source unavailable: {p}: {e}") from e
            meshes.append(self.high_meshes[p])
        return meshes or None

    def set_high_poly(self, sources, ts_index: int | None = None, all_sets=True, front=None, rear=None,
                      progress=None):
        """Bake normal/height (and AO, thickness, ID) from high-poly meshes. sources: file paths or
        Mesh objects already in this project's space (in-memory meshes get a synthetic key)."""
        paths = []
        for s in sources or []:
            if isinstance(s, Mesh):
                key = f"<mesh:{id(s)}>"
                self.high_meshes[key] = s
                paths.append(key)
            else:
                paths.append(s)
        targets = self.sets if all_sets else [self.sets[self.active if ts_index is None else ts_index]]
        settings = {}
        for ts in targets:
            staged = BakeSettings.from_dict(copy.deepcopy(ts.bake_settings.to_dict()))
            staged.high_poly = list(paths)
            if front is not None:
                staged.hp_front = float(front)
            if rear is not None:
                staged.hp_rear = float(rear)
            settings[ts.pid] = staged
        self.rebake(settings, all_sets=all_sets, ts_index=ts_index, progress=progress)

    def set_resolution(self, res: int, ts_index: int | None = None, rebake=True, progress=None):
        """Stage a set resize before publication; success clears GPU undo history.

        A failed allocation/bake leaves the live set and history untouched. With
        rebake=False, saved mesh maps are resampled rather than rebuilding sources.
        """
        index = self.active if ts_index is None else ts_index
        if isinstance(index, bool) or not isinstance(index, (int, np.integer)) or not 0 <= index < len(self.sets):
            raise ValueError("Invalid texture set")
        ts = self.sets[index]
        if isinstance(res, bool) or not isinstance(res, (int, np.integer)) or not 1 <= res <= 8192:
            raise ValueError("Texture resolution must be an integer between 1 and 8192")
        res = int(res)
        from .userchannels import validate_resolution
        validate_resolution(self.user_channels, res)
        if res == ts.res:
            return False
        if self._stroke is not None or getattr(self, "_tile_stroke", None) is not None:
            raise ValueError("Finish the current paint stroke before changing resolution")
        layers = list({id(lay): lay for lay in self._walk(ts.layers)}.values())
        shared = {id(lay) for lay in layers if any(other is not ts and any(candidate is lay for candidate in self._walk(other.layers))
                                                   for other in self.sets)}
        g = self.gpu
        staged = TextureSet(ts.name, ts.materials, ts.tri_ids, res, ts.key)
        staged.pid = ts.pid
        staged.layers = ts.layers
        staged.bake_settings = BakeSettings.from_dict(ts.bake_settings.to_dict())
        resized = []
        resized_effects = []
        evaluation_report = []

        def raster(owner, kind, original):
            from .evaluation import evaluate_raster
            return evaluate_raster(self, ts, owner, kind, original, res, allocations, evaluation_report)
        allocations = []
        staged_tiles = None

        def resample(texture, discrete=False):
            if not discrete:
                result = g.resample(texture, (res, res))
                allocations.append(result)
                return result
            # IDs, part numbers and coverage are categorical. Mipmap averages
            # would invent new identifiers when shrinking cached mesh maps.
            result = g.texture((res, res), texture.components, dtype=texture.dtype, filt=False)
            allocations.append(result)
            filtering = texture.filter
            try:
                texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
                g.blit(texture, result)
            finally:
                texture.filter = filtering
            return result

        try:
            if ts.tiles is not None:
                staged_tiles = ts.tiles.resized(res)
                staged.tiles = staged_tiles
            for lay in layers:
                if id(lay) in shared:
                    continue  # keep the authored canonical raster; evaluate separately at the new set size
                textures = raster(lay, "layer", lay.tex) if lay.tex else None
                mask = raster(lay, "mask", lay.mask_tex) if lay.mask_tex is not None else None
                resized.append((lay, textures, mask))
                for effect in lay.mask_effects:
                    if effect.tex is not None:
                        resized_effects.append((effect, raster(effect, "mask", effect.tex)))
            if ts.quick is not None:
                staged.quick = resample(ts.quick)
            staged._correction_textures = {lay.pid: textures for lay, textures, _ in resized if textures is not None}
            if rebake:
                staged.bakes = self._bake(staged, progress)
            else:
                # Keep the actual bake-time provenance; resampling is not a new
                # high-poly bake and must not relabel stale cached source data.
                old = ts.bakes
                names = ("pos", "nrm", "curv", "ao", "cov", "thick", "id", "part",
                         "tangent", "normal_hp", "height_hp", "projection")
                textures = {name: resample(getattr(old, name), discrete=name in ("part", "id", "cov", "projection"))
                            if getattr(old, name) is not None else None
                            for name in names}
                staged.bakes = BakeSet(**textures, res=res,
                    settings=BakeSettings.from_dict(old.settings.to_dict()) if old.settings is not None else None,
                    hp_hits=old.hp_hits)
                for name in ("_source_hashes", "_settings_snapshot"):
                    if hasattr(old, name):
                        setattr(staged.bakes, name, copy.deepcopy(getattr(old, name)))
            staged.comp = Compositor(g, res, staged.bakes, self.mesh, self.resources)
        except Exception:
            if staged_tiles is not None:
                staged_tiles.close()
            if staged.comp is not None:
                staged.comp.release()
            if staged.bakes is not None and rebake:
                staged.bakes.release()
            for texture in allocations:
                texture.release()
            raise
        finally:
            if self.renderer.pick_pos is not None:
                self._render_pick()

        # Publish only after all dependent allocations have succeeded. Old-size
        # raster/tree history cannot safely be applied to the resized set.
        self.commit_edit()
        self._clear_history()
        for lay, textures, mask in resized:
            self.painter.forget(lay)
            if lay.tex:
                for texture in lay.tex.values():
                    texture.release()
            if lay.mask_tex is not None:
                lay.mask_tex.release()
            lay.tex = PaintTextures(self.gpu, res, textures) if textures is not None else None
            lay.mask_tex = mask
            if lay.raster_res is not None:
                lay.raster_res = res
        for effect, texture in resized_effects:
            self.painter.forget_textures([effect.tex])
            effect.tex.release()
            effect.tex = texture
        if ts.quick is not None:
            self.painter.forget_textures([ts.quick])
            ts.quick.release()
        old_comp, old_bakes = ts.comp, ts.bakes
        ts.res, ts.quick, ts.bakes, ts.comp = res, staged.quick, staged.bakes, staged.comp
        ts.bake_settings = staged.bake_settings
        if staged_tiles is not None:
            ts.tiles.close()
            ts.tiles = staged_tiles
        old_comp.release()
        old_bakes.release()
        retained = {id(texture) for lay, textures, mask in resized for texture in
                    [*(textures or {}).values(), mask] if texture is not None}
        retained.update(id(texture) for _, texture in resized_effects)
        retained.update(id(texture) for texture in [staged.quick, *staged.bakes.maps().values()] if texture is not None)
        for texture in {id(texture): texture for texture in allocations}.values():
            if id(texture) not in retained:
                self.painter.forget_textures([texture])
                texture.release()
        self.gpu.release_scratch()
        ts.dirty, ts.paint_dirty = True, False
        self.evaluation_report = evaluation_report
        self.mark_modified()
        return True

    def rebake(self, settings: BakeSettings | None = None, ts_index: int | None = None, progress=None,
               all_sets=False):
        """Re-run the mesh-map bakers (e.g. after changing BakeSettings)."""
        targets = self.sets if all_sets else [self.sets[self.active if ts_index is None else ts_index]]
        self._finish_stroke()
        staged = []
        cancelled = False
        try:
            for index, ts in enumerate(targets):
                source = settings.get(ts.pid, ts.bake_settings) if isinstance(settings, dict) else (settings or ts.bake_settings)
                stage = copy.copy(ts)
                stage.bake_settings = BakeSettings.from_dict(copy.deepcopy(source.to_dict()))
                def report(value, i=index):
                    nonlocal cancelled
                    if progress and progress((i + value) / len(targets)) is False:
                        cancelled = True
                if report:
                    report(0.)
                if cancelled:
                    raise RuntimeError("Bake cancelled; original maps and settings retained")
                result = self._bake(stage, report)
                staged.append((ts, result, stage.bake_settings))
                if cancelled:
                    raise RuntimeError("Bake cancelled; original maps and settings retained")
            if progress:
                if progress(1.) is False:
                    raise RuntimeError("Bake cancelled; original maps and settings retained")
        except Exception:
            for _, result, _ in staged:
                result.release()
            raise
        before = [(ts, ts.bakes, ts.bake_settings) for ts in targets]
        self._push_undo(("bakes", before, self._edit_serial, "Bake mesh maps"))
        self._restore_bakes(staged)

    def _restore_bakes(self, states):
        for ts, bakes, settings in states:
            ts.bakes, ts.bake_settings = bakes, settings
            ts.comp.bakes = bakes
            ts.comp.invalidate_cache()
            ts.dirty = True

    def set_environment(self, path):
        path = os.path.abspath(path) if path else None
        if path == self.renderer.env_path:
            return False
        before = self._resource_state()
        try:
            self.renderer.load_environment(path)
        except Exception:
            if before["env_tex"] is not None:
                before["env_tex"].release()
            raise
        self._push_undo(("resources", before, self._edit_serial, "Change environment"))
        return True

    def _restore_color_profile(self, settings):
        pipeline = ColorPipeline(settings)
        if pipeline.settings.mode != self.color.settings.mode:
            raise ValueError("Color mode changes require an explicit new project")
        self.color, self.resources.pipeline = pipeline, pipeline
        self.renderer.pipeline = pipeline
        self.resources.release()
        for ts in self.sets:
            ts.comp.pipeline = pipeline
            ts.comp.invalidate_cache()
            ts.dirty = True

    def set_resource_color_space(self, path, space):
        if not self.color.managed:
            raise ValueError("Resource color interpretation requires a managed project")
        if space not in (None, "srgb", "linear"):
            raise ValueError("Unknown color-resource interpretation")
        with open(path, "rb") as source:
            digest = hashlib.sha256(source.read()).hexdigest()
        before = self.color.metadata()["settings"]
        settings = copy.deepcopy(before)
        if space is None:
            settings["resource_spaces"].pop(digest, None)
        else:
            settings["resource_spaces"][digest] = space
        if settings == before:
            return False
        operations = [operation for ts in self.sets if ts.tiles is not None for operation in ts.tiles.operations]
        if getattr(self, "_tile_stroke", None) is not None:
            operations.append(self._tile_stroke.operation)
        paths = {owner[key] for operation in operations
                 for owner, key, role in projectio.resource_slots({"brush": operation["brush"]})
                 if not (role == "alpha" and owner[key] in BUILTIN_ALPHAS)}
        for frozen in paths:
            if os.path.isfile(frozen):
                with open(frozen, "rb") as source:
                    if hashlib.sha256(source.read()).hexdigest() == digest:
                        raise ValueError("This image is referenced by tiled native paint; reinterpret it before painting. Current pixels were preserved.")
        # Construct/validate before changing project state.
        ColorPipeline(settings)
        self._push_undo(("color_profile", before, self._edit_serial, "Color resource interpretation"))
        self._restore_color_profile(settings)
        return True

    def assign_mesh_map(self, key, path, interpretation="data", ts_index=None, set_pid=None):
        ts = self.sets[self.active if ts_index is None else ts_index]
        if set_pid is not None and set_pid != ts.pid:
            raise ValueError("Mesh-map target does not match the selected texture set")
        if path is None:
            if key not in ts.bake_settings.external_maps:
                return False
            settings = BakeSettings.from_dict(copy.deepcopy(ts.bake_settings.to_dict()))
            settings.external_maps.pop(key)
            self.rebake(settings, ts_index=self.sets.index(ts))
            return True
        values, record = meshmap.read_map(path, key, ts.res, interpretation)
        record["set_pid"] = ts.pid
        if ts.bake_settings.external_maps.get(key) == record:
            return False
        self._finish_stroke()
        textures = {}
        replacement = None
        try:
            for name, texture in ts.bakes.maps().items():
                if texture is not None:
                    textures[name] = self.gpu.clone(texture)
            _, attribute, dtype = meshmap.SLOTS[key]
            replacement = self.gpu.texture((ts.res, ts.res), 4, values, dtype=dtype, filt=key != "id")
            if key in textures:
                textures.pop(key).release()
            textures[key] = replacement
            staged = copy.copy(ts.bakes)
            for name, attr in {"position": "pos", "world_normal": "nrm", "curvature": "curv", "coverage": "cov",
                               "thickness": "thick", "normal": "normal_hp", "height": "height_hp",
                               "projection_diagnostics": "projection"}.items():
                setattr(staged, attr, textures.get(name))
            for name in ("ao", "id", "part", "tangent"):
                setattr(staged, name, textures.get(name))
            settings = BakeSettings.from_dict(copy.deepcopy(ts.bake_settings.to_dict()))
            settings.external_maps[key] = record
            staged.settings = settings
            staged._settings_snapshot = meshmap.settings_provenance(settings)
        except Exception:
            for texture in textures.values():
                texture.release()
            raise
        self._push_undo(("bakes", [(ts, ts.bakes, ts.bake_settings)], self._edit_serial, "Assign mesh map"))
        self._restore_bakes([(ts, staged, settings)])
        return True

    # ------------------------------------------------------------------ layer tree helpers
    @staticmethod
    def _walk(layers):
        for lay in layers:
            yield from lay.walk()

    def all_layers(self, ts: TextureSet | None = None):
        return list(self._walk((ts or self.ts).layers)) if (ts or self.ts) else []

    def find(self, layer: Layer, ts: TextureSet | None = None):
        """(parent list, index, parent group or None) of a layer in the active (or given) set."""
        def rec(lst, parent):
            for i, l in enumerate(lst):
                if l is layer:
                    return lst, i, parent
                if l.children:
                    r = rec(l.children, l)
                    if r:
                        return r
            return None
        for t in ([ts] if ts else [self.ts] + [s for s in self.sets if s is not self.ts]):
            if t is None:
                continue
            r = rec(t.layers, None)
            if r:
                return r
        return None

    def _root_index(self, layer: Layer, ts: TextureSet | None = None) -> int:
        ts = ts or self.ts
        for i, top in enumerate(ts.layers):
            if any(l is layer or any(effect is layer for effect in l.effects + l.mask_effects) for l in top.walk()):
                return i
        return -1

    @property
    def layer(self) -> Layer | None:
        ts = self.ts
        if ts is None:
            return None
        if ts.focus is not None and self.find(ts.focus, ts):
            return ts.focus
        return ts.layers[ts.selected] if 0 <= ts.selected < len(ts.layers) else None

    def select(self, layer: Layer):
        """Select any layer, including one inside a group."""
        ts = self.ts
        r = self._root_index(layer, ts)
        if r < 0:
            return
        if getattr(self, "_tile_stroke", None) is not None:
            self._finish_stroke()
        ts.selected = r
        ts.focus = layer if ts.layers[r] is not layer else None
        self.dirty = True

    # ------------------------------------------------------------------ GPU allocation
    def _alloc_paint(self, lay: Layer, res=None):
        res = res or self.res
        lay.raster_res = int(res)
        lay.tex = PaintTextures(self.gpu, res)

    def _alloc_mask(self, lay: Layer, value: float, res=None):
        res = lay.raster_res or res or self.res
        lay.raster_res = int(res)
        res = res or self.res
        lay.mask_tex = self.gpu.texture((res, res), 1)
        self.gpu.fill(lay.mask_tex, (value, value, value, 1))

    def _release_layer(self, lay: Layer, force=False):
        if isinstance(lay, Effect):
            if lay.tex is not None:
                self.painter.forget_textures([lay.tex])
                lay.tex.release()
                lay.tex = None
            return
        live = set() if force else self._live_layers()
        for effect in lay.effects + lay.mask_effects:
            if force or id(effect) not in live:
                self._release_layer(effect)
        self.painter.forget(lay)
        if lay.tex:
            for t in lay.tex.values():
                t.release()
            lay.tex = None
        if lay.mask_tex is not None:
            lay.mask_tex.release()
            lay.mask_tex = None

    def _prepare(self, lay: Layer):
        """Allocate GPU data for a layer tree being inserted."""
        for l in lay.walk():
            if l.kind == "paint" and l.tex is None:
                self._alloc_paint(l)
            if l.has_mask and l.mask_tex is None:
                self._alloc_mask(l, 1.0)
            for effect in l.mask_effects:
                if effect.kind == "paint" and effect.tex is None:
                    effect.tex = self.gpu.texture((self.res, self.res), 1)
                    self.gpu.fill(effect.tex, (float(effect.params.get("initial", 0)),) * 4)

    # ------------------------------------------------------------------ undo snapshots of the tree
    @staticmethod
    def _tree(layers):
        return [(l, Engine._tree(l.children), list(l.effects), list(l.mask_effects)) for l in layers]

    @staticmethod
    def _restore_tree(tree):
        out = []
        for l, children, eff, meff in tree:
            l.children = Engine._restore_tree(children)
            l.effects, l.mask_effects = list(eff), list(meff)
            out.append(l)
        return out

    def _snapshot_stack(self, ts: TextureSet | None = None):
        ts = ts or self.ts
        return ("stack", ts, self._tree(ts.layers), ts.selected, ts.focus, self._edit_serial)

    def _push_undo(self, entry, clear_redo=True, journal_stroke=False):
        if getattr(self, "_tile_stroke", None) is not None:
            self._finish_stroke()
            serial_index = {"properties": 2, "resources": 2, "color_profile": 2, "bakes": 2, "mask": 3, "delta": 3}.get(entry[0])
            if serial_index is not None:
                entry = tuple(self._edit_serial if index == serial_index else value for index, value in enumerate(entry))
        self.commit_edit()
        self.journal.remember(self._edit_serial)
        if not journal_stroke:
            if entry[0] == "tex":
                for target in {"mask" if key == "mask" else "layer" for key in entry[2]}:
                    self.journal.invalidate(entry[1], target)
            elif entry[0] == "mask":
                self.journal.invalidate(entry[1], "mask")
            elif entry[0] == "delta":
                self.journal.invalidate(entry[1], entry[4])
        length = {"stack": 5, "tex": 3, "quick": 3}.get(entry[0])
        if length is not None:
            entry = (*entry[:length], self._edit_serial)
        self._serial_counter = max(self._serial_counter, self._edit_serial, self._saved_serial) + 1
        self._edit_serial = self._serial_counter
        self.journal.remember(self._edit_serial)
        self.undo_stack.append(entry)
        if clear_redo:
            dropped, self.redo_stack = self.redo_stack, []
            for e in dropped:
                self._release_entry(e)
        while len(self.undo_stack) > self.history_limit or self.history_usage() > self.history_budget_bytes:
            if not self.undo_stack:
                break
            self.memory_notice = "Older undo steps were released to stay within the history budget."
            self._release_entry(self.undo_stack.pop(0))

    def history_usage(self):
        textures = {}
        cpu = 0
        def add(texture):
            if texture is not None:
                textures[id(texture)] = texture
        for entry in self.undo_stack + self.redo_stack:
            if entry[0] == "tile_pixels":
                cpu += entry[5]
            elif entry[0] == "tile_stack":
                cpu += entry[7]
            if entry[0] in ("tex", "quick"):
                for texture in entry[2].values():
                    add(texture)
            elif entry[0] == "delta":
                for _, texture in entry[2].values():
                    add(texture)
            elif entry[0] == "mask":
                add(entry[2][1])
            elif entry[0] == "resources":
                add(entry[1].get("env_tex"))
            elif entry[0] == "bakes":
                for _, maps, _ in entry[1]:
                    for texture in maps.maps().values():
                        add(texture)
            elif entry[0] in ("stack", "tile_stack"):
                for layer in self._tree_layers(entry[2]):
                    for texture in (layer.tex or {}).values():
                        add(texture)
                    add(layer.mask_tex)
                for effect in self._tree_effects(entry[2]):
                    add(effect.tex)
        for ts in self.sets:
            for layer in self._walk(ts.layers):
                for texture in list((layer.tex or {}).values()) + [layer.mask_tex] + [effect.tex for effect in layer.mask_effects]:
                    textures.pop(id(texture), None)
        return cpu + sum(deltas.texture_bytes(texture) for texture in textures.values())

    def configure_memory(self, resource_mib, history_mib, steps):
        if not (64 <= resource_mib <= 65536 and 1 <= history_mib <= resource_mib and 1 <= steps <= 256):
            raise ValueError("Invalid resource/history budget or history step count")
        self.gpu.memory.limit_bytes = int(resource_mib * 1024 ** 2)
        self.history_budget_bytes = int(history_mib * 1024 ** 2)
        self.history_limit = int(steps)
        while self.undo_stack and (len(self.undo_stack) + len(self.redo_stack) > self.history_limit or self.history_usage() > self.history_budget_bytes):
            self._release_entry(self.undo_stack.pop(0))
        while self.redo_stack and (len(self.redo_stack) > self.history_limit or self.history_usage() > self.history_budget_bytes):
            self._release_entry(self.redo_stack.pop(0))

    @staticmethod
    def _tree_layers(tree):
        for l, children, _, _ in tree:
            yield l
            yield from Engine._tree_layers(children)

    @staticmethod
    def _tree_effects(tree):
        for _, children, content, mask in tree:
            yield from content
            yield from mask
            yield from Engine._tree_effects(children)

    def _live_layers(self):
        live = set()
        for ts in self.sets:
            live |= {id(l) for l in self._walk(ts.layers)}
            live |= {id(e) for l in self._walk(ts.layers) for e in l.effects + l.mask_effects}
        for e in self.undo_stack + self.redo_stack:
            if e[0] in ("stack", "tile_stack"):
                live |= {id(l) for l in self._tree_layers(e[2])}
                live |= {id(effect) for effect in self._tree_effects(e[2])}
            elif e[0] in ("tex", "mask") or (e[0] == "delta" and e[4] != "quick"):
                live.add(id(e[1]))
            elif e[0] == "properties":
                live |= {id(l) for l in e[4]}
            elif e[0] == "resources":
                live |= {id(l) for l, _ in e[1]["layers"]}
        return live

    def _release_entry(self, e, force=False):
        if e[0] == "delta":
            for _, texture in e[2].values():
                texture.release()
        elif e[0] == "bakes":
            for _, bakes, _ in e[1]:
                bakes.release()
        elif e[0] == "resources":
            texture = e[1].get("env_tex")
            if texture is not None:
                texture.release()
        elif e[0] == "mask":
            if e[2][1] is not None:
                e[2][1].release()
        elif e[0] in ("tex", "quick"):
            for t in e[2].values():
                t.release()
        if not force:
            candidates = (list(self._tree_layers(e[2])) if e[0] in ("stack", "tile_stack") else
                          e[4] if e[0] == "properties" else
                          [l for l, _ in e[1]["layers"]] if e[0] == "resources" else
                          [e[1]] if e[0] in ("mask", "tex") or (e[0] == "delta" and e[4] != "quick") else [])
            live = self._live_layers()
            if e[0] in ("stack", "tile_stack"):
                candidates = list(candidates) + list(self._tree_effects(e[2]))
            for lay in candidates:
                if id(lay) not in live:
                    self._release_layer(lay)

    def _clear_history(self):
        dropped = self.undo_stack + self.redo_stack
        self.undo_stack, self.redo_stack = [], []
        for e in dropped:
            self._release_entry(e)

    def _apply(self, e):
        length = {"stack": 5, "tex": 3, "quick": 3}.get(e[0])
        before_serial = self._edit_serial
        self.journal.remember(before_serial)
        inverse = self._apply_payload(e)
        if length is not None:
            # Trailing metadata preserves legacy tuple indices and app-created entries.
            self._edit_serial = e[length] if len(e) > length else before_serial
            inverse = (*inverse[:length], before_serial)
        self.journal.restore(self._edit_serial)
        return inverse

    def _apply_payload(self, e):
        """Restore entry e, returning the inverse entry."""
        if e[0] == "tile_stack":
            from .materialtiles import snapshot_bytes
            ts = e[1]
            current = ts.tiles.snapshot()
            bindings = [(obj, copy.deepcopy(obj.params)) for obj, _ in e[8]]
            inverse = ("tile_stack", ts, self._tree(ts.layers), ts.selected, ts.focus,
                       self._edit_serial, current, snapshot_bytes(current) + len(json.dumps([state for _, state in bindings])), bindings)
            ts.tiles.replace(*e[6])
            for obj, params in e[8]:
                obj.params = copy.deepcopy(params)
            ts.layers = self._restore_tree(e[2])
            ts.selected, ts.focus, self._edit_serial = e[3], e[4], e[5]
            self._invalidate_properties([self])
            return inverse
        if e[0] == "tile_pixels":
            from .materialtiles import snapshot_bytes
            ts = e[1]
            snapshot = ts.tiles.snapshot()
            inverse = ("tile_pixels", ts, snapshot,
                       [(layer, layer.has_mask) for layer in self._walk(ts.layers)], self._edit_serial, snapshot_bytes(snapshot))
            ts.tiles.replace(*e[2])
            for layer, has_mask in e[3]:
                layer.has_mask = has_mask
            self._edit_serial = e[4]
            self.dirty = True
            return inverse
        if e[0] == "color_profile":
            inverse = ("color_profile", self.color.metadata()["settings"], self._edit_serial, e[3])
            self._restore_color_profile(e[1])
            self._edit_serial = e[2]
            return inverse
        if e[0] == "delta":
            inverse = {}
            try:
                for key, (rect, saved) in e[2].items():
                    texture = self._delta_texture(e[1], key, e[4])
                    inverse[key] = (rect, deltas.crop(self.gpu, texture, rect))
            except Exception:
                for _, texture in inverse.values():
                    texture.release()
                raise
            try:
                for key, (rect, saved) in e[2].items():
                    deltas.patch(self.gpu, self._delta_texture(e[1], key, e[4]), saved, rect)
            except Exception:
                for key, (rect, saved) in inverse.items():
                    deltas.patch(self.gpu, self._delta_texture(e[1], key, e[4]), saved, rect)
                    saved.release()
                raise
            for _, saved in e[2].values():
                saved.release()
            serial = self._edit_serial
            self._edit_serial = e[3]
            self._invalidate_properties([self] if e[4] == "quick" else [e[1]])
            return ("delta", e[1], inverse, serial, e[4])
        if e[0] == "bakes":
            inverse = ("bakes", [(ts, ts.bakes, ts.bake_settings) for ts, _, _ in e[1]], self._edit_serial, e[3])
            self._restore_bakes(e[1])
            self._edit_serial = e[2]
            return inverse
        if e[0] == "properties":
            inverse = ("properties", [(obj, capture_properties(obj)) for obj, _ in e[1]],
                       self._edit_serial, e[3], e[4])
            for obj, state in reversed(e[1]):
                restore_properties(obj, state)
            self._edit_serial = e[2]
            self._invalidate_properties([obj for obj, _ in e[1]], e[4])
            return inverse
        if e[0] == "resources":
            inverse = ("resources", self._resource_state(), self._edit_serial, e[3])
            self._restore_resource_state(e[1])
            self._edit_serial = e[2]
            return inverse
        if e[0] == "mask":
            lay, (enabled, texture), serial = e[1:]
            inverse = ("mask", lay, (lay.has_mask, lay.mask_tex), self._edit_serial)
            lay.has_mask, lay.mask_tex = enabled, texture
            self._edit_serial = serial
            self._invalidate_properties([lay])
            return inverse
        if e[0] == "stack":
            ts = e[1]
            inv = self._snapshot_stack(ts)
            ts.layers = self._restore_tree(e[2])
            ts.selected, ts.focus = e[3], e[4]
            self._invalidate_properties([self])
            return inv
        if e[0] == "quick":
            ts, saved = e[1], e[2]
            cur = {"quick": self.gpu.clone(ts.quick)}
            self.gpu.blit(saved["quick"], ts.quick)
            saved["quick"].release()
            self._invalidate_properties([ts])
            return ("quick", ts, cur)
        lay, saved = e[1], e[2]
        cur = {}
        for k, t in saved.items():
            dst = (lay.tex if isinstance(lay, Effect) else lay.mask_tex) if k == "mask" else lay.tex[k]
            cur[k] = self.gpu.clone(dst)
            self.gpu.blit(t, dst)
            t.release()
        self._invalidate_properties([lay])
        return ("tex", lay, cur)

    def undo(self):
        self.commit_edit()
        self._finish_stroke()
        if self.undo_stack:
            entry = self.undo_stack.pop()
            try:
                self.redo_stack.append(self._apply(entry))
            except Exception:
                self.undo_stack.append(entry)
                raise

    def redo(self):
        self.commit_edit()
        self._finish_stroke()
        if self.redo_stack:
            entry = self.redo_stack.pop()
            try:
                inverse = self._apply(entry)
            except Exception:
                self.redo_stack.append(entry)
                raise
            self.undo_stack.append(inverse)

    # ------------------------------------------------------------------ layer operations
    def add_layer(self, kind="paint", name=None, layer: Layer | None = None, index=None, record=True,
                  parent: Layer | None = None):
        """Insert a new (or given) layer. index counts within `parent`'s children (or the top level)."""
        if layer is not None:
            from .authored import validate
            from .userchannels import layer_values
            for item in layer.walk():
                layer_values(item.user_channels, self.user_channels)
                if item.authored is not None:validate(item.authored,self.mesh,self.ts.tri_ids)
        if record:
            self._push_undo(self._snapshot_stack())
        if layer is None:
            default = {"paint": "Paint layer", "fill": "Fill layer", "group": "Folder"}.get(kind, "Layer")
            layer = make_group(name or default) if kind == "group" else Layer(name=name or default, kind=kind)
            if kind == "group":
                layer.enabled = [True] * N_CH
        self._prepare(layer)
        target = parent.children if parent is not None else self.ts.layers
        idx = len(target) if index is None else index
        target.insert(idx, layer)
        if parent is None:
            self.ts.selected, self.ts.focus = idx, None
        else:
            self.select(layer)
        self.dirty = True
        return layer

    def add_fill_layer(self, name="Fill layer", material=None, maps=None, **kw) -> Layer:
        """Fill layer with optional per-channel image maps {"C": path, "R": path, ...}."""
        lay = Layer(name=name, kind="fill", maps=dict(maps or {}), **kw)
        if material:
            from .presets import MATERIALS
            col, r, m = MATERIALS[material]
            lay.color, lay.rough, lay.metal = list(col), r, m
        if maps:
            for k in maps:
                if k in BY_KEY:
                    lay.enabled[BY_KEY[k].index] = True
                elif k in self.user_channels:
                    lay.user_channels[k] = {"value":self.user_channels[k]["default"],"enabled":True,"blend":-1,"opacity":1.}
        return self.add_layer(layer=lay)

    def add_smart_material(self, name: str, as_group=False):
        self._push_undo(self._snapshot_stack())
        # land under a selected paint layer, so the user's painting stays on top
        sel = self.ts.layers[self.selected] if 0 <= self.selected < len(self.ts.layers) else None
        idx = 0 if sel is None else (self.selected if sel.kind == "paint" else self.selected + 1)
        new = SMART_MATERIALS[name]()
        if as_group:
            grp = make_group(name, children=new)
            grp.enabled = [True] * N_CH
            self.add_layer(layer=grp, index=idx, record=False)
        else:
            for i, lay in enumerate(new):
                self.add_layer(layer=lay, index=idx + i, record=False)
        if sel is not None and sel.kind == "paint":
            self.ts.selected = self.ts.layers.index(sel)   # keep painting where you were

    def delete_layer(self, idx=None, layer: Layer | None = None):
        if layer is not None and self._root_index(layer) >= 0 and layer not in self.ts.layers:
            self._push_undo(self._snapshot_stack())
            lst, i, parent = self.find(layer, self.ts)
            lst.pop(i)
            self.ts.focus = parent
            self.dirty = True
            return
        if layer is not None:
            idx = self.ts.layers.index(layer)
        idx = self.selected if idx is None else idx
        if not (0 <= idx < len(self.layers)):
            return
        self._push_undo(self._snapshot_stack())
        self.layers.pop(idx)            # GPU data stays alive in the undo entry
        self.ts.selected = min(idx, len(self.layers) - 1)
        self.ts.focus = None
        self.dirty = True

    def clone_layers(self, layers):
        for layer in layers:
            self._require_legacy_rasters(layer)
        for ts in self.sets:
            bind_anchor_references(ts.layers)
        cloned = [Layer.from_dict(src.to_dict()) for src in layers]
        renew_persistent_ids(cloned)
        for src, dst in zip(layers, cloned):
            for s, d in zip(src.walk(), dst.walk()):
                if s.tex:
                    d.tex = PaintTextures(self.gpu, self.res, {k: (self.gpu.clone(t) if t.size == (self.res, self.res) else
                                 self.gpu.resample(t, (self.res, self.res))) for k, t in s.tex.items()})
                if s.mask_tex is not None:
                    d.mask_tex = (self.gpu.clone(s.mask_tex) if s.mask_tex.size == (self.res, self.res) else
                                  self.gpu.resample(s.mask_tex, (self.res, self.res)))
                for source, dest in zip(s.mask_effects, d.mask_effects):
                    if source.tex is not None:
                        dest.tex = (self.gpu.clone(source.tex) if source.tex.size == (self.res, self.res) else
                                    self.gpu.resample(source.tex, (self.res, self.res)))
                if d.raster_res is not None:
                    d.raster_res = self.res
        return cloned

    def _clone_layer(self, src: Layer) -> Layer:
        return self.clone_layers([src])[0]

    def duplicate_layer(self, idx=None, layer: Layer | None = None):
        if layer is None:
            idx = self.selected if idx is None else idx
            if not (0 <= idx < len(self.layers)):
                return
            layer = self.layers[idx]
        if self.ts.tiles is not None:
            self.commit_edit()
            self._finish_stroke()
            return self.ts.tiles.duplicate_layer(layer)
        lst, i, parent = self.find(layer, self.ts)
        lay = self._clone_layer(layer)
        lay.name = layer.name + " copy"
        return self.add_layer(layer=lay, index=i + 1, parent=parent)

    def move_layer(self, idx, delta):
        j = idx + delta
        if 0 <= idx < len(self.layers) and 0 <= j < len(self.layers):
            self._push_undo(self._snapshot_stack())
            self.layers[idx], self.layers[j] = self.layers[j], self.layers[idx]
            self.ts.selected, self.ts.focus = j, None
            self.dirty = True

    def move_layer_to(self, layer: Layer, parent: Layer | None, index: int | None = None):
        """Move a layer anywhere in the tree (into a group, out of it, reorder)."""
        if parent is not None and any(l is parent for l in layer.walk()):
            raise ValueError("can't move a group into itself")
        self._push_undo(self._snapshot_stack())
        lst, i, _ = self.find(layer, self.ts)
        lst.pop(i)
        target = parent.children if parent is not None else self.ts.layers
        target.insert(len(target) if index is None else min(index, len(target)), layer)
        self.select(layer)
        self.dirty = True

    def move_layers_to(self, layers, parent=None, index=None):
        """Move an ordered forest in one undo step; index refers to the original target list."""
        self._finish_stroke()
        self.commit_edit()
        active = self.all_layers()
        requested = {id(layer) for layer in layers}
        if any(identity not in {id(layer) for layer in active} for identity in requested):
            raise ValueError("Moved layers must belong to the active texture set")
        roots = [layer for layer in active if id(layer) in requested and not any(
            other is not layer and id(other) in requested and any(child is layer for child in other.walk())
            for other in active)]
        if not roots:
            return False
        if parent is not None and (not parent.is_group or not any(layer is parent for layer in active)):
            raise ValueError("Destination must be a folder in the active texture set")
        if parent is not None and any(any(child is parent for child in layer.walk()) for layer in roots):
            raise ValueError("A folder cannot be moved inside itself or a descendant")
        target = parent.children if parent is not None else self.layers
        if index is not None and (type(index) is not int or not 0 <= index <= len(target)):
            raise ValueError("Invalid layer insertion position")
        insertion = len(target) if index is None else index
        moved = {id(layer) for layer in roots}
        insertion -= sum(id(layer) in moved for layer in target[:insertion])
        lists = {id(target): (target, [layer for layer in target if id(layer) not in moved])}
        for layer in roots:
            source, _, _ = self.find(layer)
            lists[id(source)] = (source, [item for item in source if id(item) not in moved])
        replacement = lists[id(target)][1]
        replacement[insertion:insertion] = roots
        if all(len(original) == len(updated) and all(a is b for a, b in zip(original, updated))
               for original, updated in lists.values()):
            return False
        self._push_undo(self._snapshot_stack())
        for original, updated in lists.values():
            original[:] = updated
        self.select(roots[-1])
        self.dirty = True
        return True

    def group_layers(self, layers: list, name="Folder") -> Layer:
        """Wrap sibling layers in a new group placed where the topmost one was."""
        if not layers:
            return None
        self._push_undo(self._snapshot_stack())
        lst, _, parent = self.find(layers[0], self.ts)
        idxs = sorted(lst.index(l) for l in layers if l in lst)
        members = [lst[i] for i in idxs]
        for i in reversed(idxs):
            lst.pop(i)
        grp = make_group(name, children=members)
        grp.enabled = [True] * N_CH
        lst.insert(idxs[0], grp)
        if parent is None:
            self.ts.selected, self.ts.focus = idxs[0], None
        else:
            self.select(grp)
        self.dirty = True
        return grp

    def ungroup(self, grp: Layer):
        if not grp.is_group:
            return
        self._push_undo(self._snapshot_stack())
        lst, i, parent = self.find(grp, self.ts)
        lst.pop(i)
        for k, c in enumerate(grp.children):
            lst.insert(i + k, c)
        grp.children = []
        self.dirty = True

    def instance_layer(self, layer: Layer, ts_index: int, index=None):
        """Share a layer (or group) with another texture set: edits show up in both."""
        ts = self.sets[ts_index]
        from .authored import validate
        for item in layer.walk():
            if item.authored is not None:validate(item.authored,self.mesh,ts.tri_ids)
        self._require_legacy_rasters(layer)
        if ts.tiles is not None:
            raise ValueError("Cross-material layer instances are not integrated with material tiles yet")
        for item in layer.walk():
            textures = list((item.tex or {}).values()) + ([item.mask_tex] if item.mask_tex is not None else [])
            textures += [effect.tex for effect in item.mask_effects if effect.tex is not None]
            if item.raster_res is None and textures:
                item.raster_res = textures[0].size[0]
        if any(existing is layer for existing in self._walk(ts.layers)):
            return
        self._push_undo(self._snapshot_stack(ts))
        ts.layers.insert(len(ts.layers) if index is None else index, layer)
        ts.dirty = True

    def _material_tiles_for(self, owner):
        for ts in self.sets:
            if ts.tiles is not None and any(owner is layer or any(item is owner for item in layer.mask_effects + layer.effects)
                                            for layer in self._walk(ts.layers)):
                return ts.tiles
        return None

    def _require_legacy_rasters(self, owner):
        if self._material_tiles_for(owner) is not None:
            raise ValueError("This raster edit is not integrated with material tiles yet; tile pixels were preserved")

    def add_mask(self, value=1.0, idx=None, layer: Layer | None = None):
        lay = layer or (self.layer if idx is None else self.layers[idx])
        tiles = self._material_tiles_for(lay)
        if tiles is not None:
            self.commit_edit()
            self.end_stroke()
            return tiles.reset_raster(lay, mask=True, value=value)
        resolutions = {ts.res for ts in self.sets if any(item is lay for item in self._walk(ts.layers))}
        self.commit_edit()
        old = (lay.has_mask, lay.mask_tex)
        resolution = lay.raster_res or (self.res if self.res in resolutions else min(resolutions, default=self.res))
        texture = self.gpu.texture((resolution,) * 2, 1)
        self.gpu.fill(texture, (value, value, value, 1))
        self._push_undo(("mask", lay, old, self._edit_serial))
        lay.mask_tex = texture
        lay.raster_res = resolution
        lay.has_mask = True
        self._invalidate_properties([lay])

    def remove_mask(self, idx=None, layer: Layer | None = None):
        lay = layer or (self.layer if idx is None else self.layers[idx])
        self.set_property(lay, "has_mask", False)

    def fill_mask(self, value, idx=None, layer: Layer | None = None):
        lay = layer or (self.layer if idx is None else self.layers[idx])
        tiles = self._material_tiles_for(lay)
        if tiles is not None:
            self.commit_edit()
            self.end_stroke()
            return tiles.reset_raster(lay, mask=True, value=value)
        if lay.mask_tex is None:
            self.add_mask(value, layer=lay)
            return
        self._push_undo(("tex", lay, {"mask": self.gpu.clone(lay.mask_tex)}))
        self.gpu.fill(lay.mask_tex, (value, value, value, 1))
        self.dirty = True

    def clear_paint(self, idx=None, layer: Layer | None = None):
        lay = layer or (self.layer if idx is None else self.layers[idx])
        if lay.kind != "paint":
            return
        tiles = self._material_tiles_for(lay)
        if tiles is not None:
            self.commit_edit()
            self.end_stroke()
            return tiles.reset_raster(lay)
        if not len(lay.tex):
            return
        self._push_undo(("tex", lay, {k: self.gpu.clone(t) for k, t in lay.tex.items()}))
        for t in lay.tex.values():
            self.gpu.fill(t, (0, 0, 0, 0))
        self.dirty = True

    def set_geometry_mask(self, parts, layer: Layer | None = None):
        """Restrict a layer to mesh parts (list of part ids), or None for the whole mesh."""
        lay = layer or self.layer
        self.set_property(lay, "part_mask", None if parts is None else sorted(int(p) for p in parts))

    # ------------------------------------------------------------------ effects
    def add_effect(self, effect: str, layer: Layer | None = None, mask: bool | None = None, index=None,
                   blend=0, opacity=1.0, **params) -> Effect:
        """Add an effect to a layer's mask stack (mask=True) or content stack (mask=False).
        effect: one of layers.MASK_EFFECTS / CONTENT_EFFECTS. Generator params can be given as
        gen=MaskGen(...) or flat (kind=, level=, softness=, ...)."""
        kind = effect
        lay = layer or self.layer
        self._finish_stroke()
        if mask is None:
            mask = kind in MASK_EFFECTS and kind not in ("hsl", "brightness_contrast")
        if params.get("user_channel"):
            if mask or params["user_channel"] not in self.user_channels or kind not in ("invert", "levels", "blur", "brightness_contrast", "graph"):
                raise ValueError("User-channel effects require a declared scalar content target")
        if kind == "generator" and "gen" not in params:
            gen_fields = {k: params.pop(k) for k in list(params) if k in MaskGen.__dataclass_fields__}
            params["gen"] = MaskGen(**gen_fields) if gen_fields else MaskGen(kind=1)
        allowed = MASK_EFFECTS if mask else CONTENT_EFFECTS
        if kind not in allowed:
            raise ValueError(f"'{kind}' is not a {'mask' if mask else 'content'} effect")
        resolutions = {ts.res for ts in self.sets if any(item is lay for item in self._walk(ts.layers))}
        e = Effect(kind=kind, blend=blend, opacity=opacity, params=params)
        if kind == "paint":
            resolution = lay.raster_res or (self.res if self.res in resolutions else min(resolutions, default=self.res))
            e.tex = self.gpu.texture((resolution, resolution), 1)
            self.gpu.fill(e.tex, (float(e.params.get("initial", 0)),) * 4)
        self._push_undo(self._snapshot_stack())
        lst = lay.mask_effects if mask else lay.effects
        lst.insert(len(lst) if index is None else index, e)
        if kind == "paint":
            lay.raster_res = resolution
        self.dirty = True
        return e

    def copy_effect(self, effect, layer=None):
        lay = layer or self.layer
        for ts in self.sets:
            bind_anchor_references(ts.layers)
        stack = next((s for s in (lay.effects, lay.mask_effects) if any(e is effect for e in s)), None)
        if stack is None:
            raise ValueError("Effect does not belong to the layer")
        copied = Effect.from_dict(effect.to_dict())
        renew_persistent_ids(Layer("Copy", effects=[copied]))
        if effect.tex is not None:
            copied.tex = self.gpu.clone(effect.tex)
        self._push_undo(self._snapshot_stack())
        stack.insert(stack.index(effect) + 1, copied)
        self._invalidate_properties([lay])
        return copied

    def set_mask_paint_target(self, effect=None):
        self._finish_stroke()
        if effect is not None and (effect.kind != "paint" or not any(e is effect for e in self.layer.mask_effects)):
            raise ValueError("Select a paint effect on the active layer")
        self.mask_paint_target = effect
        self.brush.target = 1

    def active_mask_paint(self):
        effect = getattr(self, "mask_paint_target", None)
        return effect if self.layer and any(e is effect for e in self.layer.mask_effects) else None

    def fill_paint_effect(self, effect, value=0):
        self._validate_edit_target(effect)
        if effect.kind != "paint" or effect.tex is None:
            raise ValueError("Expected a mask paint effect")
        tiles = self._material_tiles_for(effect)
        if tiles is not None:
            self.commit_edit()
            self.end_stroke()
            return tiles.reset_raster(effect, mask=True, value=value)
        self._push_undo(("tex", effect, {"mask": self.gpu.clone(effect.tex)}))
        self.gpu.fill(effect.tex, (float(value),) * 4)
        self._invalidate_properties([effect])

    def remove_effect(self, effect: Effect, layer: Layer | None = None):
        self._finish_stroke()
        lay = layer or self.layer
        if not any(effect in lst for lst in (lay.effects, lay.mask_effects)):
            return
        self._push_undo(self._snapshot_stack())
        for lst in (lay.effects, lay.mask_effects):
            if effect in lst:
                lst.remove(effect)
        self.dirty = True

    def move_effect(self, effect: Effect, delta: int, layer: Layer | None = None):
        self._finish_stroke()
        lay = layer or self.layer
        for lst in (lay.effects, lay.mask_effects):
            if effect in lst:
                i = lst.index(effect)
                j = i + delta
                if 0 <= j < len(lst):
                    self._push_undo(self._snapshot_stack())
                    lst[i], lst[j] = lst[j], lst[i]
                    self.dirty = True
                return

    # ------------------------------------------------------------------ viewport
    def _render_pick(self):
        tri_ids = None
        if any(not ts.visible for ts in self.sets):
            visible = [ts.tri_ids for ts in self.sets if ts.visible]
            tri_ids = np.concatenate(visible) if visible else np.empty(0, np.int64)
        self.renderer.render_pick(self.gm, self._vp, *self.view_size, tri_ids=tri_ids,
                                  displaced_sets=self.sets if self.shader_workflow["displacement_meters"] else None)

    def update_view(self, w, h):
        self.view_size = (max(int(w), 1), max(int(h), 1))
        cam = self.camera
        self._vp = cam.proj(self.view_size[0] / self.view_size[1]) @ cam.view()
        if self.gm is not None:
            if self.shader_workflow["displacement_meters"]:
                self.update()
            self._render_pick()

    def pick(self, x, y):
        """(position, normal) under a viewport pixel (origin bottom-left), or None."""
        info = self.renderer.read_pick_info(x, y)
        self._last_pick = info
        return None if info is None else (info["pos"], info["nrm"])

    def pick_info(self, x, y):
        """Like pick(), with uv, triangle, mesh part and texture set index."""
        info = self.renderer.read_pick_info(x, y)
        self._last_pick = info
        if info is not None:
            info["set"] = self._set_of_tri(info["tri"])
        return info

    def _set_of_tri(self, tri):
        mat = self.mesh.tri_material
        if not (0 <= tri < len(mat)):
            return -1
        m = int(mat[tri])
        for i, ts in enumerate(self.sets):
            if m in ts.materials:
                return i
        return 0 if len(self.sets) == 1 else -1

    def update(self):
        self._finish_stroke(apply_only=True)
        while self.undo_stack and self.history_usage() > self.history_budget_bytes:
            self.memory_notice = "Older undo steps were released to stay within the history budget."
            self._release_entry(self.undo_stack.pop(0))
        for ts in self.sets:
            if ts.comp is None:
                continue
            root = self._root_index(self.layer, ts) if (ts is self.ts and self.layer is not None) else None
            started = time.perf_counter()
            if ts.dirty:
                ts.comp.composite(ts.layers, self.normal_strength, cache_at=root)
            elif ts.paint_dirty:
                k = self._root_index(self._stroke_layer, ts) if self._stroke_layer is not None else root
                ts.comp.composite(ts.layers, self.normal_strength, resume_from=k, cache_at=k)
            else:
                continue
            if self.renderer.mode == 6 and ts is self.ts and self.layer is not None:
                ts.comp.render_mask(self.layer)
            ts.dirty = ts.paint_dirty = False
            self.gpu.memory.timings.append({"set": ts.pid, "cpu_submission_seconds": time.perf_counter() - started,
                                            "passes": ts.comp.stats["passes"], "layers": ts.comp.stats["layers"]})

    def render(self, rect, cursor=None):
        """Draw the viewport into the bound framebuffer. rect=(x,y,w,h) in framebuffer pixels."""
        target = self.ctx.fbo
        self.update()
        if self.shader_workflow["displacement_meters"]:
            self._render_pick()
        target.use()
        if any(ts.tiles is not None for ts in self.sets if ts.visible):
            self.render_materials(rect)
        else:
            sets = [(ts.key, ts.comp, ts.bakes) for ts in self.sets if ts.visible and ts.comp is not None]
            self.renderer.render_sets(self.gm, self.camera, self._vp, sets, rect)
        self.renderer.draw_symmetry(self.gm, self._vp, rect, self.brush,
                                    [ts.key for ts in self.sets if ts.visible and ts.comp is not None])
        if cursor is not None:
            hit, nrm = cursor
            self.renderer.draw_cursor(hit, nrm, self.brush_radius(hit), self._vp, rect)

    def render_materials(self, rect, indices=None, tile_resolution=512, refresh=True):
        """Stream material/tile outputs into the bound target; report missing tiles.

        Tiled viewport resolution is capped separately from authored/export data.
        Picking continues to use the original mesh and global UV coordinates.
        """
        if (isinstance(tile_resolution, bool) or not isinstance(tile_resolution, (int, np.integer))
                or not 1 <= tile_resolution <= 8192):
            raise ValueError("Tile viewport resolution must be between 1 and 8192")
        indices = list(range(len(self.sets))) if indices is None else list(indices)
        if any(isinstance(index, bool) or not isinstance(index, (int, np.integer))
               or not 0 <= index < len(self.sets) for index in indices):
            raise ValueError("Invalid material viewport index")
        target = self.ctx.fbo
        if refresh:
            self.update()
        target.use()
        self.renderer.render_sets(self.gm, self.camera, self._vp, [], rect)
        diagnostics = []
        for index in indices:
            ts = self.sets[index]
            if not ts.visible:
                continue
            if ts.tiles is None:
                target.use()
                self.renderer.render_sets(self.gm, self.camera, self._vp, [(ts.key, ts.comp, ts.bakes)], rect, background=False)
                continue
            for address in ts.tile_addresses:
                try:
                    with ts.tiles.cached_evaluation(address, min(ts.res, tile_resolution), refresh) as tile:
                        target.use()
                        self.renderer.render_sets(self.gm, self.camera, self._vp, [(ts.key, tile.comp, tile.bakes)],
                                                  rect, background=False, tile_address=address)
                except ValueError as error:
                    diagnostics.append({"set_pid": ts.pid, "udim": address.udim, "message": str(error)})
        target.use()
        self.tile_render_diagnostics = diagnostics
        return diagnostics

    def render_2d(self, rect, channel="color", zoom=1.0, pan=(0.0, 0.0), ts_index=None, wire=False):
        """2D view of a texture-set channel: color, roughness, metallic, height, opacity, normal,
        emissive, mask, or a mesh map (ao, curvature, thickness, id, position, world_normal)."""
        ts = self.sets[self.active if ts_index is None else ts_index]
        target = self.ctx.fbo
        self.update()
        target.use()
        c = ts.comp
        tex, comp = {"color": (c.color, -1), "roughness": (c.rmh, 0), "metallic": (c.rmh, 1),
                     "height": (c.rmh, 2), "opacity": (c.rmh, 3), "normal": (c.normal, -1),
                     "emissive": (c.emissive, -1), "mask": (c.mask_preview, 0)}.get(channel, (None, -1))
        if tex is None and channel in c.user_outputs:
            tex, comp = c.user_outputs[channel], 0
        if tex is None:
            m = ts.bakes.maps().get(channel)
            tex, comp = (m, -1) if m is not None else (c.color, -1)
        return self.renderer.render_2d(self.gm, ts.key, tex, rect, zoom, pan, comp, wire,
                                       color_transform=self.color if channel in ("color", "emissive") else None)

    # ------------------------------------------------------------------ painting
    def brush_radius(self, hit, tri=-1, brush=None):
        b = self.brush if brush is None else brush
        if b.size_space == 1 and self.mesh is not None:
            return b.size_obj * self.mesh.radius
        if b.size_space == 2 and self.mesh is not None:
            topo = self.mesh.topology
            if tri < 0 and self._last_pick is not None:
                tri = self._last_pick.get("tri", -1)
            s = topo.uv_scale(tri) if 0 <= tri < topo.n_tris else self.mesh.radius
            return b.size_uv * 0.5 * s
        return b.size_px * 0.5 * self.camera.world_per_pixel(hit, self.view_size[1])

    def can_paint(self):
        lay = self.layer
        if self.brush.target == 2:
            return self.ts is not None
        if lay is None or not lay.visible:
            return False
        if self.brush.target == 1:
            effect = self.active_mask_paint()
            return effect is None or (effect.enabled and lay.mask_enabled)
        return lay.kind == "paint"

    def _view(self) -> View:
        cam = self.camera
        return View(vp=self._vp, size=self.view_size, campos=cam.eye, right=cam.right,
                    pick_pos=self.renderer.pick_pos, pick_uv=self.renderer.pick_uv,
                    wpp=lambda p: cam.world_per_pixel(p, self.view_size[1]))

    def _surface(self, hit, pressure=1.0, info=None) -> Surface:
        hit = np.asarray(hit, float)
        if info is None and self._last_pick is not None and np.linalg.norm(self._last_pick["pos"] - hit) < 1e-5:
            info = self._last_pick
        if info is None:
            px = self._view().project(hit)
            if px is not None:
                info = self.renderer.read_pick_info(px[0], px[1])
                if info is not None and np.linalg.norm(info["pos"] - hit) > self.mesh.radius * 0.05:
                    info = None
        if info is None:
            return Surface(hit, np.array([0.0, 1.0, 0.0]), np.zeros(2), -1, pressure)
        return Surface(hit, np.asarray(info["nrm"], float), np.asarray(info["uv"], float),
                       int(info.get("tri", -1)), pressure)

    def ensure_quick_mask(self, value=1.0):
        ts = self.ts
        if ts.quick is None:
            ts.quick = self.gpu.texture((ts.res, ts.res), 1)
            self.gpu.fill(ts.quick, (value, value, value, 1))
        return ts.quick

    def clear_quick_mask(self, value=1.0):
        self.gpu.fill(self.ensure_quick_mask(value), (value, value, value, 1))

    def set_clone_source(self, x, y):
        """Viewport pixel (origin bottom-left) the clone tool copies from."""
        self.clone_source = np.array([float(x), float(y)])
        self.clone_offset = None

    def begin_stroke(self, hit, pressure=1.0, info=None, seed=None, view=None):
        if self.shader_workflow["displacement_meters"] and (view is None or view.uv_mapping is None):
            return False  # Edit in UV space while inspecting displaced geometry.

        if self.ts is not None and self.ts.tiles is not None:
            if self.brush.tool in (TOOL_CLONE, TOOL_SMUDGE) or self.brush.target == 2 or self.quick_mask_enabled:
                raise ValueError("Tiled clone, smudge and quick-mask strokes are not integrated yet")
            if not self.can_paint() or (self.brush.target == 0 and not self.brush.user_channel and not any(self.brush.enabled)):
                return False
            self.commit_edit()
            self._finish_stroke()
            surface = self._surface(hit, pressure, info)
            if surface.tri not in self.ts.tri_ids:
                return False
            from .tilestroke import TileStroke
            self._tile_stroke = TileStroke(self.ts.tiles, pressure=pressure, seed=seed, surface=surface,
                                           view=self._view() if view is None else view)
            return True
        self.commit_edit()
        lay = self.layer
        if not self.can_paint():
            return False
        self._finish_stroke()
        b = freeze_brush(self.brush)
        if b.user_channel and b.user_channel not in self.user_channels:
            raise ValueError("The selected user channel is no longer declared")
        if b.target == 0 and not b.user_channel and not any(b.enabled):
            return False
        target = {0: "layer", 1: "mask", 2: "quick"}.get(int(b.target), "layer")
        effect = self.active_mask_paint() if target == "mask" else None
        if target == "mask" and effect is None and (lay.mask_tex is None or not lay.has_mask):
            self.add_mask(0.0 if b.mask_value > 0.5 else 1.0, layer=lay)
        if target == "layer":
            textures = lay.tex
        elif target == "mask":
            textures = effect.tex if effect is not None else lay.mask_tex
        else:
            textures = self.ensure_quick_mask()
        view = self._view() if view is None else view
        surf = self._surface(hit, pressure, info)
        offset = None
        if int(b.tool) == TOOL_CLONE:
            if view.uv_mapping is not None:
                source = getattr(self, "clone_uv_source", None)
                if source is None:
                    return False
                if getattr(self, "clone_uv_offset", None) is None:
                    self.clone_uv_offset = np.asarray(source) - surf.uv
                offset = view.uv_mapping.pixel_delta(self.clone_uv_offset)
            else:
                if self.clone_source is None:
                    return False
                if self.clone_offset is None:
                    start = view.project(surf.pos)
                    self.clone_offset = self.clone_source - (start if start is not None else 0)
                offset = self.clone_offset
        quick = self.ts.quick if (self.quick_mask_enabled and target != "quick") else None
        self._stroke = Stroke(self.painter, self.gm, self.ts.key, b, view,
                              lambda p, tri: self.brush_radius(p, tri), target, textures, quick=quick,
                              mask_value=b.mask_value, clone_offset=offset,
                              seed=b.seed if seed is None else seed)
        frozen = self._stroke.brush
        stroke = self._stroke
        if view.uv_mapping is not None:
            stroke.radius_fn = lambda p, tri: self.uv_brush_radius(tri, stroke.view.uv_mapping, frozen)
        else:
            stroke.radius_fn = lambda p, tri: self.brush_radius(p, tri, brush=frozen)
        self._stroke_layer = (effect or lay) if target != "quick" else None
        self.journal.begin(self, stroke, self._stroke_layer)
        self._stroke.start(surf)
        self._mark_stroke_dirty()
        return True

    def _mark_stroke_dirty(self):
        if self._stroke is None or self._stroke.target == "quick":
            return
        owner = self._stroke_layer
        for ts in self.sets:
            if any(layer is owner or any(effect is owner for effect in layer.mask_effects) for layer in self._walk(ts.layers)):
                ts.paint_dirty = True

    def stroke_to(self, hit, pressure=1.0, info=None):
        if getattr(self, "_tile_stroke", None) is not None:
            try:
                if self._tile_stroke.operation["coordinate_space"] != "surface":
                    raise ValueError("Use stroke_uv_to for a UV stroke")
                self._tile_stroke.feed_surface(self._surface(hit, pressure, info), self._view())
            except Exception:
                self.cancel_stroke()
                raise
            return
        if self._stroke is None:
            return
        if self._stroke.view.uv_mapping is not None:
            raise ValueError("Use stroke_uv_to for a UV stroke")
        self._stroke.view = self._view()
        self._stroke.feed(self._surface(hit, pressure, info))
        self._mark_stroke_dirty()

    def end_stroke(self):
        self._finish_stroke()

    def pick_uv(self, uv):
        """Native UV sample in the active set; None on empty/outside-tile background."""
        if self.ts is None or self.mesh is None:
            return None
        tri = uv_triangle(self.mesh, self.ts.tri_ids, uv, single_tile=self.ts.tiles is None)
        if tri is None:
            return None
        uv = np.asarray(uv, float)
        return {"pos": np.array([*uv, 0.]), "nrm": np.array([0., 0., 1.]), "uv": uv,
                "tri": tri, "set": self.active}

    def uv_brush_radius(self, tri, mapping, brush=None):
        b = self.brush if brush is None else brush
        if b.size_space == 0:
            return b.size_px * .5 * mapping.units_per_pixel
        if b.size_space == 2:
            return b.size_uv * .5
        scale = self.mesh.topology.uv_scale(tri) if tri >= 0 else self.mesh.radius
        return b.size_obj * self.mesh.radius / max(scale, 1e-9)

    def uv_tool_reason(self):
        if self.ts is not None and self.ts.tiles is not None:
            if self.brush.tool in (TOOL_CLONE, TOOL_SMUDGE) or self.brush.target == 2 or self.quick_mask_enabled:
                return "Tiled clone, smudge and quick-mask strokes are not integrated yet."
        if self.brush.symmetry:
            return "Object symmetry is unavailable in 2D: turn Symmetry off, or paint in 3D."
        if self.brush.tool == TOOL_CLONE and getattr(self, "clone_uv_source", None) is None:
            return "Clone in 2D: hold V and click a UV island to set a separate UV source."
        return ""

    def set_uv_clone_source(self, uv):
        if self.pick_uv(uv) is None:
            return False
        self.clone_uv_source = np.asarray(uv, float).copy()
        self.clone_uv_offset = None
        return True

    def _uv_view(self, mapping):
        return View(np.eye(4), mapping.size, np.array([0., 0., 1.]), np.array([1., 0., 0.]),
                    self.bakes.cov, None, lambda p: mapping.units_per_pixel, uv_mapping=mapping)

    def begin_uv_stroke(self, uv, mapping: UVMapping, pressure=1., seed=None):
        info = self.pick_uv(uv)
        if info is None or self.uv_tool_reason():
            return False
        if self.ts.tiles is not None:
            if not self.can_paint() or (self.brush.target == 0 and not self.brush.user_channel and not any(self.brush.enabled)):
                return False
            self.commit_edit()
            self._finish_stroke()
            from .tilestroke import TileStroke
            self._tile_stroke = TileStroke(self.ts.tiles, uv, mapping, pressure, seed)
            return True
        view = self._uv_view(mapping)
        return self.begin_stroke(info["pos"], pressure, info, seed, view=view)

    def stroke_uv_to(self, uv, pressure=1., mapping=None):
        if getattr(self, "_tile_stroke", None) is not None:
            try:
                self._tile_stroke.feed(uv, pressure, mapping)
            except Exception:
                self.cancel_stroke()
                raise
            return
        if self._stroke is None:
            return
        if self._stroke.view.uv_mapping is None:
            raise ValueError("Use stroke_to for a 3D stroke")
        if mapping is not None:
            self._stroke.view = self._uv_view(mapping)
            if self._stroke.tool == TOOL_CLONE:
                self._stroke.clone_offset = mapping.pixel_delta(self.clone_uv_offset)
        info = self.pick_uv(uv)
        if info is None:
            self._stroke.recorded_samples.append({"event": "break", "uv": np.asarray(uv).tolist(),
                                                  "seconds": time.monotonic() - self._stroke.started_at})
            self._stroke.last = None  # reentry starts a fresh dab, without bridging empty space
            self._stroke.last_px = None
            self._stroke.carry = 0.
            return
        self._stroke.feed(self._surface(info["pos"], pressure, info))
        self._mark_stroke_dirty()

    def _finish_stroke(self, apply_only=False):
        if getattr(self, "_tile_stroke", None) is not None:
            if not apply_only:
                session, self._tile_stroke = self._tile_stroke, None
                try:
                    session.finish()
                except Exception:
                    session.cancel()
                    raise
            return
        st = self._stroke
        if st is None:
            return
        st.apply()
        if apply_only:
            return
        snap = st.release(keep_snapshot=True)
        owner = self.ts if st.target == "quick" else self._stroke_layer
        regions = {}
        try:
            for key, texture in snap.items():
                bounds = deltas.changed_bounds(self.gpu, texture, self._delta_texture(owner, key, st.target))
                if bounds is not None:
                    regions[key] = (bounds, deltas.crop(self.gpu, texture, bounds))
        except Exception as error:
            for _, texture in regions.values():
                texture.release()
            self.memory_notice = f"Region history fallback: {error}"
            entry = (("quick", self.ts, {"quick": snap["mask"]}) if st.target == "quick" else ("tex", owner, snap))
            self._push_undo(entry, journal_stroke=True)
        else:
            for texture in snap.values():
                texture.release()
            if regions or (st.dabs and st.target != "quick"):
                self._push_undo(("delta", owner, regions, self._edit_serial, st.target), journal_stroke=True)
        self._stroke = None
        self._stroke_layer = None
        try:
            self.journal.finish(self, st, owner)
        except Exception:
            self.journal.invalidate(owner, st.target)
            raise
        finally:
            self.journal.remember(self._edit_serial)

    @staticmethod
    def _delta_texture(owner, key, target):
        if target == "quick":
            return owner.quick
        if target == "mask":
            return owner.tex if isinstance(owner, Effect) else owner.mask_tex
        return owner.tex[key]

    def _cancel_stroke(self):
        if getattr(self, "_tile_stroke", None) is not None:
            session, self._tile_stroke = self._tile_stroke, None
            session.cancel(restore=False)
        if self._stroke is not None:
            self._stroke.release()
            self._stroke = None
            self._stroke_layer = None

    def cancel_stroke(self):
        """Restore authored pixels without allocating another snapshot (budget-safe)."""
        if getattr(self, "_tile_stroke", None) is not None:
            session, self._tile_stroke = self._tile_stroke, None
            session.cancel()
            return True
        if self._stroke is None:
            return False
        stroke, owner = self._stroke, self._stroke_layer
        target = self.ts if stroke.target == "quick" else owner
        for key, saved in stroke.snapshot.items():
            self.gpu.blit(saved, self._delta_texture(target, key, stroke.target))
        self._cancel_stroke()
        self._invalidate_properties([self] if stroke.target == "quick" else [owner])
        return True

    def add_authored_path(self, points, kind="path", width=.04, name=None):
        from .authored import path,anchor_uv,validate
        anchors=[copy.deepcopy(p) if isinstance(p,dict) and "bary" in p else anchor_uv(self.mesh,p,self.ts.tri_ids) for p in points]
        value=path(self.mesh,anchors,kind,width)
        validate(value,self.mesh,self.ts.tri_ids)
        layer=self.add_layer(kind="fill",name=name or kind.title())
        layer.authored=value
        layer.color=list(self.brush.color)
        self._invalidate_properties([layer])
        return layer

    def add_text(self, text, font, name=None):
        from .authored import text as definition,validate,font_atlas
        value=definition(font,text);validate(value)
        font_atlas(value,min(self.res,256))  # Reject missing/invalid fonts before inserting a layer.
        layer=self.add_layer(kind="fill",name=name or "Text")
        layer.authored=value
        layer.color=list(self.brush.color)
        self._invalidate_properties([layer])
        return layer

    def set_authored(self, layer=None, **changes):
        layer=layer or self.layer
        if layer is None or layer.authored is None:raise ValueError("Select an authored object")
        return self.set_properties(layer,authored=dict(copy.deepcopy(layer.authored),**changes))

    def set_path_point(self,index,uv=None,layer=None,**profile):
        from .authored import anchor_uv
        layer=layer or self.layer
        if layer is None or layer.authored is None or layer.authored["kind"]=="text":raise ValueError("Select a surface path")
        points=copy.deepcopy(layer.authored["points"])
        if type(index) is not int or not 0<=index<len(points):raise ValueError("Invalid path point index")
        if set(profile)-{"width","pressure"}:raise ValueError("Unknown path point profile")
        owner=next(ts for ts in self.sets if any(item is layer for item in self._walk(ts.layers)))
        if uv is not None:
            anchor=anchor_uv(self.mesh,uv,owner.tri_ids)
            anchor.update({key:points[index][key] for key in ("width","pressure")})
            points[index]=anchor
        points[index].update(profile)
        return self.set_authored(layer,points=points)

    def paint_path(self, points, closed=False, samples_per_segment=12, pressure=1.0):
        """Paint along a smooth curve through surface points (world positions or pick infos)."""
        infos = []
        for p in points:
            if isinstance(p, dict):
                infos.append(p)
            else:
                s = self._surface(p)
                infos.append({"pos": s.pos, "nrm": s.nrm, "uv": s.uv, "tri": s.tri})
        if len(infos) < 2:
            return False
        P = [np.asarray(i["pos"], float) for i in infos]
        if closed:
            P = P + P[:2]
            infos = infos + infos[:2]
        pts = []
        n = len(P)
        for i in range(n - 1):
            p0, p1, p2, p3 = P[max(i - 1, 0)], P[i], P[i + 1], P[min(i + 2, n - 1)]
            for t in np.linspace(0, 1, samples_per_segment, endpoint=False):
                t2, t3 = t * t, t * t * t
                q = 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
                a, b = infos[i], infos[i + 1]
                nrm = np.asarray(a["nrm"]) * (1 - t) + np.asarray(b["nrm"]) * t
                uv = np.asarray(a["uv"]) * (1 - t) + np.asarray(b["uv"]) * t
                pts.append({"pos": q, "nrm": nrm / max(np.linalg.norm(nrm), 1e-9), "uv": uv,
                            "tri": b.get("tri", -1) if t > 0.5 else a.get("tri", -1)})
        pts.append(infos[-1])
        if not self.begin_stroke(pts[0]["pos"], pressure, pts[0]):
            return False
        for p in pts[1:]:
            self.stroke_to(p["pos"], pressure, p)
        self.end_stroke()
        return True

    # ------------------------------------------------------------------ polygon fill / selection
    def select_triangles(self, x, y, mode=0, angle_deg=1.0):
        """Triangle ids under a viewport pixel, expanded by mode
        (0 triangle, 1 polygon, 2 UV island, 3 mesh part, 4 texture set)."""
        info = self.renderer.read_pick_info(x, y)
        if info is None:
            return np.zeros(0, np.int64)
        return self.mesh.topology.expand([info["tri"]], mode, angle_deg)

    def select_triangles_rect(self, x0, y0, x1, y1, mode=0, lasso=None):
        """Visible triangles inside a rectangle (or a lasso polygon of viewport pixels)."""
        if lasso is not None:
            pts = np.asarray(lasso, float)
            x0, y0 = pts.min(0); x1, y1 = pts.max(0)
        ids, (ox, oy) = self.renderer.read_pick_region(x0, y0, x1, y1)
        if lasso is not None:
            hh, ww = ids.shape
            yy, xx = np.mgrid[0:hh, 0:ww]
            inside = _point_in_poly(xx + ox + 0.5, yy + oy + 0.5, pts)
            ids = np.where(inside, ids, -1)
        tris = np.unique(ids[ids >= 0])
        return self.mesh.topology.expand(tris, mode)

    def polygon_fill(self, tris, erase=False, target=None, mask_value=None):
        """Fill triangles of the active texture set on the selected layer (paint channels from the
        brush), its mask, or the quick mask. target: 0 layer, 1 mask, 2 quick mask (default brush.target)."""
        ts = self.ts
        tris = np.asarray(tris, np.int64)
        tris = tris[np.isin(tris, ts.tri_ids)]
        if tris.size == 0:
            return False
        target = int(self.brush.target if target is None else target)
        lay = self.layer
        if ts.tiles is not None:
            if target == 2 or self.quick_mask_enabled:
                raise ValueError("Quick-mask polygon fill is not integrated with material tiles yet")
            if lay is None or (target == 0 and (lay.kind != "paint" or (not self.brush.user_channel and not any(self.brush.enabled)))):
                return False
            self.commit_edit()
            self._finish_stroke()
            owner = (self.active_mask_paint() or lay) if target == 1 else lay
            return ts.tiles.fill_triangles(owner, tris, self.brush, mask=target == 1, erase=erase,
                                          value=self.brush.mask_value if mask_value is None else mask_value)
        view = self._view()
        self._finish_stroke()
        if target == 2:
            q = self.ensure_quick_mask()
            self._push_undo(("quick", ts, {"quick": self.gpu.clone(q)}))
            self.painter.fill_tris(self.gm, tris, q, self.brush, view, erase,
                                   self.brush.mask_value if mask_value is None else mask_value)
        elif target == 1:
            value = self.brush.mask_value if mask_value is None else mask_value
            effect = self.active_mask_paint()
            if effect is not None:
                self._push_undo(("tex", effect, {"mask": self.gpu.clone(effect.tex)}))
                self.painter.fill_tris(self.gm, tris, effect.tex, self.brush, view, erase, value)
                self._invalidate_properties([effect])
                return True
            if lay.mask_tex is None or not lay.has_mask:
                self.add_mask(0.0 if (value > 0.5 and not erase) else 1.0, layer=lay)
            self._push_undo(("tex", lay, {"mask": self.gpu.clone(lay.mask_tex)}))
            self.painter.fill_tris(self.gm, tris, lay.mask_tex, self.brush, view, erase,
                                   self.brush.mask_value if mask_value is None else mask_value)
        else:
            if lay is None or lay.kind != "paint":
                return False
            from .userchannels import paint_channels
            keys = [c.key for c in paint_channels(self.brush)]
            if not keys:
                return False
            if hasattr(lay.tex, "ensure"):
                lay.tex.ensure(keys)
            self._push_undo(("tex", lay, {key: self.gpu.clone(lay.tex[key]) for key in keys}))
            self.painter.fill_tris(self.gm, tris, lay.tex, self.brush, view, erase)
        ts.dirty = True
        return True

    # ------------------------------------------------------------------ picker
    def pick_material(self, x, y, apply=True) -> dict | None:
        """Material picker: read the composited channels under a viewport pixel and (optionally)
        load them into the brush."""
        info = self.pick_info(x, y)
        if info is None or info.get("set", -1) < 0:
            return None
        ts = self.sets[info["set"]]
        self.update()
        if ts.tiles is None:
            vals = ts.comp.sample(info["uv"])
        else:
            from .tiles import address_at
            address = address_at(info["uv"], ts.tiles.addresses)
            uv = np.asarray(info["uv"]) - np.asarray(address.to_list())
            # The picker reads authored-resolution accumulators, independently of
            # viewport LOD and the selected material. No texture escapes the lease.
            with ts.tiles.evaluate(address) as tile:
                vals = tile.comp.sample(uv)
        if self.color.managed:
            for key in ("color", "emissive"):
                vals[key] = self.color.encoded(vals[key]).tolist()
        if apply:
            b = self.brush
            b.color, b.rough, b.metal = vals["color"], vals["rough"], vals["metal"]
            b.height, b.opac, b.emissive, b.normal = vals["height"], vals["opac"], vals["emissive"], vals["normal"]
        return vals

    # ------------------------------------------------------------------ Substance 3D Painter content
    def add_imported(self, result, index=None, parent=None, record=True, progress=None, max_dabs=150000, per_layer=40000):
        """Insert a converted Painter smart material (substance.convert.ImportResult) into the
        active texture set as one undo step; paint strokes are replayed. Returns the new layers."""
        from .substance import apply
        return apply.add_imported(self, result, index=index, parent=parent, record=record, progress=progress, max_dabs=max_dabs, per_layer=per_layer)

    def apply_mask_state(self, mask, idx=None, layer=None, replace=False, **options):
        """Apply a converted Painter smart mask (substance.convert.MaskBuild) to a layer (default:
        the selected one) as one undo step. Returns False when there is nothing to apply."""
        self._require_legacy_rasters(layer or (self.layer if idx is None else self.layers[idx]))
        from .substance import apply
        lay = layer if layer is not None else (self.layers[idx] if idx is not None and 0 <= idx < len(self.layers)
                                               else self.layer)
        return apply.apply_mask(self, mask, lay, replace=replace, **options)

    def import_painter_project(self, proj, ao_samples=96, progress=None, max_dabs=150000, per_layer=40000):
        """Replace the project with an imported .spp (substance.importer.ProjectImport): mesh, every
        texture set and its layer stack, with recorded paint strokes replayed. Returns dabs painted."""
        from .substance import apply
        return apply.import_project(self, proj, ao_samples=ao_samples, progress=progress, max_dabs=max_dabs, per_layer=per_layer)

    def continue_import(self, max_dabs=150000, per_layer=40000, progress=None):
        from .substance.session import resume
        self._finish_stroke()
        return resume(self,max_dabs,per_layer,progress)

    def discard_import_continuation(self):
        if self.import_state and self.import_state["status"]!="complete":
            self.import_state=None
            self._edit_serial+=1

    # ------------------------------------------------------------------ save / load
    # ------------------------------------------------------------------ unsaved changes
    def _signature(self) -> str:
        """Fingerprint of everything a save writes that the user edits: texture sets, their
        resolution and bake settings, and every layer's settings (UI-only state such as which
        folders are expanded is ignored). Pixel edits are tracked by _edit_serial instead."""
        def strip(d):
            d.pop("expanded", None)
            d.pop("raster_res", None)
            for c in d.get("children", []):
                strip(c)
            return d
        state = {"mesh": id(self.mesh), "normal_strength": self.normal_strength,
                 "sets": [{"name": ts.name, "res": ts.res, "bake": ts.bake_settings.to_dict(),
                           "description": getattr(ts, "description", ""),
                           "layers": [strip(l.to_dict()) for l in ts.layers]} for ts in self.sets]}
        state["user_channels"] = self.user_channels
        state["shader_workflow"] = self.shader_workflow
        state["export_settings"] = self.export_settings
        if self.import_state:
            state["import_replay"]={k:v for k,v in self.import_state.items() if k!="tasks"}
        if self.color.managed:
            state["color"] = self.color.metadata()
        return hashlib.md5(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()

    def mark_saved(self):
        """Record the current state as saved (called by new_project, load and save)."""
        self._saved_serial = self._edit_serial
        self._saved_sig = self._signature() if self.mesh is not None else None

    def mark_modified(self):
        """Mark recovered/imported content as requiring a user save."""
        self._serial_counter = max(self._serial_counter, self._edit_serial, self._saved_serial) + 1
        self._edit_serial = self._serial_counter

    @property
    def modified(self) -> bool:
        """True when the project has changes since it was created, opened or last saved.
        Computed on demand (serialises the layer settings): call it when needed, not every frame."""
        if self.mesh is None or not self.sets:
            return False
        if self._stroke is not None or getattr(self, "_tile_stroke", None) is not None or self._edit_serial != self._saved_serial:
            return True
        return self._signature() != self._saved_sig

    def _project_snapshot(self, path, portable=False):
        if self.mesh is None or not self.sets:
            raise ValueError("There is no project to save")
        self._finish_stroke()
        for ts in self.sets:
            if ts.bake_settings.ray_correction_pid or ts.bake_settings.distance_correction_pid:
                ts.bake_settings.correction_hashes = self._current_correction_hashes(ts)
        arrays = {}
        m = self.mesh
        for k in ("positions", "normals", "uvs", "indices", "tangents", "curvature", "parts", "colors",
                  "tri_material"):
            arrays["mesh_" + k] = getattr(m, k)
        seen = {}
        sets = []

        def ser(lay, prefix):
            if id(lay) in seen:
                return {"instance": seen[id(lay)]}
            seen[id(lay)] = prefix
            d = lay.to_dict()
            d["_id"] = prefix
            if lay.tex:
                from .userchannels import descriptor
                for channel in (descriptor(key) for key in lay.tex):
                    if channel.key in lay.tex:
                        arrays[f"{prefix}_{channel.key}"] = self.gpu.read(lay.tex[channel.key]).astype(
                            np.dtype(channel.paint_dtype))
            if lay.mask_tex is not None:
                arrays[f"{prefix}_mask"] = self.gpu.read(lay.mask_tex).astype(np.float16)
            for effect in lay.mask_effects:
                if effect.kind == "paint" and effect.tex is not None:
                    arrays[f"effect_{effect.pid}"] = self.gpu.read(effect.tex).astype(np.float16)
            d["children"] = [ser(c, f"{prefix}c{i}") for i, c in enumerate(lay.children)]
            return d

        for si, ts in enumerate(self.sets):
            bind_anchor_references(ts.layers)
            sd = {"name": ts.name, "pid": ts.pid, "materials": ts.materials, "res": ts.res,
                         "selected": ts.selected, "bake": ts.bake_settings.to_dict(),
                         "description": ts.description,
                         "layers": [ser(l, f"S{si}L{i}") for i, l in enumerate(ts.layers)]}
            cache = {}
            for name, texture in ts.bakes.maps().items():
                if texture is not None:
                    key = f"bake{si}_{name}"
                    arrays[key] = self.gpu.read(texture)
                    cache[name] = {"array": key, "dtype": texture.dtype,
                                   "sha256": hashlib.sha256(arrays[key].tobytes()).hexdigest()}
            sd["cache"] = {"maps": cache, "hp_hits": float(ts.bakes.hp_hits),
                           "source_hashes": list(getattr(ts.bakes, "_source_hashes", [])),
                           "baked_settings": copy.deepcopy(getattr(ts.bakes, "_settings_snapshot", {}))}
            sets.append(sd)
            if ts.tiles is not None:
                tile_meta, tile_arrays = ts.tiles.snapshot()
                for backing in (tile_meta["backing"], tile_meta["base"]):
                    for page in backing["pages"]:
                        for texture in page["textures"]:
                            name = texture["array"]
                            member = f"tile_set{si}_" + name
                            arrays[member] = tile_arrays[name]
                            texture["array"] = member
                sd["tiles"] = tile_meta
        meta = {"version": SAVE_VERSION, "mesh_name": m.name, "material_names": m.material_names,
                "part_names": m.part_names, "mesh_extra": copy.deepcopy(m.extra),
                "res": self.res, "selected": self.selected,
                "active": self.active, "normal_strength": self.normal_strength, "sets": sets,
                "brush": self.brush.to_dict(), "camera": self.camera.to_dict(),
                "environment": self.renderer.env_path,
                "display": {key: getattr(self.renderer, key) for key in
                            ("exposure", "env_rot", "emissive_intensity", "alpha_test", "use_ao")}}
        if meta["brush"].get("user_channel") not in self.user_channels:
            meta["brush"]["user_channel"] = None
        if self.export_settings:
            meta["export_settings"] = copy.deepcopy(self.export_settings)
        if any(e.kind == "paint" for ts in self.sets for l in self._walk(ts.layers) for e in l.mask_effects):
            meta["version"] = 4
        if any(layer.raster_res is not None and layer.raster_res != ts.res for ts in self.sets for layer in self._walk(ts.layers)):
            meta["version"] = 5
        if self.color.managed:
            meta["version"], meta["color"] = 6, self.color.metadata()
        if self.journal.nodes:
            meta["version"], meta["journal"] = 7, self.journal.snapshot(arrays)
        if any(layer.proj.repeat_meters for ts in self.sets for layer in self._walk(ts.layers)):
            meta["version"] = 8
        if any(ts.tiles is not None for ts in self.sets):
            meta["version"] = 9
        from .bakecontrol import DEFAULTS
        if any(any(key in sd["bake"] for key in DEFAULTS) for sd in meta["sets"]):
            meta["version"] = 10
        if self.import_reports or self.import_state or any(effect.kind=="graph" for layer in self.all_layers_all_sets() for effect in layer.effects+layer.mask_effects):
            meta["version"] = 11
            meta["imports"] = {"reports":copy.deepcopy(self.import_reports),"continuation":copy.deepcopy(self.import_state)}
        if any(layer.authored is not None or layer.proj.warp is not None or layer.proj.decal or
               any(isinstance(effect.params.get("proj"),Projection) and (effect.params["proj"].warp is not None or effect.params["proj"].decal) for effect in layer.mask_effects)
               for layer in self.all_layers_all_sets()):meta["version"]=12
        from .userchannels import DEFAULT_WORKFLOW
        if self.user_channels or self.shader_workflow != DEFAULT_WORKFLOW:
            meta["version"] = 13
            meta["user_channels"] = copy.deepcopy(self.user_channels)
            meta["shader_workflow"] = copy.deepcopy(self.shader_workflow)
        if self.export_settings:
            meta["version"] = 14
        meta, blobs, records, diagnostics = projectio.package_resources(
            meta, path, portable, self.project_resources, BUILTIN_ALPHAS)
        for sd in meta["sets"]:
            sd["cache"]["provenance"] = projectio.bake_fingerprint(meta, arrays, sd)
        projectio.validate(meta, arrays)
        return meta, arrays, blobs, records, diagnostics

    def save(self, path, portable=False, backups=0):
        """Atomically save a v3 project; portable embeds its external dependencies."""
        self.commit_edit()
        meta, arrays, blobs, records, diagnostics = self._project_snapshot(path, portable)
        projectio.atomic_write(path, meta, arrays, blobs, backups)
        self.project_path = os.path.abspath(path)
        self.project_resources, self.project_diagnostics = records, diagnostics
        self.mark_saved()

    def autosave(self, path, backups=3):
        """Write a portable recovery snapshot without clearing the user's modified state."""
        meta, arrays, blobs, _, _ = self._project_snapshot(path, portable=True)
        projectio.atomic_write(path, meta, arrays, blobs, backups)
        return os.path.abspath(path)

    def load(self, path, progress=None):
        """Restore staged CPU/GPU state; failures leave the current project intact."""
        original, data, blobs = projectio.read_archive(path)
        meta, records, diagnostics, temp = projectio.resolve_resources(original, blobs, path, BUILTIN_ALPHAS)
        stage = object.__new__(type(self))
        stage.__dict__ = self.__dict__.copy()
        stage.sets, stage.undo_stack, stage.redo_stack = [], [], []
        stage._edit_transaction = None
        stage._tile_stroke = None
        stage.gm, stage.mesh, stage._stroke, stage._stroke_layer = None, None, None, None
        stage.high_meshes = {}
        stage._high_hashes = {}
        stage.resources = Resources(self.gpu)
        stage.painter = Painter(self.gpu, stage.resources)
        stage.camera, stage.brush = Camera(), Brush()
        stage.renderer = SimpleNamespace(gpu=self.gpu, env_path=None, env_tex=None)
        stage._loading_layers = []
        stage.project_resources, stage.project_diagnostics = records, diagnostics
        stage._project_tempdir = temp
        try:
            stage._restore_project(meta, original, data, progress)
            scene = self.renderer.program_for(stage.color)
        except Exception:
            for layer in stage._loading_layers:
                stage._release_layer(layer)
            stage._release_project()
            stage.resources.release()
            if stage.renderer.env_tex is not None:
                stage.renderer.env_tex.release()
            if temp is not None:
                temp.cleanup()
            raise
        self._adopt_project_stage(stage, scene, path)

    def _adopt_project_stage(self, stage, scene, path=None):
        """Publish a fully restored/evaluated project on the owning GL thread."""
        old_temp = self._project_tempdir
        renderer, brush = self.renderer, self.brush
        self._release_project()
        self.resources.release()
        if renderer.env_tex is not None:
            renderer.env_tex.release()
        for key, value in stage.__dict__.items():
            if key not in ("renderer", "brush", "_loading_layers"):
                self.__dict__[key] = value
        brush.load_dict(stage.brush.to_dict())
        self.brush, self.renderer = brush, renderer
        for ts in self.sets:
            if ts.tiles is not None:
                ts.tiles.engine = self
        renderer.env_tex, renderer.env_path = stage.renderer.env_tex, stage.renderer.env_path
        renderer.pipeline, renderer.scene = self.color, scene
        for key in ("exposure", "env_rot", "emissive_intensity", "alpha_test", "use_ao"):
            setattr(renderer, key, getattr(stage.renderer, key))
        self.project_path = os.path.abspath(path) if path else None
        self.clone_source, self.clone_offset, self._last_pick = None, None, None
        self.clone_uv_source = self.clone_uv_offset = None
        if old_temp is not None:
            old_temp.cleanup()
        self.dirty = True
        self.mark_saved()

    def _restore_project(self, meta, original, data, progress=None):
        from .userchannels import DEFAULT_WORKFLOW
        self.export_settings = copy.deepcopy(meta.get("export_settings", {}))
        self.user_channels = copy.deepcopy(meta.get("user_channels", {}))
        self.shader_workflow = copy.deepcopy(meta.get("shader_workflow", DEFAULT_WORKFLOW))
        self.import_reports=copy.deepcopy(meta.get("imports",{}).get("reports",[]))
        self.import_state=copy.deepcopy(meta.get("imports",{}).get("continuation"))
        self.last_replay=None
        if self.import_state:
            from .substance.apply import ReplayStats
            self.last_replay=ReplayStats()
            self.last_replay.dabs,self.last_replay.skipped=self.import_state["dabs"],self.import_state["skipped"]
            self.last_replay.truncated=self.import_state["status"]!="complete"
        self.reimport_checkpoint = meta.get("mesh_extra", {}).get("reimport", {}).get("checkpoint")
        self.journal = Journal.load(meta.get("journal"), data)
        color = meta.get("color")
        self.color = ColorPipeline(color["settings"] if color else None)
        if color and color.get("config_id") != self.color.config_id:
            raise ValueError("Managed color configuration differs from the saved project; use its matching OCIO runtime")
        self.resources.pipeline = self.color
        self.renderer.pipeline = self.color
        extra = {k: data["mesh_" + k] for k in ("parts", "colors", "tri_material") if "mesh_" + k in data}
        mesh = Mesh(meta["mesh_name"], *(data["mesh_" + k] for k in ("positions", "normals", "uvs", "indices")),
                    tangents=data["mesh_tangents"], curvature=data["mesh_curvature"],
                    material_names=meta.get("material_names"), part_names=meta.get("part_names"),
                    **extra).finalize()
        if any(sd.get("tiles") is not None for sd in meta["sets"]):
            # Tile journals fingerprint exact source arrays. Re-normalizing saved
            # float32 normals can change one bit on every reopen; retain the
            # validated authored values rather than silently changing provenance.
            mesh.normals = np.ascontiguousarray(data["mesh_normals"], np.float32)
        mesh.extra.update(meta.get("mesh_extra", {}))
        self.mesh, self.gm = mesh, GPUMesh(self.gpu, mesh)
        missing_ids = {r["id"] for r in self.project_resources if r["status"] in ("missing", "changed")}
        for index, sd in enumerate(meta["sets"]):
            materials = sd.get("materials")
            if materials is None:
                materials = [index] if len(meta["sets"]) > 1 else list(np.unique(mesh.tri_material))
            tris = np.nonzero(np.isin(mesh.tri_material, materials))[0]
            if meta.get("version", 1) < 2:
                tris = np.arange(len(mesh.indices))
            ts = TextureSet(sd["name"], materials, tris, sd["res"], f"ts{index}")
            ts.pid = sd.get("pid", ts.pid)
            ts.bake_settings = BakeSettings.from_dict(sd.get("bake"))
            self.sets.append(ts)
            self.gm.add_subset(ts.key, tris)
            cached = sd.get("cache", {})
            recorded = original["sets"][index]
            valid = cached.get("provenance") == projectio.bake_fingerprint(original, data, recorded)
            source_refs = recorded.get("bake", {}).get("high_poly", [])
            affected = any((p.startswith("resource:") and p[9:] in missing_ids) or p.startswith("<mesh:") or
                           (not p.startswith(("resource:", "<mesh:")) and
                            not os.path.isfile(sd.get("bake", {}).get("high_poly", [])[j]))
                           for j, p in enumerate(source_refs))
            source_hashes = cached.get("source_hashes", [])
            stale = any(p.startswith("resource:") and j < len(source_hashes) and p[9:] != source_hashes[j]
                        for j, p in enumerate(source_refs))
            cage_ref = recorded.get("bake", {}).get("cage_path", "")
            if cage_ref:
                affected |= ((cage_ref.startswith("resource:") and cage_ref[9:] in missing_ids) or
                             not os.path.isfile(ts.bake_settings.cage_path))
                cage_hash = recorded.get("bake", {}).get("cage_hash", "")
                stale |= bool(cage_hash and cage_ref.startswith("resource:") and cage_ref[9:] != cage_hash)
            current_settings = meshmap.settings_provenance(ts.bake_settings)
            stale_settings = bool(cached.get("baked_settings")) and cached["baked_settings"] != current_settings
            if valid and cached.get("maps"):
                textures = {}
                try:
                    for name, info in cached["maps"].items():
                        arr = data[info["array"]]
                        textures[name] = self.gpu.texture((ts.res, ts.res), arr.shape[2], arr,
                            dtype=info["dtype"], filt=name not in ("coverage", "part", "projection_diagnostics"))
                    ts.bakes = BakeSet(textures["position"], textures["world_normal"], textures["curvature"],
                        textures["ao"], textures["coverage"], ts.res, thick=textures.get("thickness"),
                        id=textures.get("id"), part=textures.get("part"), settings=ts.bake_settings,
                        tangent=textures.get("tangent"), normal_hp=textures.get("normal"),
                        height_hp=textures.get("height"), hp_hits=cached.get("hp_hits", 0.0),
                        projection=textures.get("projection_diagnostics"))
                    ts.bakes._source_hashes = list(source_hashes)
                    ts.bakes._settings_snapshot = copy.deepcopy(cached.get("baked_settings", current_settings))
                except Exception:
                    for texture in textures.values():
                        texture.release()
                    raise
                if affected:
                    self.project_diagnostics.append({"code": "bake_cache_source_unavailable", "severity": "warning",
                        "message": f"{ts.name}: retained saved bake; source missing or changed. Relink before rebaking."})
                elif stale or stale_settings:
                    self.project_diagnostics.append({"code": "bake_cache_source_changed", "severity": "warning",
                        "message": f"{ts.name}: source or settings changed since baking; retained saved bake. Re-bake explicitly to update."})
            else:
                if cached.get("maps"):
                    self.project_diagnostics.append({"code": "bake_cache_invalid", "severity": "warning",
                        "message": f"{ts.name}: bake cache provenance changed; rebuilding from available sources."})
                if affected:
                    raise ValueError(f"{ts.name}: high-poly source unavailable and no valid bake cache")
                ts.bakes = self._bake(ts)
            ts.comp = Compositor(self.gpu, ts.res, ts.bakes, mesh, self.resources)
            if progress:
                progress((index + 1) / len(meta["sets"]))
        self.active = 0
        by_id = {}

        def build(d, ts):
            if "instance" in d:
                return by_id[d["instance"]]
            lay = Layer.from_dict({k: v for k, v in d.items() if k != "children"})
            self._loading_layers.append(lay)
            pid = d.get("_id")
            by_id[pid] = lay
            # Register the layer immediately so stage cleanup owns partial uploads.
            lay.children = [build(c, ts) for c in d.get("children", [])]
            if lay.kind == "paint":
                self._alloc_paint(lay, lay.raster_res or ts.res)
                from .userchannels import descriptor
                for channel in list(CHANNEL_DESCRIPTORS) + [descriptor(key) for key in self.user_channels]:
                    key = f"{pid}_{channel.key}"
                    if key in data:
                        lay.tex[channel.key].write(data[key].astype(np.dtype(channel.paint_dtype)).tobytes())
            if f"{pid}_mask" in data:
                self._alloc_mask(lay, 1.0, lay.raster_res or ts.res)
                lay.mask_tex.write(data[f"{pid}_mask"].astype(np.float16).tobytes())
            for effect in lay.mask_effects:
                if effect.kind == "paint":
                    if lay.raster_res is None:
                        lay.raster_res = ts.res
                    effect.tex = self.gpu.texture((lay.raster_res or ts.res,) * 2, 1)
                    effect.tex.write(data[f"effect_{effect.pid}"].astype(np.float16).tobytes())
            return lay

        for sd, ts in zip(meta["sets"], self.sets):
            for d in sd["layers"]:
                ts.layers.append(build(d, ts))
            ts.selected = min(sd.get("selected", 0), len(ts.layers) - 1)
            ts.description = sd.get("description", "")
            if sd.get("tiles") is not None:
                from .materialtiles import MaterialTiles
                source = SimpleNamespace(**{key: data["mesh_" + key] for key in
                                         ("positions", "normals", "uvs", "indices", "tangents", "curvature", "parts", "colors", "tri_material")})
                ts.tiles = MaterialTiles.from_snapshot(self, ts, sd["tiles"], data, source_mesh=source)
            diagnostics = bind_anchor_references(ts.layers)
            for diagnostic in diagnostics:
                self.project_diagnostics.append({"code": "anchor_reference", "severity": "warning",
                                                 "message": str(diagnostic)})
        self.active = min(meta.get("active", 0), len(self.sets) - 1)
        self.normal_strength = meta.get("normal_strength", 1.0)
        for key, default in {"exposure": 1., "env_rot": 0., "emissive_intensity": 1., "alpha_test": False, "use_ao": True}.items():
            setattr(self.renderer, key, meta.get("display", {}).get(key, default))
        if meta.get("brush"):
            self.brush.load_dict(meta["brush"])
        if meta.get("camera"):
            self.camera.load_dict(meta["camera"])
        if meta.get("environment"):
            try:
                Renderer.load_environment(self.renderer, meta["environment"])
            except Exception as e:
                self.project_diagnostics.append({"code": "environment_unavailable", "severity": "warning",
                                                "message": f"Environment unavailable: {e}"})
        self.dirty = True

    def _resource_state(self):
        """Owned undo snapshot; only the environment needs a private GPU copy."""
        texture = self.renderer.env_tex
        saved_texture = self.gpu.clone(texture) if texture is not None else None
        if saved_texture is not None:
            saved_texture.repeat_x, saved_texture.repeat_y = True, False
            saved_texture.build_mipmaps()
            saved_texture.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        layers = list(self.all_layers_all_sets())
        return {"layers": [(lay, dict(lay.maps)) for lay in layers],
                "effects": [(effect, effect.params.get("map")) for lay in layers
                            for effect in lay.effects + lay.mask_effects if effect.kind == "fill"],
                "sets": [(ts, list(ts.bake_settings.high_poly)) for ts in self.sets],
                "mesh_maps": [(ts, copy.deepcopy(ts.bake_settings.external_maps)) for ts in self.sets],
                "cages": [(ts, ts.bake_settings.cage_path, ts.bake_settings.cage_hash) for ts in self.sets],
                "tile_sequences": [(ts, copy.deepcopy(ts.tiles.sequences)) for ts in self.sets if ts.tiles is not None],
                "brush": {"alpha": self.brush.alpha, "stencil": self.brush.stencil,
                          "maps": dict(self.brush.maps),
                          "proj_maps": dict(self.brush.proj_maps)},
                "authored": [(layer,copy.deepcopy(layer.authored)) for layer in layers if layer.authored is not None],
                "import_state": copy.deepcopy(self.import_state),
                "records": copy.deepcopy(self.project_resources),
                "diagnostics": copy.deepcopy(self.project_diagnostics),
                "env_path": self.renderer.env_path, "env_tex": saved_texture}

    def _restore_resource_state(self, state):
        for layer, maps in state["layers"]:
            layer.maps = dict(maps)
        for effect, path in state["effects"]:
            if path is None:
                effect.params.pop("map", None)
            else:
                effect.params["map"] = path
        for ts, paths in state["sets"]:
            ts.bake_settings.high_poly = list(paths)
        for ts, path, digest in state.get("cages", []):
            ts.bake_settings.cage_path, ts.bake_settings.cage_hash = path, digest
        for ts, maps in state.get("mesh_maps", []):
            ts.bake_settings.external_maps = copy.deepcopy(maps)
        for ts, sequences in state.get("tile_sequences", []):
            ts.tiles.sequences = copy.deepcopy(sequences)
        self.brush.alpha, self.brush.stencil = state["brush"]["alpha"], state["brush"]["stencil"]
        self.brush.maps = dict(state["brush"].get("maps", {}))
        self.brush.proj_maps = dict(state["brush"]["proj_maps"])
        for layer,authored in state.get("authored",[]):layer.authored=copy.deepcopy(authored)
        self.import_state=copy.deepcopy(state.get("import_state",self.import_state))
        self.project_resources = copy.deepcopy(state["records"])
        self.project_diagnostics = copy.deepcopy(state["diagnostics"])
        if self.renderer.env_tex is not None:
            self.renderer.env_tex.release()
        self.renderer.env_path, self.renderer.env_tex = state["env_path"], state["env_tex"]
        self.resources.release()
        self.high_meshes, self._high_hashes = {}, {}
        self._invalidate_properties([self])

    def relink_resources(self, mapping):
        """Validate replacements first, then update known project paths and mark modified.

        Keys can be resource IDs, original source paths or current resolved paths.
        Existing saved bakes are retained; rebaking remains an explicit operation.
        """
        self.commit_edit()
        replacements = {}
        updates = []
        matched_records = []
        unmatched = set(mapping)
        for record in self.project_resources:
            matches = [k for k in (record["id"], record.get("source"), record.get("resolved")) if k in mapping]
            unmatched.difference_update(matches)
            replacement = mapping[matches[0]] if matches else None
            if replacement is None:
                continue
            target = os.path.abspath(os.path.expanduser(replacement))
            if not os.path.isfile(target):
                raise ValueError(f"Replacement resource does not exist: {target}")
            with open(target, "rb") as stream:
                digest = hashlib.sha256(stream.read()).hexdigest()
            if any(role not in ("high_poly", "cage", "font") for role in record.get("roles", [])):
                from .imageio import read_image
                read_image(target)  # decode before changing any references
            if "high_poly" in record.get("roles", []):
                load_high_poly(target, self.mesh)
            if "font" in record.get("roles",[]):
                from PIL import ImageFont
                ImageFont.truetype(target,16)
            if "cage" in record.get("roles", []):
                from .mesh import load_mesh
                from .bakecontrol import validate_cage
                validate_cage(self.mesh, load_mesh(target, xform=self.mesh.extra.get("xform") or ([0., 0., 0.], 1.),
                                                   light=True, require_uvs=False))
            if "mesh_map" in record.get("roles", []):
                for ts in self.sets:
                    for key, item in ts.bake_settings.external_maps.items():
                        if item["path"] == record.get("resolved"):
                            meshmap.read_map(target, key, ts.res, item["interpretation"])
            proposed = dict(record, id=digest, resolved=target, source=target, sha256=digest,
                            status="available", embedded=False, member=None, size=os.path.getsize(target))
            matched_records.append(record)
            if proposed == record:
                continue
            replacements[record["resolved"]] = target
            updates.append((record, target, proposed))
        if unmatched:
            raise ValueError("Unknown project resource: " + ", ".join(map(str, unmatched)))
        if not updates:
            return [dict(record) for record in matched_records]
        environment = None
        if self.renderer.env_path in replacements:
            environment = SimpleNamespace(gpu=self.gpu, env_path=None, env_tex=None, pipeline=self.color)
            Renderer.load_environment(environment, replacements[self.renderer.env_path])
        try:
            before = self._resource_state()
        except Exception:
            if environment is not None and environment.env_tex is not None:
                environment.env_tex.release()
            raise
        self._push_undo(("resources", before, self._edit_serial, "Relink resources"))
        def rewrite_layer(layer):
            layer.maps = {k: replacements.get(v, v) for k, v in layer.maps.items()}
            for effect in layer.effects + layer.mask_effects:
                if effect.kind == "fill" and effect.params.get("map") in replacements:
                    effect.params["map"] = replacements[effect.params["map"]]
        for layer in self.all_layers_all_sets():
            rewrite_layer(layer)
            if layer.authored:
                for key in ("font","alpha"):
                    if layer.authored.get(key) in replacements:layer.authored[key]=replacements[layer.authored[key]]
        for ts in self.sets:
            ts.bake_settings.high_poly = [replacements.get(p, p) for p in ts.bake_settings.high_poly]
            if ts.bake_settings.cage_path in replacements:
                ts.bake_settings.cage_path = replacements[ts.bake_settings.cage_path]
                with open(ts.bake_settings.cage_path, "rb") as source:
                    ts.bake_settings.cage_hash = hashlib.sha256(source.read()).hexdigest()
            if ts.tiles is not None:
                for channels in ts.tiles.sequences.values():
                    for paths in channels.values():
                        for udim, path in paths.items():
                            paths[udim] = replacements.get(path, path)
            for record in ts.bake_settings.external_maps.values():
                record["path"] = replacements.get(record["path"], record["path"])
        for owner,key,_ in projectio.resource_slots({"imports":{"continuation":self.import_state}}):
            owner[key]=replacements.get(owner[key],owner[key])
        for attr in ("alpha", "stencil"):
            setattr(self.brush, attr, replacements.get(getattr(self.brush, attr), getattr(self.brush, attr)))
        self.brush.maps = {k: replacements.get(v, v) for k, v in self.brush.maps.items()}
        self.brush.proj_maps = {k: replacements.get(v, v) for k, v in self.brush.proj_maps.items()}
        if environment is not None:
            if self.renderer.env_tex is not None:
                self.renderer.env_tex.release()
            self.renderer.env_path, self.renderer.env_tex = environment.env_path, environment.env_tex
        ids = {r["id"] for r, _, _ in updates}
        for record, target, proposed in updates:
            record.update(proposed)
        self.resources.release()
        self.high_meshes = {}
        self._high_hashes = {}
        self.project_diagnostics = [d for d in self.project_diagnostics if d.get("resource_id") not in ids]
        self.dirty = True
        self._invalidate_properties([self])
        return [dict(record) for record in matched_records]

    def all_layers_all_sets(self):
        seen = set()
        for ts in self.sets:
            for layer in self._walk(ts.layers):
                if id(layer) not in seen:
                    seen.add(id(layer))
                    yield layer


def _point_in_poly(x, y, poly):
    inside = np.zeros(x.shape, bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1)
        inside ^= cond
    return inside
