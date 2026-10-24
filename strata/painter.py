"""3D projection brush: each dab rasterises the mesh in UV space and paints texels near the hit point."""
from __future__ import annotations

import moderngl
import numpy as np

from . import shaders as S
from .gpu import GPU, GPUMesh
from .layers import Brush, Layer
from .mathutil import glmat

PAINT_BLEND = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA, moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
ERASE_BLEND = (moderngl.ZERO, moderngl.ONE_MINUS_SRC_ALPHA, moderngl.ZERO, moderngl.ONE_MINUS_SRC_ALPHA)


class Painter:
    def __init__(self, gpu: GPU):
        self.gpu = gpu
        self.prog = gpu.program("brush", S.UV_VS, S.BRUSH_FS)
        self.prog["u_pickPos"] = 0
        self._fbos = {}

    def _fbo(self, lay: Layer, mask: bool):
        key = (lay.uid, mask, id(lay.mask_tex) if mask else id(lay.tex))
        if key not in self._fbos:
            if mask:
                self._fbos[key] = self.gpu.ctx.framebuffer([lay.mask_tex])
            else:
                t = lay.tex
                self._fbos[key] = self.gpu.ctx.framebuffer([t["C"], t["R"], t["M"], t["H"]])
        return self._fbos[key]

    def forget(self, lay: Layer):
        for k in [k for k in self._fbos if k[0] == lay.uid]:
            self._fbos.pop(k).release()

    def dab(self, gm: GPUMesh, lay: Layer, brush: Brush, hit, radius, vp, campos, pick_pos_tex,
            target_mask: bool):
        ctx, p = self.gpu.ctx, self.prog
        res = (lay.mask_tex if target_mask else lay.tex["C"]).size
        fbo = self._fbo(lay, target_mask)
        fbo.use()
        ctx.viewport = (0, 0, res[0], res[1])
        ctx.disable(moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        ctx.enable(moderngl.BLEND)
        ctx.blend_equation = moderngl.FUNC_ADD
        erase = brush.mode == 1
        if target_mask:
            ctx.blend_func = PAINT_BLEND
            p["u_mode"] = 2
            p["u_maskValue"] = 0.0 if erase else float(brush.mask_value)
        else:
            ctx.blend_func = ERASE_BLEND if erase else PAINT_BLEND
            p["u_mode"] = 1 if erase else 0
        p["u_hit"] = tuple(map(float, hit))
        p["u_radius"] = float(radius)
        p["u_hardness"] = float(brush.hardness)
        p["u_flow"] = float(brush.flow)
        p["u_grain"] = float(brush.grain)
        p["u_grainScale"] = float(brush.grain_scale) / max(float(gm.mesh.radius), 1e-3)
        p["u_campos"] = tuple(map(float, campos))
        p["u_vp"].write(glmat(vp))
        p["u_tol"] = float(radius * 0.25 + gm.mesh.radius * 0.004)
        p["u_color"] = tuple(map(float, brush.color))
        p["u_rough"] = float(brush.rough); p["u_metal"] = float(brush.metal); p["u_height"] = float(brush.height)
        p["u_en"] = tuple(int(bool(e)) for e in brush.enabled)
        pick_pos_tex.use(0)
        gm.render(p)
        ctx.disable(moderngl.BLEND)
