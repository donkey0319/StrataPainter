"""Evaluates the layer stack into final channel textures, entirely in UV space on the GPU."""
from __future__ import annotations

import moderngl

from . import shaders as S
from .baker import BakeSet
from .gpu import GPU
from .layers import Layer
from .mesh import Mesh

DEFAULT_C = (0.5, 0.5, 0.5, 1.0)
DEFAULT_R = (0.6, 0.0, 0.5, 1.0)   # rough, metal, height


class Compositor:
    def __init__(self, gpu: GPU, res: int, bakes: BakeSet, mesh: Mesh):
        self.gpu, self.res, self.bakes, self.mesh = gpu, res, bakes, mesh
        g = gpu
        self.accC = [g.texture((res, res), 4) for _ in range(2)]
        self.accR = [g.texture((res, res), 4) for _ in range(2)]
        self.fbos = [g.ctx.framebuffer([self.accC[i], self.accR[i]]) for i in range(2)]
        self.normal = g.texture((res, res), 4)
        self.nfbo = g.ctx.framebuffer([self.normal])
        self.mask_preview = g.texture((res, res), 4)
        self._mask_scratch = g.texture((res, res), 4)
        self.mfbo = g.ctx.framebuffer([self.mask_preview, self._mask_scratch])
        self.cur = 0
        self.prog = g.fs_program("composite", S.COMPOSITE_FS)
        self.nprog = g.fs_program("nfromh", S.NORMAL_FROM_HEIGHT_FS)
        names = ["u_prevC", "u_prevR", "u_pC", "u_pR", "u_pM", "u_pH", "u_mask",
                 "u_pos", "u_nrm", "u_ao", "u_curv"]
        for i, n in enumerate(names):
            if n in self.prog:
                self.prog[n] = i
        lo, hi = mesh.bounds
        self._set("u_meshSize", float(mesh.radius * 2))
        self._set("u_bmin", tuple(map(float, lo)))
        self._set("u_bmax", tuple(map(float, hi)))

    @property
    def color(self):
        return self.accC[self.cur]

    @property
    def rmh(self):
        return self.accR[self.cur]

    def _set(self, name, value):
        if name in self.prog:
            self.prog[name] = value

    def _bind_layer(self, lay: Layer, mask_only=False):
        g, b = self.gpu, self.bakes
        p = self._set
        p("u_type", 0 if lay.kind == "fill" else 1)
        p("u_color", tuple(float(c) for c in lay.color))
        p("u_rough", float(lay.rough)); p("u_metal", float(lay.metal)); p("u_height", float(lay.height))
        p("u_en", tuple(int(bool(e)) for e in lay.enabled))
        p("u_opacity", float(lay.opacity))
        p("u_blend", int(lay.blend)); p("u_hblend", int(lay.hblend))
        p("u_var", float(lay.variation)); p("u_bump", float(lay.bump)); p("u_varScale", float(lay.var_scale))
        has_mask = lay.has_mask and lay.mask_tex is not None
        p("u_hasMask", int(has_mask))
        p("u_gen", int(lay.gen.kind)); p("u_level", float(lay.gen.level)); p("u_soft", float(lay.gen.softness))
        p("u_noiseAmt", float(lay.gen.noise_amount)); p("u_noiseScale", float(lay.gen.noise_scale))
        p("u_invert", int(lay.gen.invert))
        s = lay.seed
        p("u_seed", (s * 3.1, s * 7.7, s * 1.3))
        p("u_maskOnly", int(mask_only))
        if lay.kind == "paint" and lay.tex:
            for i, k in enumerate("CRMH"):
                lay.tex[k].use(2 + i)
        else:
            for i in range(4):
                g.black.use(2 + i)
        (lay.mask_tex if has_mask else g.white).use(6)
        b.pos.use(7); b.nrm.use(8); b.ao.use(9); b.curv.use(10)

    def composite(self, layers, normal_strength=1.0):
        ctx = self.gpu.ctx
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        cur = 0
        self.fbos[cur].use()
        self.fbos[cur].clear(*DEFAULT_C)
        # second attachment needs its own clear value
        self.gpu.fill(self.accR[cur], DEFAULT_R)
        for lay in layers:
            if not lay.visible or lay.opacity <= 0.0:
                continue
            nxt = 1 - cur
            self.fbos[nxt].use()
            self.accC[cur].use(0); self.accR[cur].use(1)
            self._bind_layer(lay)
            self.gpu.draw_quad(self.prog)
            cur = nxt
        self.cur = cur
        self.gpu.dilate(self.accC[cur], self.bakes.cov, 4)
        self.gpu.dilate(self.accR[cur], self.bakes.cov, 4)
        self.nfbo.use()
        self.accR[cur].use(0)
        self.nprog["u_rmh"] = 0
        self.nprog["u_strength"] = float(normal_strength)
        self.gpu.draw_quad(self.nprog)

    def render_mask(self, lay: Layer):
        self.gpu.ctx.disable(moderngl.BLEND)
        self.mfbo.use()
        self.accC[self.cur].use(0); self.accR[self.cur].use(1)
        self._bind_layer(lay, mask_only=True)
        self.gpu.draw_quad(self.prog)

    def release(self):
        for o in self.accC + self.accR + self.fbos + [self.normal, self.nfbo, self.mask_preview, self._mask_scratch, self.mfbo]:
            o.release()
