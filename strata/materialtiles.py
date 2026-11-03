"""Material-owned tiled raster state and detached evaluation on the owning GL thread.

This module shares the material's editable definitions; only authored pixels and
derived evaluation have tile context. Interactive dispatch/UI are separate.
"""
import copy
import json
import os
from contextlib import contextmanager
from types import SimpleNamespace
import numpy as np

from .tiles import TileAddress, partition
from .tilestore import TileStore
from .paintstore import PaintTextures
from .layers import Layer, Brush
from .channels import CHANNEL_DESCRIPTORS, BY_KEY
from .userchannels import descriptor, paint_channels
from .gpu import GPUMesh
from .painter import Painter, Stroke, Surface, View, Dab, TOOL_CLONE, TOOL_SMUDGE, TOOL_PROJECTION
from .viewinput import UVMapping, uv_triangle
from .journal import freeze_brush, mesh_revision, validate_operation
from . import shaders as S


def raster_name(pid, channel):
    return pid + ":" + channel


def snapshot_bytes(snapshot):
    meta, arrays = snapshot
    return len(json.dumps(meta, separators=(",", ":")).encode("utf-8")) + sum(array.nbytes for array in arrays.values())


def operation_from_stroke(material, stroke, owner):
    e = material.engine
    return {"version": 1, "brush": stroke.brush.to_dict(), "seed": stroke.seed,
            "coordinate_space": "uv" if stroke.view.uv_mapping is not None else "surface", "mesh_revision": mesh_revision(e.mesh),
            "color_identity": e.color.cache_id, "set_pid": material.ts.pid, "owner_pid": owner.pid,
            "target": stroke.target, "views": stroke.recorded_views, "samples": stroke.recorded_samples,
            "dabs": stroke.recorded_dabs, "source_revision": None, "clone_offset": [0., 0.]}


def dab_touches_tile(record, address, brush):
    values = record["values"]
    radius = values["radius_uv"]
    if brush.alpha:
        radius *= sum(abs(value) for value in values["rot"])
    center = np.asarray(values["hit_uv"])
    return np.all(center + radius >= address.to_list()) and np.all(center - radius <= np.array(address.to_list()) + 1)


def touches_tile(material, operation, record, address, brush):
    if operation["coordinate_space"] == "uv":
        return dab_touches_tile(record, address, brush)
    # The brush shader rejects points farther than three world radii. Use a
    # conservative world AABB, including transformed symmetry copies and seams.
    values = record["values"]
    center = (np.linalg.inv(np.asarray(values["sym_inv"])) @ np.append(values["hit"], 1.))[:3]
    lo, hi = material.world_bounds[address]
    radius = values["radius"] * 3.
    return np.all(center + radius >= lo) and np.all(center - radius <= hi)


@contextmanager
def unscissored(engine):
    scissor = engine.ctx.scissor
    engine.ctx.scissor = None
    try:
        yield
    finally:
        engine.ctx.scissor = scissor


@contextmanager
def tile_views(engine, operation, address, coverage=None):
    """Rebuild recorded camera occlusion from the whole mesh; restore current picks."""
    from .evaluation import _view
    previous, current = None, None
    def get(index):
        nonlocal previous, current
        if previous != index:
            current = _view(engine, operation["views"][index])
            current.tile_offset = tuple(address.to_list())
            if current.uv_mapping is not None:
                current.pick_pos = coverage or engine.gpu.white
            previous = index
        return current
    try:
        yield get
    finally:
        if operation["coordinate_space"] == "surface":
            engine.renderer.render_pick(engine.gm, engine._vp, *engine.view_size)


class _Recorder:
    def __init__(self, painter):
        self.gpu = painter.gpu
        self.forget_textures = painter.forget_textures

    def __getattr__(self, name):
        if name.startswith(("dab_", "apply_")):
            return lambda *args, **kwargs: None
        raise AttributeError(name)


class _LeasePaint(PaintTextures):
    def __init__(self, gpu, res, lease, pid):
        super().__init__(gpu, res, {name[len(pid)+1:]: texture for name, texture in lease.items()
                                  if name.startswith(pid + ":") and name != pid + ":mask"})
        self.lease, self.pid = lease, pid

    def __missing__(self, key):
        channel = descriptor(key)
        texture = self.lease.texture(raster_name(self.pid, key), (self.resolution,) * 2,
                                     channel.paint_components, channel.paint_dtype)
        self[key] = texture
        return texture


class _AllocationProxy:
    def __init__(self, gpu):
        self.original, self.created = gpu, []

    def __getattr__(self, name):
        return getattr(self.original, name)

    def texture(self, *args, **kwargs):
        texture = self.original.texture(*args, **kwargs)
        self.created.append(texture)
        return texture

    def rollback(self):
        self.original.release_scratch()
        for texture in self.created:
            texture.release()


class MaterialTiles:
    def __init__(self, engine, ts, resident_bytes=None):
        self.engine, self.ts = engine, ts
        self.layout = partition(engine.mesh, ts.materials)
        if not self.layout.pages:
            raise ValueError("This material has no nondegenerate supported tile coverage")
        self.res = ts.res
        self.world_bounds = {}
        for address, page in self.layout.pages.items():
            points = engine.mesh.positions[engine.mesh.indices[page.source_triangles]].reshape(-1, 3)
            self.world_bounds[address] = (points.min(axis=0), points.max(axis=0))
        self.store = TileStore(engine.gpu, engine.gpu.memory.limit_bytes if resident_bytes is None else resident_bytes,
                               forget=engine.painter.forget_textures)
        self.base = TileStore(engine.gpu, self.store.limit, forget=engine.painter.forget_textures)
        self.operations, self.mask_defaults = [], {}
        self.sequences = {}
        self.preview_cache = None
        self.evaluation_cache = None
        self.raster_revision = 0

    @property
    def addresses(self):
        return tuple(self.layout.pages)

    def import_legacy_base(self):
        """Only tile (0,0) inherits existing legacy paint; other tiles start unpainted."""
        if TileAddress() not in self.layout.pages:
            return
        base_sources = {}
        with self.store.lease(self.ts.pid) as lease:
            for layer in self.engine._walk(self.ts.layers):
                sources = [(raster_name(layer.pid, key), texture) for key, texture in (layer.tex or {}).items()]
                if layer.mask_tex is not None:
                    sources.append((raster_name(layer.pid, "mask"), layer.mask_tex))
                sources.extend((raster_name(effect.pid, "mask"), effect.tex)
                               for effect in layer.mask_effects if effect.tex is not None)
                for name, source in sources:
                    base_sources[name] = source
                    texture = lease.texture(name, (self.res, self.res), source.components, source.dtype)
                    if source.size == (self.res, self.res):
                        self.engine.gpu.blit(source, texture)
                    else:
                        resized = self.engine.gpu.resample(source, (self.res, self.res))
                        try:
                            self.engine.gpu.blit(resized, texture)
                        finally:
                            resized.release()
        self.store.evict(self.ts.pid, TileAddress())
        self.base.capture(self.ts.pid, TileAddress(), base_sources)

    def close(self):
        stores = [self.store, self.base] + [cache.store for cache in (self.evaluation_cache, self.preview_cache) if cache is not None]
        if any(page.pins for store in stores for page in store.pages.values()):
            raise RuntimeError("Release material tile leases before replacing their storage")
        if self.evaluation_cache is not None:
            self.evaluation_cache.close()
            self.evaluation_cache = None
        if self.preview_cache is not None:
            self.preview_cache.close()
            self.preview_cache = None
        self.store.close()
        self.base.close()

    def snapshot(self):
        meta, arrays = self.store.snapshot()
        base_meta, base_arrays = self.base.snapshot()
        for page in base_meta["pages"]:
            for texture in page["textures"]:
                key = texture["array"]
                texture["array"] = "base_" + key
                arrays[texture["array"]] = base_arrays[key]
        return {"version": 1, "addresses": [address.to_list() for address in self.addresses], "res": self.res,
                "mesh_revision": mesh_revision(self.engine.mesh),
                "backing": meta, "base": base_meta, "operations": copy.deepcopy(self.operations),
                "mask_defaults": dict(self.mask_defaults), "sequences": copy.deepcopy(self.sequences)}, arrays

    @classmethod
    def from_snapshot(cls, engine, ts, meta, arrays, source_mesh=None, resident_bytes=None):
        from .tiles import validate_material_tiles
        validate_material_tiles(meta, arrays, source_mesh or engine.mesh, ts.pid, ts.materials, ts.res)
        if (not isinstance(meta, dict) or meta.get("version") != 1 or meta.get("res") != ts.res
                or not isinstance(meta.get("operations"), list) or not isinstance(meta.get("mask_defaults"), dict)):
            raise ValueError("Invalid material tile payload")
        result = cls(engine, ts, resident_bytes)
        if meta.get("addresses") != [address.to_list() for address in result.addresses]:
            raise ValueError("Tile addresses differ from the material's mesh coverage")
        backing = TileStore.from_snapshot(engine.gpu, result.store.limit, meta["backing"], arrays,
                                          forget=engine.painter.forget_textures)
        if any(set_pid != ts.pid or address not in result.layout.pages for set_pid, address in backing.pages):
            backing.close()
            raise ValueError("Tile backing belongs to a different material or address")
        for operation in meta["operations"]:
            validate_operation(operation)
            if (operation["set_pid"] != ts.pid or not isinstance(operation.get("owner_pid"), str)
                    or operation.get("mesh_revision") != meta["mesh_revision"]):
                backing.close()
                raise ValueError("Tile operation has invalid material/mesh provenance")
        defaults = meta["mask_defaults"]
        if any(not isinstance(key, str) or not isinstance(value, (int, float)) or not np.isfinite(value)
               or not 0 <= value <= 1 for key, value in defaults.items()):
            backing.close()
            raise ValueError("Invalid tile mask default")
        result.store.close()
        result.base.close()
        result.base = TileStore.from_snapshot(engine.gpu, backing.limit, meta["base"], arrays,
                                              forget=engine.painter.forget_textures)
        result.store, result.operations, result.mask_defaults = backing, copy.deepcopy(meta["operations"]), dict(defaults)
        result.sequences = copy.deepcopy(meta.get("sequences", {}))
        return result

    def replace(self, meta, arrays):
        staged = type(self).from_snapshot(self.engine, self.ts, meta, arrays, resident_bytes=self.store.limit)
        self.close()
        self.store, self.base = staged.store, staged.base
        self.operations, self.mask_defaults = staged.operations, staged.mask_defaults
        self.sequences = staged.sequences
        self.raster_revision += 1

    def duplicate_layer(self, layer):
        """Copy one subtree's definitions, backing and native replay atomically."""
        from .layers import bind_anchor_references, renew_persistent_ids
        e, ts = self.engine, self.ts
        found = e.find(layer, ts)
        if found is None:
            raise ValueError("Select a layer in this tiled material")
        target, index, parent = found
        # Resolve legacy anchor names on detached definitions, leaving the live
        # tree unchanged if validation or allocation fails.
        forest = [Layer.from_dict(root.to_dict()) for root in ts.layers]
        bind_anchor_references(forest)
        live_effects = {effect.pid: effect for root in ts.layers for item in root.walk()
                        for effect in item.effects + item.mask_effects}
        bindings = [(live_effects[effect.pid], copy.deepcopy(live_effects[effect.pid].params), copy.deepcopy(effect.params))
                    for root in forest for item in root.walk() for effect in item.mask_effects
                    if effect.kind == "anchor" and effect.params != live_effects[effect.pid].params]
        duplicate = next(item for root in forest for item in root.walk() if item.pid == layer.pid)
        objects = [obj for item in duplicate.walk() for obj in [item, *item.effects, *item.mask_effects]]
        old_ids = [obj.pid for obj in objects]
        renew_persistent_ids([duplicate])
        mapping = dict(zip(old_ids, [obj.pid for obj in objects]))
        duplicate.name = layer.name + " copy"
        before = self.snapshot()
        meta, arrays = copy.deepcopy(before[0]), dict(before[1])
        for backing in (meta["backing"], meta["base"]):
            for page in backing["pages"]:
                for record in list(page["textures"]):
                    owner, channel = record["name"].split(":", 1)
                    if owner not in mapping:
                        continue
                    copied = copy.deepcopy(record)
                    copied["name"] = raster_name(mapping[owner], channel)
                    copied["array"] = "duplicate_" + record["array"]
                    arrays[copied["array"]] = arrays[record["array"]]
                    page["textures"].append(copied)
        for operation in list(meta["operations"]):
            if operation["owner_pid"] in mapping:
                copied = copy.deepcopy(operation)
                copied["owner_pid"] = mapping[operation["owner_pid"]]
                meta["operations"].append(copied)
        for key in ("mask_defaults", "sequences"):
            for owner, value in list(meta[key].items()):
                if owner in mapping:
                    meta[key][mapping[owner]] = copy.deepcopy(value)
        entry = ("tile_stack", ts, e._tree(ts.layers), ts.selected, ts.focus,
                 e._edit_serial, before, snapshot_bytes(before) + len(json.dumps([old for _, old, _ in bindings])),
                 [(obj, old) for obj, old, _ in bindings])
        try:
            e._prepare(duplicate)
            self.replace(meta, arrays)
        except Exception:
            for item in duplicate.walk():
                e._release_layer(item, force=True)
            raise
        for obj, _, bound in bindings:
            obj.params = bound
        target.insert(index + 1, duplicate)
        ts.selected = e._root_index(duplicate, ts)
        ts.focus = duplicate if parent is not None else None
        e._push_undo(entry)
        e.dirty = True
        return duplicate

    def preview(self, address, channel=0, resolution=512):
        if self.preview_cache is None:
            from .tilepreview import TilePreview
            self.preview_cache = TilePreview(self)
        return self.preview_cache.lease(address, channel, resolution)

    def cached_evaluation(self, address, resolution=None, refresh=True):
        if self.evaluation_cache is None:
            from .tilecache import TileEvaluationCache
            self.evaluation_cache = TileEvaluationCache(self)
        return self.evaluation_cache.lease(address, resolution, refresh)

    def sequence_diagnostics(self):
        result = []
        for owner, channels in self.sequences.items():
            for channel, paths in channels.items():
                for address in self.addresses:
                    path = paths.get(str(address.udim))
                    if path is None or not os.path.isfile(path):
                        result.append({"owner_pid": owner, "channel": channel, "udim": address.udim,
                                       "path": path, "status": "unassigned" if path is None else "missing"})
        return result

    def assign_sequence(self, layer, channel, paths):
        """Explicit UDIM-to-file assignment; omissions remain visible diagnostics."""
        e = self.engine
        if not any(item is layer for item in e._walk(self.ts.layers)) or layer.kind != "fill" or (channel not in BY_KEY and channel not in e.user_channels):
            raise ValueError("Tile image sequences require this material's fill layer and a valid channel")
        assigned = None
        if paths is not None:
            if not isinstance(paths, dict):
                raise ValueError("Assign an explicit dictionary of integer UDIM numbers to image paths")
            assigned = {}
            for udim, path in paths.items():
                address = TileAddress.from_udim(udim)
                if address not in self.layout.pages or not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
                    raise ValueError("Tile image assignment needs a covered address and an image path")
                path = os.path.abspath(os.path.expanduser(os.fspath(path)))
                if os.path.isfile(path):
                    e.resources.texture(path, descriptor(channel).resource_kind)
                assigned[str(udim)] = path
        before = self.snapshot()
        channels = self.sequences.setdefault(layer.pid, {})
        if assigned is None:
            channels.pop(channel, None)
            if not channels:
                self.sequences.pop(layer.pid, None)
        else:
            channels[channel] = assigned
        e._push_undo(("tile_pixels", self.ts, before, [(item, item.has_mask) for item in e._walk(self.ts.layers)],
                      e._edit_serial, snapshot_bytes(before)))
        e.dirty = True
        return self.sequence_diagnostics()

    def resized(self, resolution, addresses=None):
        with unscissored(self.engine):
            return self._resized(resolution, addresses)

    def _resized(self, resolution, addresses=None):
        """Stage from immutable imported pixels, then replay the global dab stream."""
        from .userchannels import validate_resolution
        validate_resolution(self.engine.user_channels, resolution)
        addresses = self.addresses if addresses is None else tuple(addresses)
        if any(address not in self.layout.pages for address in addresses):
            raise ValueError("Tile does not belong to this material")
        staged = type(self)(self.engine, self.ts, self.store.limit)
        staged.res = resolution
        staged.mask_defaults = dict(self.mask_defaults)
        staged.sequences = copy.deepcopy(self.sequences)
        try:
            meta, arrays = self.base.snapshot()
            staged.base.close()
            staged.base = TileStore.from_snapshot(self.engine.gpu, self.store.limit, meta, arrays,
                                                  forget=self.engine.painter.forget_textures)
            for set_pid, address in self.base.pages:
                if address not in addresses:
                    continue
                with staged.base.lease(set_pid, address) as source, staged.store.lease(set_pid, address) as target:
                    for name, texture in source.items():
                        output = target.texture(name, (resolution, resolution), texture.components, texture.dtype)
                        self.engine.gpu.blit(texture, output)
                staged.base.evict(set_pid, address)
                staged.store.evict(set_pid, address)
            operations = list(self.operations)
            active = getattr(self.engine, "_tile_stroke", None)
            if active is not None and active.material is self and active.changed:
                operations.append(active.operation)
            for operation in operations:
                staged._apply_operation(operation, addresses=addresses)
            staged.operations = copy.deepcopy(operations)
            return staged
        except Exception:
            staged.close()
            raise

    def reset_raster(self, owner, mask=False, value=0.):
        """Replace this owner's tile raster/base without allocating GPU textures."""
        e = self.engine
        if mask and (not isinstance(value, (int, float)) or not np.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("Mask fill must be finite and between zero and one")
        before = self.snapshot()
        meta, arrays = copy.deepcopy(before[0]), before[1]
        flags = [(layer, layer.has_mask) for layer in e._walk(self.ts.layers)]
        names = {raster_name(owner.pid, "mask")} if mask else {raster_name(owner.pid, channel.key) for channel in list(CHANNEL_DESCRIPTORS) + [descriptor(key) for key in e.user_channels]}
        target = "mask" if mask else "layer"
        changed = False
        for backing in (meta["backing"], meta["base"]):
            for page in backing["pages"]:
                kept = [texture for texture in page["textures"] if texture["name"] not in names]
                changed |= len(kept) != len(page["textures"])
                page["textures"] = kept
        operations = [operation for operation in meta["operations"]
                      if operation["owner_pid"] != owner.pid or operation["target"] != target]
        changed |= len(operations) != len(meta["operations"])
        meta["operations"] = operations
        if mask:
            meta["mask_defaults"][owner.pid] = float(value)
            changed = True
        if not changed:
            return False
        self.replace(meta, arrays)
        if mask and isinstance(owner, Layer):
            owner.has_mask = True
        e._push_undo(("tile_pixels", self.ts, before, flags, e._edit_serial, snapshot_bytes(before)))
        e.dirty = True
        return True

    def fill_triangles(self, owner, tris, brush, mask=False, erase=False, value=1.):
        """Stage a raster fill; flatten only this owner's affected target for replay."""
        e = self.engine
        if mask and (not isinstance(value, (int, float)) or not np.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("Mask fill must be finite and between zero and one")
        selected_tiles = {address: np.intersect1d(tris, self.layout.pages[address].source_triangles)
                          for address in self.addresses}
        if not any(len(selected) for selected in selected_tiles.values()):
            return False
        before = self.snapshot()
        flags = [(layer, layer.has_mask) for layer in e._walk(self.ts.layers)]
        target = "mask" if mask else "layer"
        names = {raster_name(owner.pid, "mask")} if mask else {raster_name(owner.pid, channel.key) for channel in list(CHANNEL_DESCRIPTORS) + [descriptor(key) for key in e.user_channels]}
        initial_state = before
        if mask and isinstance(owner, Layer) and not owner.has_mask:
            meta = copy.deepcopy(before[0])
            for backing in (meta["backing"], meta["base"]):
                for page in backing["pages"]:
                    page["textures"] = [record for record in page["textures"] if record["name"] not in names]
            meta["operations"] = [operation for operation in meta["operations"]
                                  if operation["owner_pid"] != owner.pid or operation["target"] != "mask"]
            meta["mask_defaults"][owner.pid] = 0. if value > .5 and not erase else 1.
            initial_state = (meta, before[1])
        staged = type(self).from_snapshot(e, self.ts, *initial_state, resident_bytes=self.store.limit)
        try:
            if mask:
                initial = (0. if value > .5 and not erase else 1.) if isinstance(owner, Layer) and not owner.has_mask else 1.
                staged.mask_defaults.setdefault(owner.pid, float(getattr(owner, "params", {}).get("initial", initial)))
            for address, selected in selected_tiles.items():
                if not len(selected):
                    continue
                with staged._geometry(address) as (_, gm), staged.store.lease(self.ts.pid, address) as page:
                    if mask:
                        texture = page.get(raster_name(owner.pid, "mask"))
                        if texture is None:
                            texture = page.texture(raster_name(owner.pid, "mask"), (self.res, self.res), 1)
                            e.gpu.fill(texture, (staged.mask_defaults[owner.pid],) * 4)
                        textures = texture
                    else:
                        textures = _LeasePaint(e.gpu, self.res, page, owner.pid)
                        textures.ensure([channel.key for channel in CHANNEL_DESCRIPTORS if brush.enabled[channel.index]])
                    e.painter.fill_tris(gm, selected, textures, brush, e._view(), erase, value if mask else None)
            # Raster edits are canonical bases at authored resolution. Other
            # owners retain their bases and native journals without modification.
            base_meta, base_arrays = staged.base.snapshot()
            authored_meta, authored_arrays = staged.store.snapshot()
            pages = {tuple(page["address"]): page for page in base_meta["pages"]}
            for page in pages.values():
                page["textures"] = [record for record in page["textures"] if record["name"] not in names]
            for source in authored_meta["pages"]:
                records = [record for record in source["textures"] if record["name"] in names]
                if not records:
                    continue
                address = tuple(source["address"])
                if address not in pages:
                    pages[address] = {"set_pid": self.ts.pid, "address": list(address), "textures": []}
                    base_meta["pages"].append(pages[address])
                for record in records:
                    record = copy.deepcopy(record)
                    member = record["array"]
                    record["array"] = "fill_" + member
                    base_arrays[record["array"]] = authored_arrays[member]
                    pages[address]["textures"].append(record)
            replacement = TileStore.from_snapshot(e.gpu, self.base.limit, base_meta, base_arrays,
                                                   forget=e.painter.forget_textures)
            staged.base.close()
            staged.base = replacement
            staged.operations = [operation for operation in staged.operations
                                 if operation["owner_pid"] != owner.pid or operation["target"] != target]
            result = staged.snapshot()
        finally:
            staged.close()
        self.replace(*result)
        if mask and isinstance(owner, Layer):
            owner.has_mask = True
        e._push_undo(("tile_pixels", self.ts, before, flags, e._edit_serial, snapshot_bytes(before)))
        e.dirty = True
        return True

    def _page_mesh(self, address):
        if address not in self.layout.pages:
            raise ValueError("Tile does not belong to this material")
        mesh = self.layout.pages[address].raster_mesh(self.engine.mesh, retain_topology=True)
        gm = GPUMesh(self.engine.gpu, mesh)
        gm.add_subset(self.ts.key, self.layout.pages[address].source_triangles)
        return mesh, gm

    @contextmanager
    def _geometry(self, address):
        mesh, gm = self._page_mesh(address)
        try:
            yield mesh, gm
        finally:
            gm.release()

    def _record_uv(self, samples, mapping, brush, owner):
        e = self.engine
        if brush.tool in (TOOL_CLONE, TOOL_SMUDGE) or brush.target == 2 or e.quick_mask_enabled:
            raise ValueError("Tiled clone/smudge/quick-mask dispatch is not integrated yet")
        if brush.symmetry:
            raise ValueError("Object symmetry is unavailable for native UV operations")
        target = "layer" if brush.target == 0 else "mask"
        dummy = PaintTextures(e.gpu, 1) if target == "layer" else e.gpu.texture((1, 1), 1)
        if target == "mask":
            e.gpu.fill(dummy, (0, 0, 0, 0))
        view = View(np.eye(4), mapping.size, np.array([0., 0., 1.]), np.array([1., 0., 0.]),
                    e.gpu.white, None, lambda p: mapping.units_per_pixel, uv_mapping=mapping)
        stroke = None
        try:
            stroke = Stroke(_Recorder(e.painter), e.gm, self.ts.key, brush, view,
                            lambda p, tri: e.uv_brush_radius(tri, mapping, brush), target, dummy,
                            seed=brush.seed, mask_value=brush.mask_value)
            for uv, pressure in samples:
                tri = uv_triangle(e.mesh, self.ts.tri_ids, uv, single_tile=False)
                if tri is None:
                    stroke.recorded_samples.append({"event": "break", "uv": list(uv), "seconds": 0.})
                    stroke.last, stroke.last_px, stroke.carry = None, None, 0.
                    continue
                point = np.array([*uv, 0.], float)
                surface = Surface(point, np.array([0., 0., 1.]), np.asarray(uv), tri, pressure)
                (stroke.start if stroke.last is None else stroke.feed)(surface)
            return operation_from_stroke(self, stroke, owner)
        finally:
            if stroke is not None:
                stroke.release()
            if target == "layer":
                e.painter.forget_textures(list(dummy.values()))
                for texture in dummy.values():
                    texture.release()
            else:
                dummy.release()

    def _apply_operation(self, operation, store=None, resolution=None, addresses=None):
        e, store = self.engine, store or self.store
        res = resolution or self.res
        brush = Brush()
        brush.load_dict(operation["brush"])
        for address in self.addresses if addresses is None else addresses:
            # Only tiles touched by the recorded UV footprint need authored storage.
            touched = any(touches_tile(self, operation, record, address, brush) for record in operation["dabs"])
            if not touched:
                continue
            with unscissored(e), self._geometry(address) as (_, gm), store.lease(self.ts.pid, address) as lease:
                stroke, coverage = None, None
                try:
                    if operation["target"] == "layer":
                        textures = _LeasePaint(e.gpu, res, lease, operation["owner_pid"])
                    else:
                        name = raster_name(operation["owner_pid"], "mask")
                        textures = lease.get(name)
                        if textures is None:
                            textures = lease.texture(name, (res, res), 1)
                            value = self.mask_defaults.get(operation["owner_pid"], 0.)
                            e.gpu.fill(textures, (value,) * 4)
                    if operation["coordinate_space"] == "uv":
                        coverage = self._coverage(gm, res)
                    with tile_views(e, operation, address, coverage) as get_view:
                        stroke = Stroke(e.painter, gm, self.ts.key, brush, get_view(0), lambda p, tri: 1.,
                                        operation["target"], textures, seed=operation["seed"], mask_value=brush.mask_value)
                        for record in operation["dabs"]:
                            stroke.view = get_view(record["view"])
                            values = copy.deepcopy(record["values"])
                            for key in ("hit", "hit_px", "hit_uv", "sym_inv"):
                                values[key] = np.asarray(values[key])
                            values["frame"] = tuple(np.asarray(value) for value in values["frame"])
                            dab = Dab(**values)
                            if operation["target"] == "layer":
                                e.painter.dab_paint(gm, self.ts.key, stroke.buffers, stroke.brush, stroke.view, dab, None,
                                                   projection=brush.tool == TOOL_PROJECTION)
                            else:
                                e.painter.dab_mask(gm, self.ts.key, stroke.buffers[0], stroke.brush, stroke.view, dab, None)
                            stroke.changed = True
                        stroke.apply()
                finally:
                    if coverage is not None:
                        coverage.release()
                    if stroke is not None:
                        stroke.release()

    def _coverage(self, gm, res):
        e = self.engine
        texture = e.gpu.texture((res, res), 1, dtype="f1", filt=False)
        fbo = None
        try:
            fbo = e.ctx.framebuffer([texture])
            fbo.use()
            e.ctx.viewport = (0, 0, res, res)
            import moderngl
            e.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
            fbo.clear()
            program = e.gpu.program("tile_coverage", S.UV_VS, S.HEADER + "out vec4 o; void main() { o = vec4(1.0); }")
            gm.render(program, self.ts.key)
            return texture
        except Exception:
            texture.release()
            raise
        finally:
            if fbo is not None:
                fbo.release()

    def paint_uv(self, points, mapping, brush=None):
        e = self.engine
        if e.ts is not self.ts or not e.can_paint():
            raise ValueError("Select a paintable layer/effect in this material first")
        brush = freeze_brush(brush or e.brush)
        if brush.target == 0 and not any(brush.enabled):
            return False
        owner = e.active_mask_paint() or e.layer if brush.target == 1 else e.layer
        points = list(points)
        if any(len(point) not in (2, 3) for point in points):
            raise ValueError("UV samples require two coordinates and optional pressure")
        samples = [(np.asarray(point[:2], float), float(point[2]) if len(point) == 3 else 1.) for point in points]
        if any(uv.shape != (2,) or not np.isfinite(uv).all() or not np.isfinite(pressure) for uv, pressure in samples):
            raise ValueError("Invalid UV/pressure sample")
        operation = self._record_uv(samples, mapping, brush, owner)
        validate_operation(operation)
        if not operation["dabs"]:
            return False
        before = self.snapshot()
        flags = [(layer, layer.has_mask) for layer in e._walk(self.ts.layers)]
        try:
            if brush.target == 1:
                if owner is e.layer:
                    if not owner.has_mask:
                        self.mask_defaults[owner.pid] = 0. if brush.mask_value > .5 else 1.
                        owner.has_mask = True
                    else:
                        self.mask_defaults.setdefault(owner.pid, 1.)
                else:
                    self.mask_defaults.setdefault(owner.pid, float(owner.params.get("initial", 0.)))
            self._apply_operation(operation)
            self.operations.append(operation)
        except Exception:
            self.replace(*before)
            for layer, has_mask in flags:
                layer.has_mask = has_mask
            raise
        e._push_undo(("tile_pixels", self.ts, before, flags, e._edit_serial, snapshot_bytes(before)))
        e.dirty = True
        return True

    @contextmanager
    def evaluate(self, address, resolution=None):
        res = self.res if resolution is None else resolution
        if type(res) is not int or not 1 <= res <= 8192 or address not in self.addresses:
            raise ValueError("Invalid material tile/resolution")
        with unscissored(self.engine):
            edges = self._normal_edges(address, res)
            with self._evaluate(address, resolution, edges) as tile:
                yield tile

    def _normal_edges(self, address, res):
        """Stream four neighbors, retaining only O(res) height/coverage strips."""
        varying = any(name.endswith(":H") for store in (self.store, self.base) for page in store.pages.values()
                      for name in set(page.saved) | set(page.textures))
        varying |= any(layer.visible and layer.enabled[3] and layer.kind == "fill" and
                       (layer.height != .5 or layer.bump or (layer.maps or {}).get("H") or
                        self.sequences.get(layer.pid, {}).get("H") or layer.effects)
                       for layer in self.engine._walk(self.ts.layers))
        if not varying:
            return None
        edges = np.zeros((4, res, 2), np.float32)
        geometry = self._edge_geometry(address, res)
        for edge, delta in enumerate(((-1, 0), (1, 0), (0, -1), (0, 1))):
            u, v = address.u + delta[0], address.v + delta[1]
            neighbor = next((item for item in self.addresses if (item.u, item.v) == (u, v)), None)
            if neighbor is None:
                continue
            with self._evaluate(neighbor, res) as tile:
                rect = ((res - 1, 0, 1, res), (0, 0, 1, res), (0, res - 1, res, 1), (0, 0, res, 1))[edge]
                position = None
                for component, texture in enumerate((tile.comp.rmh, tile.bakes.cov, tile.bakes.pos)):
                    fbo = self.engine.ctx.framebuffer([texture])
                    try:
                        values = np.frombuffer(fbo.read(viewport=rect, components=texture.components, dtype="f4"), np.float32)
                        values = values.reshape(res, texture.components)
                        if component < 2:
                            edges[edge, :, component] = values[:, 2 if component == 0 else 0]
                        else:
                            position = values
                    finally:
                        fbo.release()
                outer, inner = geometry[edge], geometry[edge + 4]
                direction = outer[:, :3] - inner[:, :3]
                step = np.linalg.norm(direction, axis=1)
                delta = position[:, :3] - outer[:, :3]
                distance = np.linalg.norm(delta, axis=1)
                along = (delta * direction).sum(axis=1) / np.maximum(step, 1e-12)
                perpendicular = np.linalg.norm(delta - direction * (along / np.maximum(step, 1e-12))[:, None], axis=1)
                tolerance = self.engine.mesh.radius * 1e-6
                continuous = ((outer[:, 3] > .5) & (inner[:, 3] > .5) & (position[:, 3] > .5) &
                              (distance <= step * 4 + tolerance) & (along >= -tolerance) &
                              (perpendicular <= step * .1 + tolerance))
                edges[edge, :, 1] *= continuous
        return edges

    def _edge_geometry(self, address, res):
        """Rasterize border/inward world positions in O(res) storage for seam ownership."""
        import moderngl
        e = self.engine
        vertex = S.UV_VS.replace("void main()", "uniform int u_edge; uniform float u_at; uniform float u_resolution;\nvoid main()")
        vertex = vertex.replace("gl_Position = vec4(in_uv * 2.0 - 1.0, 0.0, 1.0);",
            "vec2 q = u_edge < 2 ? in_uv.yx : in_uv; gl_Position = vec4(q.x * 2.0 - 1.0, (q.y - u_at) * 2.0 * u_resolution, 0.0, 1.0);")
        program = e.gpu.program("tile-edge-geometry", vertex, S.HEADER + "in vec3 v_pos; out vec4 o; void main() { o = vec4(v_pos, 1.0); }")
        texture = e.gpu.texture((res, 8), 4, dtype="f4", filt=False)
        fbo = None
        try:
            fbo = e.ctx.framebuffer([texture])
            fbo.use()
            e.ctx.scissor = None
            e.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
            fbo.clear()
            with self._geometry(address) as (_, gm):
                for row in range(8):
                    edge = row % 4
                    inset = min((.5 if row < 4 else 1.5) / res, .5)
                    e.gpu.set(program, "u_edge", edge)
                    e.gpu.set(program, "u_at", inset if edge in (0, 2) else 1 - inset)
                    e.gpu.set(program, "u_resolution", float(res))
                    e.ctx.viewport = (0, row, res, 1)
                    gm.render(program, self.ts.key)
            return np.frombuffer(fbo.read(components=4, dtype="f4"), np.float32).reshape(8, res, 4).copy()
        finally:
            if fbo is not None:
                fbo.release()
            texture.release()

    @contextmanager
    def _evaluate(self, address, resolution=None, edges=None):
        if resolution is not None and resolution != self.res:
            if type(resolution) is not int or not 1 <= resolution <= 8192:
                raise ValueError("Tile resolution must be an integer between 1 and 8192")
            staged = self.resized(resolution, (address,))
            try:
                with staged._evaluate(address, edges=edges) as result:
                    yield result
            finally:
                staged.close()
            return
        from .baker import Baker
        from .compositor import Compositor
        e, res = self.engine, self.res
        mesh, gm = self._page_mesh(address)
        comp = bakes = None
        proxy = _AllocationProxy(e.gpu)
        try:
            with self.store.lease(self.ts.pid, address) as lease:
                memo = {}
                def clone(layer):
                    if id(layer) in memo:
                        return memo[id(layer)]
                    copy_layer = Layer.from_dict(layer.to_dict())
                    memo[id(layer)] = copy_layer
                    copy_layer.children = [clone(child) for child in layer.children]
                    if layer.kind == "fill":
                        copy_layer.maps = dict(layer.maps or {})
                        for channel, paths in self.sequences.get(layer.pid, {}).items():
                            enabled = layer.enabled[BY_KEY[channel].index] if channel in BY_KEY else layer.user_channels.get(channel,{}).get("enabled",False)
                            if not layer.visible or not enabled:
                                continue
                            path = paths.get(str(address.udim))
                            if path is None or not os.path.isfile(path):
                                raise ValueError(f"Missing tile image: {layer.name}, {channel}, UDIM {address.udim}: {path or 'unassigned'}")
                            # The legacy compositor falls back to constants on a
                            # bitmap failure. An explicit tile assignment must
                            # reject decode/upload errors before evaluation.
                            e.resources.texture(path, descriptor(channel).resource_kind)
                            copy_layer.maps[channel] = path
                    if layer.kind == "paint":
                        copy_layer.tex = _LeasePaint(e.gpu, res, lease, layer.pid)
                    copy_layer.mask_tex = lease.get(raster_name(layer.pid, "mask"))
                    if layer.has_mask and copy_layer.mask_tex is None:
                        copy_layer.mask_tex = lease.texture(raster_name(layer.pid, "mask"), (res, res), 1)
                        e.gpu.fill(copy_layer.mask_tex, (self.mask_defaults.get(layer.pid, 1.),) * 4)
                    for source, effect in zip(layer.mask_effects, copy_layer.mask_effects):
                        if source.kind == "paint":
                            effect.tex = lease.get(raster_name(source.pid, "mask"))
                            if effect.tex is None:
                                effect.tex = lease.texture(raster_name(source.pid, "mask"), (res, res), 1)
                                e.gpu.fill(effect.tex, (self.mask_defaults.get(source.pid, float(source.params.get("initial", 0.))),) * 4)
                    return copy_layer
                layers = [clone(layer) for layer in self.ts.layers]
                settings = copy.deepcopy(self.ts.bake_settings)
                if settings.external_maps:
                    raise ValueError("Assigning external tile map sequences is not integrated yet")
                bakes = Baker(proxy).bake(gm, res, subset=self.ts.key, settings=settings, high=e._high_for(self.ts),
                                         cage=e._cage_for(self.ts), **e._corrections_for(self.ts, lease))
                comp = Compositor(proxy, res, bakes, e.mesh, e.resources)
                comp.authored_origin=address.to_list()
                comp.composite(layers, e.normal_strength)
                if edges is not None:
                    edge_texture = proxy.texture((res, 4), 2, edges, dtype="f4", filt=False)
                    try:
                        comp.finish_normal(e.normal_strength, edge_texture)
                    finally:
                        edge_texture.release()
                yield SimpleNamespace(name=self.ts.name, pid=self.ts.pid, key=self.ts.key, materials=self.ts.materials,
                                      res=res, layers=layers, comp=comp, bakes=bakes, address=address, gm=gm)
        except Exception:
            proxy.rollback()
            raise
        finally:
            if comp is not None:
                comp.release()
            if bakes is not None:
                bakes.release()
            gm.release()
            e.gpu.release_scratch()
