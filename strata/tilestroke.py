"""One native UV stroke, streamed through bounded tile-local accumulation buffers."""
import copy
import time
from types import SimpleNamespace
import numpy as np
import moderngl
from .channels import CHANNEL_DESCRIPTORS
from .userchannels import paint_channels
from .paintstore import PaintTextures
from .tilestore import TileStore
from .painter import Stroke, Surface, View, Dab, TOOL_PROJECTION
from .journal import freeze_brush, validate_operation
from .materialtiles import _Recorder, _LeasePaint, raster_name, snapshot_bytes, operation_from_stroke, touches_tile, tile_views, unscissored


class TileStroke:
    def __init__(self, material, uv=None, mapping=None, pressure=1., seed=None, surface=None, view=None):
        self.material, self.engine = material, material.engine
        e = self.engine
        self.owner = (e.active_mask_paint() or e.layer) if e.brush.target == 1 else e.layer
        self.before, self.serial = material.snapshot(), e._edit_serial
        self.flags = [(layer, layer.has_mask) for layer in e._walk(material.ts.layers)]
        self.changed, self.closed = False, False
        self.state = TileStore(e.gpu, material.store.limit, forget=e.painter.forget_textures)
        self.recorder, self.dummy = None, None
        self.brush = freeze_brush(e.brush)
        self.target = "layer" if self.brush.target == 0 else "mask"
        try:
            self.dummy = PaintTextures(e.gpu, 1) if self.target == "layer" else e.gpu.texture((1, 1), 1)
            if self.target == "mask":
                e.gpu.fill(self.dummy, (0, 0, 0, 0))
            self.recorder = Stroke(_Recorder(e.painter), e.gm, material.ts.key, self.brush, view or self.view(mapping),
                lambda p, tri: (e.uv_brush_radius(tri, self.recorder.view.uv_mapping, self.brush)
                               if self.recorder.view.uv_mapping is not None else e.brush_radius(p, tri, self.brush)), self.target,
                self.dummy, seed=self.brush.seed if seed is None else seed, mask_value=self.brush.mask_value)
            self.brush = self.recorder.brush
            self.operation = operation_from_stroke(material, self.recorder, self.owner)
            if surface is None:
                self.feed(uv, pressure)
            else:
                self.feed_surface(surface, view)
        except Exception:
            self.cancel()
            raise

    def view(self, mapping, address=None, coverage=None):
        return View(np.eye(4), mapping.size, np.array([0., 0., 1.]), np.array([1., 0., 0.]),
                    coverage or self.engine.gpu.white, None, lambda p: mapping.units_per_pixel,
                    uv_mapping=mapping, tile_offset=(0, 0) if address is None else tuple(address.to_list()))

    def feed(self, uv, pressure=1., mapping=None):
        if self.closed:
            return
        e, m, st = self.engine, self.material, self.recorder
        if self.operation["coordinate_space"] != "uv":
            raise ValueError("Use surface input for a 3D tile stroke")
        uv = np.asarray(uv, float)
        if uv.shape != (2,) or not np.isfinite(uv).all() or not np.isfinite(pressure):
            raise ValueError("Invalid UV/pressure sample")
        if e.ts is not m.ts:
            raise ValueError("The stroke's material changed")
        if mapping is not None:
            st.view = self.view(mapping)
        info = e.pick_uv(uv)
        if info is None:
            st.recorded_samples.append({"event": "break", "uv": uv.tolist(), "seconds": time.monotonic() - st.started_at})
            st.last, st.last_px, st.carry = None, None, 0.
            return
        surface = Surface(np.array([*uv, 0.]), np.array([0., 0., 1.]), uv, info["tri"], float(pressure))
        self.feed_surface(surface)

    def feed_surface(self, surface, view=None):
        if self.closed:
            return
        e, m, st = self.engine, self.material, self.recorder
        if e.ts is not m.ts:
            raise ValueError("The stroke's material changed")
        if view is not None:
            st.view = view
        if (not np.isfinite(surface.pressure) or not np.isfinite(surface.pos).all()
                or not np.isfinite(surface.uv).all() or not np.isfinite(surface.nrm).all()):
            raise ValueError("Invalid surface/pressure sample")
        if surface.tri not in m.ts.tri_ids:
            st.recorded_samples.append({"event": "break", "seconds": time.monotonic() - st.started_at})
            st.last, st.last_px, st.carry = None, None, 0.
            return
        start, sample_start = len(st.recorded_dabs), len(st.recorded_samples)
        (st.start if st.last is None else st.feed)(surface)
        records = st.recorded_dabs[start:]
        validate_operation(dict(self.operation, dabs=records, samples=st.recorded_samples[sample_start:]))
        if not records:
            return
        if self.target == "mask":
            if self.owner is e.layer and not self.owner.has_mask:
                # Recreating a disabled mask starts fresh, matching add_mask in
                # the single-tile path. Cancellation still restores old backing.
                meta = copy.deepcopy(self.before[0])
                name = raster_name(self.owner.pid, "mask")
                for backing in (meta["backing"], meta["base"]):
                    for page in backing["pages"]:
                        page["textures"] = [record for record in page["textures"] if record["name"] != name]
                meta["operations"] = [operation for operation in meta["operations"]
                                      if operation["owner_pid"] != self.owner.pid or operation["target"] != "mask"]
                meta["mask_defaults"][self.owner.pid] = 0. if self.brush.mask_value > .5 else 1.
                m.replace(meta, self.before[1])
                self.owner.has_mask = True
            elif self.owner is e.layer:
                m.mask_defaults.setdefault(self.owner.pid, 1.)
            else:
                m.mask_defaults.setdefault(self.owner.pid, float(getattr(self.owner, "params", {}).get("initial", 0.)))
        for address in m.addresses:
            local = [record for record in records if touches_tile(m, self.operation, record, address, self.brush)]
            if local:
                self.dispatch(address, local)
        self.changed = True
        m.raster_revision += 1
        e.dirty = True

    def dispatch(self, address, records):
        e, m, b = self.engine, self.material, self.brush
        with unscissored(e), m._geometry(address) as (_, gm), m.store.lease(m.ts.pid, address) as authored, self.state.lease(m.ts.pid, address) as state:
            coverage = state.get("coverage")
            if coverage is None and self.operation["coordinate_space"] == "uv":
                generated = m._coverage(gm, m.res)
                try:
                    coverage = state.texture("coverage", (m.res, m.res), 1, "f1")
                    e.gpu.blit(generated, coverage)
                finally:
                    generated.release()
            if coverage is not None:
                coverage.filter = (moderngl.NEAREST, moderngl.NEAREST)
            snapshot, buffers = {}, []
            if self.target == "layer":
                textures = _LeasePaint(e.gpu, m.res, authored, self.owner.pid)
                channels = paint_channels(b)
                textures.ensure([channel.key for channel in channels])
                sources = [(channel.key, textures[channel.key], max(4, channel.paint_components)) for channel in channels]
            else:
                name = raster_name(self.owner.pid, "mask")
                textures = authored.get(name)
                if textures is None:
                    textures = authored.texture(name, (m.res, m.res), 1)
                    e.gpu.fill(textures, (m.mask_defaults.get(self.owner.pid, 0.),) * 4)
                sources = [("mask", textures, 1)]
            for key, source, components in sources:
                saved = state.get("base/" + key)
                if saved is None:
                    saved = state.texture("base/" + key, source.size, source.components, source.dtype)
                    e.gpu.blit(source, saved)
                snapshot[key] = saved
                buffers.append(state.texture("buffer/" + key, source.size, components, source.dtype))
            with tile_views(e, self.operation, address, coverage) as get_view:
                for record in records:
                    values = copy.deepcopy(record["values"])
                    for key in ("hit", "hit_px", "hit_uv", "sym_inv"):
                        values[key] = np.asarray(values[key])
                    values["frame"] = tuple(np.asarray(value) for value in values["frame"])
                    dab = Dab(**values)
                    view = get_view(record["view"])
                    if self.target == "layer":
                        e.painter.dab_paint(gm, m.ts.key, buffers, b, view, dab, None, projection=b.tool == TOOL_PROJECTION)
                    else:
                        e.painter.dab_mask(gm, m.ts.key, buffers[0], b, view, dab, None)
            # Reuse the ordinary stroke merge, including its opacity ceiling.
            Stroke.apply(SimpleNamespace(changed=True, direct=False, brush=b, target=self.target,
                painter=e.painter, textures=textures, snapshot=snapshot, buffers=buffers,
                erase=b.mode == 1, mask_value=b.mask_value))

    def finish(self):
        if self.closed:
            return
        if self.changed:
            validate_operation(self.operation)
            self.material.operations.append(self.operation)
            self.engine._push_undo(("tile_pixels", self.material.ts, self.before, self.flags,
                                    self.serial, snapshot_bytes(self.before)))
        self.release()

    def cancel(self, restore=True):
        if self.closed:
            return
        if restore:
            self.material.replace(*self.before)
            for layer, has_mask in self.flags:
                layer.has_mask = has_mask
            self.engine.dirty = True
        self.release()

    def release(self):
        self.state.close()
        if self.recorder is not None:
            self.recorder.release()
        if isinstance(self.dummy, dict):
            for texture in self.dummy.values():
                texture.release()
        elif self.dummy is not None:
            self.dummy.release()
        self.closed = True
