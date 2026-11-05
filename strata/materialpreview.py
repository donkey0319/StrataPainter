"""Cached material thumbnails rendered with the real compositor and PBR sphere."""
from collections import OrderedDict
import copy
import json

import moderngl

from .baker import Baker
from .compositor import Compositor
from .gpu import GPUMesh
from .layers import Layer
from .mesh import make_sphere
from .renderer import Camera, Renderer


class MaterialPreviews:
    SIZE = 160
    LIMIT = 64

    def __init__(self, engine):
        self.engine = engine
        self.cache = OrderedDict()
        self.gm = self.bakes = self.comp = None
        self.renderer = None
        self.pipeline = None
        self.camera = Camera()
        self.camera.frame((0, 0, 0), 1.0)

    @staticmethod
    def material(obj):
        """Use the same material channels for a brush and a uniform fill."""
        layer = Layer(name="Material preview", kind="fill", seed=0.0)
        for attr in ("color", "rough", "metal", "height", "normal", "emissive", "opac", "enabled"):
            setattr(layer, attr, copy.deepcopy(getattr(obj, attr)))
        return layer

    def _setup(self):
        e = self.engine
        if self.gm is None:
            mesh = make_sphere(seg_u=64, seg_v=32)
            self.gm = GPUMesh(e.gpu, mesh)
        if self.bakes is None:
            self.bakes = Baker(e.gpu).bake(self.gm, 128, ao_samples=8, ao_res=64)
        if self.comp is None or self.pipeline != e.color.cache_id:
            if self.comp is not None:
                self.comp.release()
            self.comp = None
            self.comp = Compositor(e.gpu, 128, self.bakes, self.gm.mesh, e.resources)
            self.pipeline = e.color.cache_id
        if self.renderer is None:
            # Share shader programs, but keep viewport display settings independent.
            self.renderer = Renderer(e.gpu)
        self.renderer.scene = self.renderer.program_for(e.color)
        self.renderer.pipeline = e.color

    def texture(self, layers):
        e, ctx = self.engine, self.engine.ctx
        specs = [layer.to_dict() for layer in layers]
        def stable(value):
            if isinstance(value, dict):
                return {k: stable(v) for k, v in value.items() if k not in ("uid", "pid")}
            if isinstance(value, list):
                return [stable(v) for v in value]
            return value
        # Referenced bitmaps can change on disk without changing a layer property.
        maps = [(path, e.resources._key(path, "color"))
                for layer in layers for path in layer.maps.values() if path]
        key = json.dumps((stable(specs), maps, e.color.cache_id), sort_keys=True)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        viewport, scissor = ctx.viewport, ctx.scissor
        previous = ctx.fbo
        texture = fbo = depth = None
        try:
            self._setup()
            # Clone descriptions: compositing may bind anchors or allocate effect state.
            preview_layers = [Layer.from_dict(spec) for spec in specs]
            for layer in preview_layers:
                # Surface anchors belong to the project mesh, not this sphere.
                # Preview the editable material; inspect object coverage in the
                # project viewport and mask preview instead.
                layer.authored = None
            self.comp.composite(preview_layers)
            texture = e.gpu.texture((self.SIZE, self.SIZE), 4, dtype="f1", purpose="material preview")
            depth = ctx.depth_renderbuffer(texture.size)
            fbo = ctx.framebuffer([texture], depth)
            with ctx.scope(framebuffer=fbo, enable_only=moderngl.DEPTH_TEST):
                ctx.scissor = None
                fbo.clear(0, 0, 0, 0, depth=1.0)
                self.renderer.render_sets(self.gm, self.camera, self.camera.proj(1) @ self.camera.view(),
                                          [(None, self.comp, self.bakes)], (0, 0, self.SIZE, self.SIZE),
                                          background=False)
            self.cache[key] = texture
            return texture
        except Exception:
            if texture is not None:
                texture.release()
            raise
        finally:
            if fbo is not None:
                fbo.release()
            if depth is not None:
                depth.release()
            if previous is not None and hasattr(previous.mglo, "use"):
                previous.use()
            elif ctx.screen is not None:
                ctx.screen.use()
            ctx.viewport, ctx.scissor = viewport, scissor

    def finish_frame(self):
        # ImGui holds texture IDs until its draw lists have been submitted.
        while len(self.cache) > self.LIMIT:
            self.cache.popitem(last=False)[1].release()

    def release(self):
        for texture in self.cache.values():
            texture.release()
        self.cache.clear()
        for target in (self.comp, self.bakes, self.gm):
            if target is not None:
                target.release()
        if self.renderer is not None:
            self.renderer.cursor_vao.release()
            self.renderer.cursor_vbo.release()
        self.comp = self.bakes = self.gm = self.renderer = None

