"""Engine: project state + all GPU subsystems. Has no UI dependency, so it runs headless.

A project is one mesh split into texture sets (one per material). Each texture set has its own
resolution, mesh-map bakes, layer stack and compositor. `engine.layers`, `engine.comp`,
`engine.bakes`, `engine.res` and `engine.selected` refer to the active texture set.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile

import moderngl
import numpy as np

from .baker import Baker, BakeSet, BakeSettings, PAD
from .compositor import Compositor
from .gpu import GPU, GPUMesh
from .layers import (Brush, Layer, MaskGen, Effect, group as make_group, CH_KEYS, CH_COMPONENTS,
                     N_CH, MASK_EFFECTS, CONTENT_EFFECTS)
from .mesh import BUILTIN_MESHES, Mesh, load_high_poly
from .painter import Painter, Stroke, Surface, View, TOOL_CLONE
from .presets import SMART_MATERIALS
from .renderer import Camera, Renderer
from .resources import Resources

UNDO_LIMIT = 24
SAVE_VERSION = 2


class TextureSet:
    def __init__(self, name: str, materials: list, tri_ids: np.ndarray, res: int, key: str):
        self.name = name
        self.materials = list(materials)
        self.tri_ids = np.asarray(tri_ids, np.int64)
        self.res = int(res)
        self.key = key
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

    def release(self):
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
        self.resources = Resources(self.gpu)
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
        self._stroke: Stroke | None = None
        self._stroke_layer = None
        self.view_size = (1, 1)
        self._vp = np.eye(4)
        self._last_pick = None
        self.clone_source = None          # screen px of the clone source
        self.clone_offset = None
        self.quick_mask_enabled = False
        self.high_meshes = {}             # path -> high-poly Mesh (in this project's space)
        self.last_replay = None           # substance.apply.ReplayStats of the last Painter import
        self._edit_serial = 0             # bumped by every undoable edit (paint, masks, layer tree)
        self._saved_serial = 0
        self._saved_sig = None            # project fingerprint at the last new / open / save

    # ------------------------------------------------------------------ active texture set
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
        if 0 <= idx < len(self.sets):
            self.active = idx

    # ------------------------------------------------------------------ project
    def new_project(self, mesh: Mesh | str, res: int = 2048, ao_samples: int = 96, progress=None,
                    with_default_layer=True, bake_settings: BakeSettings | None = None,
                    split_materials=True, resolutions: dict | None = None):
        if isinstance(mesh, str):
            mesh = BUILTIN_MESHES[mesh]()
        if mesh is not self.mesh:
            self.high_meshes = {}
        self._release_project()
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
        self.dirty = True
        self.mark_saved()

    def _release_project(self):
        self._cancel_stroke()
        doomed = {}
        for ts in self.sets:
            doomed.update({id(l): l for l in self._walk(ts.layers)})
        for e in self.undo_stack + self.redo_stack:
            if e[0] == "stack":
                doomed.update({id(l): l for l in self._tree_layers(e[2])})
            self._release_entry(e, force=True)
        for lay in doomed.values():
            self._release_layer(lay)
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
        return self.baker.bake(self.gm, ts.res, progress=progress, subset=ts.key, settings=ts.bake_settings,
                               high=self._high_for(ts))

    def _high_for(self, ts: TextureSet):
        paths = list(ts.bake_settings.high_poly or [])
        meshes = []
        for p in paths:
            if p not in self.high_meshes:
                if p.startswith("<mesh:"):
                    continue                      # in-memory mesh from an earlier session
                try:
                    self.high_meshes[p] = load_high_poly(p, self.mesh)
                except Exception as e:
                    print(f"[strata] high poly {p}: {e}")
                    continue
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
        for ts in targets:
            ts.bake_settings.high_poly = list(paths)
            if front is not None:
                ts.bake_settings.hp_front = float(front)
            if rear is not None:
                ts.bake_settings.hp_rear = float(rear)
        self.rebake(all_sets=all_sets, ts_index=ts_index, progress=progress)

    def set_resolution(self, res: int, ts_index: int | None = None, rebake=True, progress=None):
        """Change a texture set's resolution without losing paint (layers are resampled)."""
        ts = self.sets[self.active if ts_index is None else ts_index]
        res = int(res)
        if res == ts.res:
            return
        self._cancel_stroke()
        self._clear_history()
        g = self.gpu
        for lay in self._walk(ts.layers):
            self.painter.forget(lay)
            if lay.tex:
                for k, t in list(lay.tex.items()):
                    lay.tex[k] = g.resample(t, (res, res)); t.release()
            if lay.mask_tex is not None:
                old = lay.mask_tex
                lay.mask_tex = g.resample(old, (res, res)); old.release()
        if ts.quick is not None:
            old = ts.quick
            ts.quick = g.resample(old, (res, res)); old.release()
        ts.res = res
        old_bakes, old_comp = ts.bakes, ts.comp
        ts.bakes = self._bake(ts, progress)
        ts.comp = Compositor(self.gpu, res, ts.bakes, self.mesh, self.resources)
        old_comp.release(); old_bakes.release()
        self.gpu.release_scratch()
        ts.dirty = True

    def rebake(self, settings: BakeSettings | None = None, ts_index: int | None = None, progress=None,
               all_sets=False):
        """Re-run the mesh-map bakers (e.g. after changing BakeSettings)."""
        targets = self.sets if all_sets else [self.sets[self.active if ts_index is None else ts_index]]
        for ts in targets:
            if settings is not None:
                ts.bake_settings = BakeSettings.from_dict(settings.to_dict())
            new = self._bake(ts, progress)
            ts.comp.bakes = new
            ts.bakes.release()
            ts.bakes = new
            ts.dirty = True

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
            if any(l is layer for l in top.walk()):
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
        ts.selected = r
        ts.focus = layer if ts.layers[r] is not layer else None
        self.dirty = True

    # ------------------------------------------------------------------ GPU allocation
    def _alloc_paint(self, lay: Layer, res=None):
        res = res or self.res
        r = (res, res)
        g = self.gpu
        lay.tex = {k: g.texture(r, CH_COMPONENTS[k]) for k in CH_KEYS}
        for t in lay.tex.values():
            g.fill(t, (0, 0, 0, 0))

    def _alloc_mask(self, lay: Layer, value: float, res=None):
        res = res or self.res
        lay.mask_tex = self.gpu.texture((res, res), 1)
        self.gpu.fill(lay.mask_tex, (value, value, value, 1))

    def _release_layer(self, lay: Layer):
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
        return ("stack", ts, self._tree(ts.layers), ts.selected, ts.focus)

    def _push_undo(self, entry, clear_redo=True):
        self._edit_serial += 1
        self.undo_stack.append(entry)
        if clear_redo:
            dropped, self.redo_stack = self.redo_stack, []
            for e in dropped:
                self._release_entry(e)
        while len(self.undo_stack) > UNDO_LIMIT:
            self._release_entry(self.undo_stack.pop(0))

    @staticmethod
    def _tree_layers(tree):
        for l, children, _, _ in tree:
            yield l
            yield from Engine._tree_layers(children)

    def _live_layers(self):
        live = set()
        for ts in self.sets:
            live |= {id(l) for l in self._walk(ts.layers)}
        for e in self.undo_stack + self.redo_stack:
            if e[0] == "stack":
                live |= {id(l) for l in self._tree_layers(e[2])}
            elif e[0] == "tex":
                live.add(id(e[1]))
        return live

    def _release_entry(self, e, force=False):
        if e[0] in ("tex", "quick"):
            for t in e[2].values():
                t.release()
        elif e[0] == "stack" and not force:
            live = self._live_layers()
            for lay in self._tree_layers(e[2]):
                if id(lay) not in live:
                    self._release_layer(lay)

    def _clear_history(self):
        for e in self.undo_stack + self.redo_stack:
            self._release_entry(e)
        self.undo_stack, self.redo_stack = [], []

    def _apply(self, e):
        """Restore entry e, returning the inverse entry."""
        if e[0] == "stack":
            ts = e[1]
            inv = self._snapshot_stack(ts)
            ts.layers = self._restore_tree(e[2])
            ts.selected, ts.focus = e[3], e[4]
            ts.dirty = True
            return inv
        if e[0] == "quick":
            ts, saved = e[1], e[2]
            cur = {"quick": self.gpu.clone(ts.quick)}
            self.gpu.blit(saved["quick"], ts.quick)
            saved["quick"].release()
            ts.dirty = True
            return ("quick", ts, cur)
        lay, saved = e[1], e[2]
        cur = {}
        for k, t in saved.items():
            dst = lay.mask_tex if k == "mask" else lay.tex[k]
            cur[k] = self.gpu.clone(dst)
            self.gpu.blit(t, dst)
            t.release()
        for ts in self.sets:
            ts.dirty = True
        return ("tex", lay, cur)

    def undo(self):
        self._finish_stroke()
        if self.undo_stack:
            self._edit_serial += 1
            self.redo_stack.append(self._apply(self.undo_stack.pop()))

    def redo(self):
        self._finish_stroke()
        if self.redo_stack:
            self._push_undo(self._apply(self.redo_stack.pop()), clear_redo=False)

    # ------------------------------------------------------------------ layer operations
    def add_layer(self, kind="paint", name=None, layer: Layer | None = None, index=None, record=True,
                  parent: Layer | None = None):
        """Insert a new (or given) layer. index counts within `parent`'s children (or the top level)."""
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
                if k in CH_KEYS:
                    lay.enabled[CH_KEYS.index(k)] = True
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

    def _clone_layer(self, src: Layer) -> Layer:
        lay = Layer.from_dict(src.to_dict())
        for s, d in zip(src.walk(), lay.walk()):
            if s.tex:
                d.tex = {k: self.gpu.clone(t) for k, t in s.tex.items()}
            if s.mask_tex is not None:
                d.mask_tex = self.gpu.clone(s.mask_tex)
        return lay

    def duplicate_layer(self, idx=None, layer: Layer | None = None):
        if layer is None:
            idx = self.selected if idx is None else idx
            if not (0 <= idx < len(self.layers)):
                return
            layer = self.layers[idx]
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
        self._push_undo(self._snapshot_stack(ts))
        ts.layers.insert(len(ts.layers) if index is None else index, layer)
        ts.dirty = True

    def add_mask(self, value=1.0, idx=None, layer: Layer | None = None):
        lay = layer or (self.layer if idx is None else self.layers[idx])
        if lay.mask_tex is None:
            self._alloc_mask(lay, value)
        else:
            self.gpu.fill(lay.mask_tex, (value, value, value, 1))
        lay.has_mask = True
        self.dirty = True

    def remove_mask(self, idx=None, layer: Layer | None = None):
        lay = layer or (self.layer if idx is None else self.layers[idx])
        lay.has_mask = False
        self.dirty = True

    def fill_mask(self, value, idx=None, layer: Layer | None = None):
        lay = layer or (self.layer if idx is None else self.layers[idx])
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
        self._push_undo(("tex", lay, {k: self.gpu.clone(t) for k, t in lay.tex.items()}))
        for t in lay.tex.values():
            self.gpu.fill(t, (0, 0, 0, 0))
        self.dirty = True

    def set_geometry_mask(self, parts, layer: Layer | None = None):
        """Restrict a layer to mesh parts (list of part ids), or None for the whole mesh."""
        lay = layer or self.layer
        self._push_undo(self._snapshot_stack())
        lay.part_mask = None if parts is None else sorted(int(p) for p in parts)
        self.dirty = True

    # ------------------------------------------------------------------ effects
    def add_effect(self, effect: str, layer: Layer | None = None, mask: bool | None = None, index=None,
                   blend=0, opacity=1.0, **params) -> Effect:
        """Add an effect to a layer's mask stack (mask=True) or content stack (mask=False).
        effect: one of layers.MASK_EFFECTS / CONTENT_EFFECTS. Generator params can be given as
        gen=MaskGen(...) or flat (kind=, level=, softness=, ...)."""
        kind = effect
        lay = layer or self.layer
        if mask is None:
            mask = kind in MASK_EFFECTS and kind not in ("hsl", "brightness_contrast")
        if kind == "generator" and "gen" not in params:
            gen_fields = {k: params.pop(k) for k in list(params) if k in MaskGen.__dataclass_fields__}
            params["gen"] = MaskGen(**gen_fields) if gen_fields else MaskGen(kind=1)
        allowed = MASK_EFFECTS if mask else CONTENT_EFFECTS
        if kind not in allowed:
            raise ValueError(f"'{kind}' is not a {'mask' if mask else 'content'} effect")
        self._push_undo(self._snapshot_stack())
        e = Effect(kind=kind, blend=blend, opacity=opacity, params=params)
        lst = lay.mask_effects if mask else lay.effects
        lst.insert(len(lst) if index is None else index, e)
        self.dirty = True
        return e

    def remove_effect(self, effect: Effect, layer: Layer | None = None):
        lay = layer or self.layer
        self._push_undo(self._snapshot_stack())
        for lst in (lay.effects, lay.mask_effects):
            if effect in lst:
                lst.remove(effect)
        self.dirty = True

    def move_effect(self, effect: Effect, delta: int, layer: Layer | None = None):
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
    def update_view(self, w, h):
        self.view_size = (max(int(w), 1), max(int(h), 1))
        cam = self.camera
        self._vp = cam.proj(self.view_size[0] / self.view_size[1]) @ cam.view()
        if self.gm is not None:
            self.renderer.render_pick(self.gm, self._vp, *self.view_size)

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
        for ts in self.sets:
            if ts.comp is None:
                continue
            root = self._root_index(self.layer, ts) if (ts is self.ts and self.layer is not None) else None
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

    def render(self, rect, cursor=None):
        """Draw the viewport into the bound framebuffer. rect=(x,y,w,h) in framebuffer pixels."""
        target = self.ctx.fbo
        self.update()
        target.use()
        sets = [(ts.key, ts.comp, ts.bakes) for ts in self.sets if ts.comp is not None]
        self.renderer.render_sets(self.gm, self.camera, self._vp, sets, rect)
        if cursor is not None:
            hit, nrm = cursor
            self.renderer.draw_cursor(hit, nrm, self.brush_radius(hit), self._vp, rect)

    def render_2d(self, rect, channel="color", zoom=1.0, pan=(0.0, 0.0), ts_index=None, wire=True):
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
        if tex is None:
            m = ts.bakes.maps().get(channel)
            tex, comp = (m, -1) if m is not None else (c.color, -1)
        return self.renderer.render_2d(self.gm, ts.key, tex, rect, zoom, pan, comp, wire)

    # ------------------------------------------------------------------ painting
    def brush_radius(self, hit, tri=-1):
        b = self.brush
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
            return True
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

    def begin_stroke(self, hit, pressure=1.0, info=None):
        lay = self.layer
        if not self.can_paint():
            return False
        self._finish_stroke()
        b = self.brush
        target = {0: "layer", 1: "mask", 2: "quick"}.get(int(b.target), "layer")
        if target == "mask" and (lay.mask_tex is None or not lay.has_mask):
            self.add_mask(0.0 if b.mask_value > 0.5 else 1.0, layer=lay)
        if target == "layer":
            textures = lay.tex
        elif target == "mask":
            textures = lay.mask_tex
        else:
            textures = self.ensure_quick_mask()
        view = self._view()
        surf = self._surface(hit, pressure, info)
        offset = None
        if int(b.tool) == TOOL_CLONE:
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
                              seed=len(self.undo_stack) * 7919 + 17)
        self._stroke_layer = lay if target != "quick" else None
        self._stroke.start(surf)
        self.ts.paint_dirty = target != "quick"
        return True

    def stroke_to(self, hit, pressure=1.0, info=None):
        if self._stroke is None:
            return
        self._stroke.view = self._view()
        self._stroke.feed(self._surface(hit, pressure, info))
        self.ts.paint_dirty = self._stroke.target != "quick"

    def end_stroke(self):
        self._finish_stroke()

    def _finish_stroke(self, apply_only=False):
        st = self._stroke
        if st is None:
            return
        st.apply()
        if apply_only:
            return
        snap = st.release(keep_snapshot=True)
        if st.target == "quick":
            self._push_undo(("quick", self.ts, {"quick": snap["mask"]}))
        elif st.target == "mask":
            self._push_undo(("tex", self._stroke_layer, {"mask": snap["mask"]}))
        else:
            self._push_undo(("tex", self._stroke_layer, snap))
        self._stroke = None
        self._stroke_layer = None

    def _cancel_stroke(self):
        if self._stroke is not None:
            self._stroke.release()
            self._stroke = None
            self._stroke_layer = None

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
        view = self._view()
        self._finish_stroke()
        if target == 2:
            q = self.ensure_quick_mask()
            self._push_undo(("quick", ts, {"quick": self.gpu.clone(q)}))
            self.painter.fill_tris(self.gm, tris, q, self.brush, view, erase,
                                   self.brush.mask_value if mask_value is None else mask_value)
        elif target == 1:
            value = self.brush.mask_value if mask_value is None else mask_value
            if lay.mask_tex is None or not lay.has_mask:
                self.add_mask(0.0 if (value > 0.5 and not erase) else 1.0, layer=lay)
            self._push_undo(("tex", lay, {"mask": self.gpu.clone(lay.mask_tex)}))
            self.painter.fill_tris(self.gm, tris, lay.mask_tex, self.brush, view, erase,
                                   self.brush.mask_value if mask_value is None else mask_value)
        else:
            if lay is None or lay.kind != "paint":
                return False
            self._push_undo(("tex", lay, {k: self.gpu.clone(t) for k, t in lay.tex.items()}))
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
        vals = ts.comp.sample(info["uv"])
        if apply:
            b = self.brush
            b.color, b.rough, b.metal = vals["color"], vals["rough"], vals["metal"]
            b.height, b.opac, b.emissive, b.normal = vals["height"], vals["opac"], vals["emissive"], vals["normal"]
        return vals

    # ------------------------------------------------------------------ Substance 3D Painter content
    def add_imported(self, result, index=None, parent=None, record=True):
        """Insert a converted Painter smart material (substance.convert.ImportResult) into the
        active texture set as one undo step; paint strokes are replayed. Returns the new layers."""
        from .substance import apply
        return apply.add_imported(self, result, index=index, parent=parent, record=record)

    def apply_mask_state(self, mask, idx=None, layer=None, replace=False):
        """Apply a converted Painter smart mask (substance.convert.MaskBuild) to a layer (default:
        the selected one) as one undo step. Returns False when there is nothing to apply."""
        from .substance import apply
        lay = layer if layer is not None else (self.layers[idx] if idx is not None and 0 <= idx < len(self.layers)
                                               else self.layer)
        return apply.apply_mask(self, mask, lay, replace=replace)

    def import_painter_project(self, proj, ao_samples=96, progress=None):
        """Replace the project with an imported .spp (substance.importer.ProjectImport): mesh, every
        texture set and its layer stack, with recorded paint strokes replayed. Returns dabs painted."""
        from .substance import apply
        return apply.import_project(self, proj, ao_samples=ao_samples, progress=progress)

    # ------------------------------------------------------------------ save / load
    # ------------------------------------------------------------------ unsaved changes
    def _signature(self) -> str:
        """Fingerprint of everything a save writes that the user edits: texture sets, their
        resolution and bake settings, and every layer's settings (UI-only state such as which
        folders are expanded is ignored). Pixel edits are tracked by _edit_serial instead."""
        def strip(d):
            d.pop("expanded", None)
            for c in d.get("children", []):
                strip(c)
            return d
        state = {"mesh": id(self.mesh), "normal_strength": self.normal_strength,
                 "sets": [{"name": ts.name, "res": ts.res, "bake": ts.bake_settings.to_dict(),
                           "description": getattr(ts, "description", ""),
                           "layers": [strip(l.to_dict()) for l in ts.layers]} for ts in self.sets]}
        return hashlib.md5(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()

    def mark_saved(self):
        """Record the current state as saved (called by new_project, load and save)."""
        self._saved_serial = self._edit_serial
        self._saved_sig = self._signature() if self.mesh is not None else None

    @property
    def modified(self) -> bool:
        """True when the project has changes since it was created, opened or last saved.
        Computed on demand (serialises the layer settings): call it when needed, not every frame."""
        if self.mesh is None or not self.sets:
            return False
        if self._stroke is not None or self._edit_serial != self._saved_serial:
            return True
        return self._signature() != self._saved_sig

    def save(self, path):
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
                for k, t in lay.tex.items():
                    arrays[f"{prefix}_{k}"] = self.gpu.read(t).astype(np.float16)
            if lay.mask_tex is not None:
                arrays[f"{prefix}_mask"] = self.gpu.read(lay.mask_tex).astype(np.float16)
            d["children"] = [ser(c, f"{prefix}c{i}") for i, c in enumerate(lay.children)]
            return d

        for si, ts in enumerate(self.sets):
            sets.append({"name": ts.name, "materials": ts.materials, "res": ts.res,
                         "selected": ts.selected, "bake": ts.bake_settings.to_dict(),
                         "description": ts.description,
                         "layers": [ser(l, f"S{si}L{i}") for i, l in enumerate(ts.layers)]})
        meta = {"version": SAVE_VERSION, "mesh_name": m.name, "material_names": m.material_names,
                "part_names": m.part_names, "res": self.res, "selected": self.selected,
                "active": self.active, "normal_strength": self.normal_strength, "sets": sets,
                "brush": self.brush.to_dict(), "camera": self.camera.to_dict(),
                "environment": self.renderer.env_path}
        buf = io.BytesIO()
        np.savez_compressed(buf, **arrays)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
            z.writestr("project.json", json.dumps(meta, indent=1))
            z.writestr("data.npz", buf.getvalue())
        self.mark_saved()

    def load(self, path, progress=None):
        with zipfile.ZipFile(path) as z:
            meta = json.loads(z.read("project.json"))
            data = np.load(io.BytesIO(z.read("data.npz")))
        extra = {k: data["mesh_" + k] for k in ("parts", "colors", "tri_material") if "mesh_" + k in data}
        mesh = Mesh(meta["mesh_name"], *(data["mesh_" + k] for k in ("positions", "normals", "uvs", "indices")),
                    tangents=data["mesh_tangents"], curvature=data["mesh_curvature"],
                    material_names=meta.get("material_names"), part_names=meta.get("part_names"),
                    **extra).finalize()
        if meta.get("version", 1) < 2:          # one texture set, flat layer list
            meta["sets"] = [{"name": "Default", "res": meta["res"], "selected": meta.get("selected", 0),
                             "layers": [dict(d, _id=f"L{i}") for i, d in enumerate(meta["layers"])]}]
            split = False
        else:
            split = len(meta["sets"]) > 1
        bake = BakeSettings.from_dict(meta["sets"][0].get("bake")) if meta["sets"][0].get("bake") else None
        resolutions = {s["name"]: s["res"] for s in meta["sets"]}
        self.new_project(mesh, meta["sets"][0]["res"], progress=progress, with_default_layer=False,
                         bake_settings=bake, split_materials=split, resolutions=resolutions,
                         ao_samples=(bake.ao_samples if bake else 96))
        by_id = {}

        def build(d, ts):
            if "instance" in d:
                return by_id[d["instance"]]
            lay = Layer.from_dict({k: v for k, v in d.items() if k != "children"})
            lay.children = [build(c, ts) for c in d.get("children", [])]
            pid = d.get("_id")
            by_id[pid] = lay
            if lay.kind == "paint":
                self._alloc_paint(lay, ts.res)
                for k in CH_KEYS:
                    key = f"{pid}_{k}"
                    if key in data:
                        lay.tex[k].write(data[key].astype(np.float16).tobytes())
            if f"{pid}_mask" in data:
                self._alloc_mask(lay, 1.0, ts.res)
                lay.mask_tex.write(data[f"{pid}_mask"].astype(np.float16).tobytes())
            return lay

        for sd in meta["sets"]:
            ts = next((t for t in self.sets if t.name == sd["name"]), self.sets[0])
            ts.layers = [build(d, ts) for d in sd["layers"]]
            ts.selected = min(sd.get("selected", 0), len(ts.layers) - 1)
            ts.description = sd.get("description", "")
        self.active = min(meta.get("active", 0), len(self.sets) - 1)
        self.normal_strength = meta.get("normal_strength", 1.0)
        if meta.get("brush"):
            self.brush.load_dict(meta["brush"])
        if meta.get("camera"):
            self.camera.load_dict(meta["camera"])
        if meta.get("environment"):
            try:
                self.renderer.load_environment(meta["environment"])
            except Exception as e:
                print(f"[strata] environment: {e}")
        self.dirty = True
        self.mark_saved()


def _point_in_poly(x, y, poly):
    inside = np.zeros(x.shape, bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1)
        inside ^= cond
    return inside
