"""Texture-space bakes: position, normal, curvature, coverage, ambient occlusion."""
from __future__ import annotations

from dataclasses import dataclass

import moderngl
import numpy as np

from . import shaders as S
from .gpu import GPU, GPUMesh
from .mathutil import look_at, ortho, glmat, fibonacci_sphere

PAD = 16  # texels of dilation around UV islands


@dataclass
class BakeSet:
    pos: moderngl.Texture
    nrm: moderngl.Texture
    curv: moderngl.Texture
    ao: moderngl.Texture
    cov: moderngl.Texture
    res: int

    def release(self):
        for t in (self.pos, self.nrm, self.curv, self.ao, self.cov):
            t.release()


class Baker:
    def __init__(self, gpu: GPU):
        self.gpu = gpu

    def bake(self, gm: GPUMesh, res: int, ao_samples: int = 96, ao_res: int = 1024,
             progress=None) -> BakeSet:
        g, ctx = self.gpu, self.gpu.ctx
        pos = g.texture((res, res), 4, dtype="f4")
        nrm = g.texture((res, res), 4)
        curv = g.texture((res, res), 4)
        cov = g.texture((res, res), 1, dtype="f1", filt=False)
        fbo = ctx.framebuffer([pos, nrm, curv, cov])
        fbo.use()
        fbo.clear(0, 0, 0, 0)
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        prog = g.program("bake_geom", S.UV_VS, S.BAKE_GEOM_FS)
        gm.render(prog)
        fbo.release()

        ao = self._bake_ao(gm, pos, nrm, res, ao_samples, ao_res, progress)
        for t in (nrm, curv, ao, pos):
            g.dilate(t, cov, PAD)
        return BakeSet(pos, nrm, curv, ao, cov, res)

    def _bake_ao(self, gm, pos, nrm, res, n, smap_res, progress):
        g, ctx = self.gpu, self.gpu.ctx
        mesh = gm.mesh
        c, r = mesh.center, mesh.radius * 1.02
        depth = ctx.depth_texture((smap_res, smap_res))
        depth.filter = (moderngl.NEAREST, moderngl.NEAREST)
        depth.compare_func = ""
        dfbo = ctx.framebuffer(depth_attachment=depth)
        acc = g.texture((res, res), 4, dtype="f4")
        afbo = ctx.framebuffer([acc])
        afbo.clear(0, 0, 0, 0)
        dprog = g.program("depth", S.DEPTH_VS, S.DEPTH_FS)
        aprog = g.fs_program("ao_accum", S.AO_ACCUM_FS)
        aprog["u_pos"], aprog["u_nrm"], aprog["u_depth"] = 0, 1, 2
        near, far = 0.01, 4 * r
        bias = r * 0.006
        aprog["u_bias"] = bias
        aprog["u_dbias"] = bias / (far - near)
        for i, d in enumerate(fibonacci_sphere(n)):
            vp = ortho(-r, r, -r, r, near, far) @ look_at(c + d * 2 * r, c)
            dfbo.use()
            dfbo.clear(depth=1.0)
            ctx.disable(moderngl.BLEND | moderngl.CULL_FACE)
            ctx.enable(moderngl.DEPTH_TEST)
            dprog["u_vp"].write(glmat(vp))
            gm.render(dprog)
            afbo.use()
            ctx.disable(moderngl.DEPTH_TEST)
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            ctx.blend_equation = moderngl.FUNC_ADD
            pos.use(0); nrm.use(1); depth.use(2)
            aprog["u_vp"].write(glmat(vp))
            aprog["u_dir"] = tuple(float(x) for x in d)
            g.draw_quad(aprog)
            if progress:
                progress((i + 1) / n)
        ctx.disable(moderngl.BLEND)
        ao = g.texture((res, res), 4)
        rfbo = ctx.framebuffer([ao])
        rfbo.use()
        rprog = g.fs_program("ao_resolve", S.AO_RESOLVE_FS)
        acc.use(0)
        rprog["u_acc"] = 0
        g.draw_quad(rprog)
        for o in (rfbo, afbo, dfbo, acc, depth):
            o.release()
        return ao
