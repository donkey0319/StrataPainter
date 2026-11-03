"""Disposable, revision-keyed tile thumbnails; authored leases never escape evaluation."""
import os
from .tilestore import TileStore
from . import shaders as S

CHANNELS = ("Color", "Roughness", "Metallic", "Height", "Normal", "Emissive", "Opacity", "Mask", "AO", "Curvature")
SOURCES = (("color", -1), ("rmh", 0), ("rmh", 1), ("rmh", 2), ("normal", -1),
           ("emissive", -1), ("rmh", 3), ("mask_preview", 0), ("ao", 0), ("curv", 0))
FS = """
uniform sampler2D u_src, u_cov;
uniform int u_component, u_display;
in vec2 v_uv; out vec4 o;
void main() {
    vec4 value = texture(u_src, v_uv);
    vec3 c = u_component < 0 ? value.rgb : vec3(value[u_component]);
    if (u_display == 1) c = displayColor(vec4(c, 1.0)).rgb;
    float check = mod(floor(v_uv.x * 24.0) + floor(v_uv.y * 24.0), 2.0);
    vec3 bg = vec3(mix(0.085, 0.11, check));
    o = vec4(mix(bg, c, step(0.5, texture(u_cov, v_uv).r)), 1.0);
}
"""


class TilePreview:
    def __init__(self, material, resident_bytes=64 * 1024**2):
        self.material = material
        e = material.engine
        self.store = TileStore(e.gpu, resident_bytes)
        self.key = None
        self.ready = set()
        self.evaluations = 0

    def close(self):
        self.store.close()

    def revision(self, channel, resolution):
        e, ts = self.material.engine, self.material.ts
        paths = {path for path in ts.bake_settings.high_poly if not path.startswith("<mesh:")}
        if ts.bake_settings.cage_path:
            paths.add(ts.bake_settings.cage_path)
        for layer in e._walk(ts.layers):
            paths.update(path for path in (layer.maps or {}).values() if path and not path.startswith("bake:"))
            paths.update(effect.params["map"] for effect in layer.effects + layer.mask_effects if effect.params.get("map"))
        for channels in self.material.sequences.values():
            for assigned in channels.values():
                paths.update(assigned.values())
        from .projectio import resource_slots
        operations = self.material.operations
        operation_key = (id(operations), len(operations))
        if operation_key != getattr(self, "_operation_paths_key", None):
            self._operation_paths = {owner[key] for operation in operations
                for owner, key, _ in resource_slots({"brush": operation["brush"]})}
            self._operation_paths_key = operation_key
        paths.update(self._operation_paths)
        active = getattr(e, "_tile_stroke", None)
        if active is not None and active.material is self.material:
            paths.update(owner[key] for owner, key, _ in resource_slots({"brush": active.operation["brush"]}))
        stamps = []
        for path in sorted(paths):
            try:
                stat = os.stat(path)
                stamps.append((path, stat.st_mtime_ns, stat.st_size))
            except OSError:
                stamps.append((path, None, None))
        return (e._edit_serial, e._signature(), self.material.layout.revision, self.material.raster_revision, e.color.cache_id,
                e.layer.pid if e.layer else None, channel, resolution, tuple(stamps))

    def lease(self, address, channel=0, resolution=512):
        """Return a context manager exposing one display-ready texture, with bounded residency."""
        from contextlib import contextmanager
        @contextmanager
        def acquire():
            if type(channel) is not int or not 0 <= channel < len(CHANNELS):
                raise ValueError("Unknown tile preview channel")
            if type(resolution) is not int or not 1 <= resolution <= 2048:
                raise ValueError("Tile preview resolution must be between 1 and 2048")
            m, e = self.material, self.material.engine
            if address not in m.addresses:
                raise ValueError("Tile does not belong to this material")
            res = min(resolution, m.res)
            revision = self.revision(channel, res)
            if revision != self.key:
                limit = self.store.limit
                self.store.close()
                self.store = TileStore(e.gpu, limit)
                self.key = revision
                self.ready.clear()
            with self.store.lease(m.ts.pid, address) as page:
                texture = page.get("preview")
                if texture is None or address not in self.ready:
                    # Derived cache owns only the thumbnail. Bakes, composites and
                    # authored texture references are released before returning it.
                    with m.evaluate(address, resolution=res) as tile:
                        name, component = SOURCES[channel]
                        if channel == 7 and e.layer is not None:
                            selected = next((layer for root in tile.layers for layer in root.walk() if layer.pid == e.layer.pid), None)
                            if selected is not None:
                                tile.comp.render_mask(selected)
                        source = getattr(tile.bakes if channel >= 8 else tile.comp, name)
                        texture = page.texture("preview", (res, res), 4, "f1")
                        display = (e.color.display_shader + "\nvec4 displayColor(vec4 c) { return ocio_display(c); }\n"
                                   if e.color.managed else "vec4 displayColor(vec4 c) { return c; }\n")
                        program = e.gpu.fs_program("tile-preview/" + str(e.color.config_id or "legacy"), S.HEADER + display + FS)
                        fbo = e.ctx.framebuffer([texture])
                        try:
                            import moderngl
                            fbo.use()
                            e.ctx.viewport = (0, 0, res, res)
                            e.ctx.scissor = None
                            e.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
                            e.gpu.bind(program, {"u_src": (0, source), "u_cov": (1, tile.bakes.cov)})
                            e.gpu.set(program, "u_component", component)
                            e.gpu.set(program, "u_display", int(channel in (0, 5)))
                            e.gpu.draw_quad(program)
                        except Exception:
                            # Never publish a partially rendered cache entry.
                            self.key = None
                            raise
                        finally:
                            fbo.release()
                        self.evaluations += 1
                        self.ready.add(address)
                yield texture
        return acquire()
