"""Brush footprint and sample stroke rendered into an isolated coverage texture."""
import os

import numpy as np

from ..layers import Brush
from ..painter import Stroke, Surface, TOOL_PAINT, View
from ..viewinput import UVMapping


class BrushPreview:
    SIZE = 320
    CROP = 0.32
    SETTINGS = (
        "size_space", "size_px", "size_obj", "size_uv", "alpha", "alpha_invert",
        "hardness", "flow", "spacing", "angle", "follow_path", "grain", "grain_scale",
        "size_jitter", "flow_jitter", "angle_jitter", "pos_jitter", "seed", "stroke_opacity",
        "pressure_size", "pressure_flow", "min_size", "min_flow", "lazy",
    )

    def __init__(self):
        self.texture = None
        self.key = None

    def update(self, engine):
        source = engine.brush
        settings = {name: getattr(source, name) for name in self.SETTINGS}
        try:
            alpha_revision = os.stat(source.alpha).st_mtime_ns if source.alpha else None
        except OSError:
            alpha_revision = None
        key = (settings, alpha_revision)
        if self.key == key:
            return self.texture

        size = (self.SIZE, self.SIZE)
        gpu, ctx = engine.gpu, engine.ctx
        if self.texture is None:
            self.texture = gpu.texture(size, 1, dtype="f1", purpose="brush preview")
            self.texture.swizzle = "RRR1"
        brush = Brush(tool=TOOL_PAINT, **settings)
        diameter = (brush.size_px / self.SIZE, brush.size_obj, brush.size_uv)[brush.size_space]
        radius = float(np.clip(diameter * 0.5, 0.025, 0.065))
        mapping = UVMapping(size)
        normal = np.array([0., 0., 1.])
        view = View(np.eye(4), size, normal, np.array([1., 0., 0.]), gpu.white, None,
                    lambda pos: mapping.units_per_pixel, uv_mapping=mapping)

        def surface(x, y, pressure=1.0):
            pos = np.array([x, y, 0.])
            return Surface(pos, normal, pos[:2], -1, pressure)

        viewport, scissor, target = ctx.viewport, ctx.scissor, ctx.fbo
        stroke = None
        self.key = None
        try:
            ctx.scissor = None
            gpu.fill(self.texture, (0, 0, 0, 0))
            stroke = Stroke(engine.painter, engine.gm, None, brush, view, lambda pos, tri: radius,
                            "mask", self.texture, seed=brush.seed)
            stroke.start(surface(.15, .5))
            stroke.start(surface(.33, .5, .45))
            for t in np.linspace(0., 1., 51)[1:]:
                stroke.feed(surface(.33 + .53 * t, .5 + .055 * np.sin(2 * np.pi * t), .45 + .55 * t))
            stroke.apply()
            self.key = key
        finally:
            if stroke is not None:
                stroke.release()
            if target is not None and hasattr(target.mglo, "use"):
                target.use()
            elif ctx.screen is not None:
                ctx.screen.use()
            ctx.viewport, ctx.scissor = viewport, scissor
        return self.texture

    def release(self, painter):
        if self.texture is not None:
            painter.forget_textures([self.texture])
            self.texture.release()
            self.texture = None
        self.key = None
