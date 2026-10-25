"""Evaluates a layer stack into final channel textures, entirely in UV space on the GPU.

Per layer:  content pass (T0-T4)  ->  content effects  ->  mask stack  ->  blend pass into the
accumulator (A0-A3, ping-pong). Groups save the accumulator, composite their children on top, then
merge the result back over the saved state through the group's own mask, opacity and blend modes.
Anchor effects copy the accumulator after their layer so masks higher up can read it.
"""
from __future__ import annotations

import numpy as np
import moderngl

from . import shaders as S
from .baker import BakeSet
from .gpu import GPU
from .layers import (Layer, Effect, CH_KEYS, N_CH, B_NORMAL, B_PASSTHROUGH, MaskGen)
from .mesh import Mesh
from .resources import Resources

ACC_DTYPES = ("f1", "f2", "f1", "f1")        # colour, rough/metal/height/opacity, emissive, normal
T_DTYPES = ("f1", "f2", "f1", "f1", "f1")
ACC_CLEAR = ((0.5, 0.5, 0.5, 1.0), (0.6, 0.0, 0.5, 1.0), (0.0, 0.0, 0.0, 1.0), (0.5, 0.5, 1.0, 1.0))
CONTENT_KINDS = {"hsl": 1, "levels": 2, "invert": 3, "blur": 4, "brightness_contrast": 5}
MASK_KINDS = {"fill": 1, "generator": 2, "levels": 3, "invert": 4, "color_select": 5, "anchor": 6,
              "mesh_map": 7, "threshold": 8}
DILATE_ITERS = 4


class Compositor:
    def __init__(self, gpu: GPU, res: int, bakes: BakeSet, mesh: Mesh, resources: Resources | None = None):
        self.gpu, self.res, self.bakes, self.mesh = gpu, res, bakes, mesh
        self.resources = resources or Resources(gpu)
        ctx = gpu.ctx
        r = (res, res)
        self.acc = [self._tex_set(ACC_DTYPES) for _ in range(2)]
        self.acc_fbo = [ctx.framebuffer(a) for a in self.acc]
        self.cur = 0
        self.normal = gpu.texture(r, 4)
        self.nfbo = ctx.framebuffer([self.normal])
        self.T = [self._tex_set(T_DTYPES)]
        self.T_fbo = [ctx.framebuffer(self.T[0])]
        self.TB = None                                    # blur copies of T, lazily
        self.masks = [gpu.texture(r, 1) for _ in range(2)]
        self.mask_fbo = [ctx.framebuffer([m]) for m in self.masks]
        self.mask_tmp = gpu.texture(r, 1)
        self.mask_preview = gpu.texture(r, 4, dtype="f1")
        self.mpfbo = ctx.framebuffer([self.mask_preview])
        self.anchors = {}                                 # name -> accumulator copy
        self._saves = []                                  # group save sets, one per depth
        self._cache = None                                # accumulator snapshot for partial re-composites
        self._cache_idx = None
        self._luts = {}
        self.stats = {"layers": 0, "passes": 0}
        g = gpu
        self.p_content = g.fs_program("content", S.CONTENT_FS)
        self.p_ceffect = g.fs_program("content_effect", S.CONTENT_EFFECT_FS)
        self.p_mbase = g.fs_program("mask_base", S.MASK_BASE_FS)
        self.p_meffect = g.fs_program("mask_effect", S.MASK_EFFECT_FS)
        self.p_blend = g.fs_program("blend", S.BLEND_FS)
        self.p_group = g.fs_program("group", S.GROUP_FS)
        self.p_copy = g.fs_program("copy4", S.COPY4_FS)
        self.p_normal = g.fs_program("nfromh", S.NORMAL_FROM_HEIGHT_FS)
        self.p_preview = g.fs_program("mask_preview", S.MASK_PREVIEW_FS)
        lo, hi = mesh.bounds
        for p in (self.p_content, self.p_mbase, self.p_meffect):
            g.set(p, "u_meshSize", float(mesh.radius * 2))
            g.set(p, "u_bmin", tuple(map(float, lo)))
            g.set(p, "u_bmax", tuple(map(float, hi)))
            g.set(p, "u_center", tuple(map(float, mesh.center)))

    # ------------------------------------------------------------------ resources
    def _tex_set(self, dtypes):
        return [self.gpu.texture((self.res, self.res), 4, dtype=d) for d in dtypes]

    @property
    def color(self):
        return self.acc[self.cur][0]

    @property
    def rmh(self):
        """roughness, metallic, height, opacity"""
        return self.acc[self.cur][1]

    @property
    def emissive(self):
        return self.acc[self.cur][2]

    @property
    def normal_channel(self):
        return self.acc[self.cur][3]

    def _use(self, fbo):
        fbo.use()
        self.gpu.ctx.viewport = (0, 0, self.res, self.res)

    def _draw(self, prog):
        self.gpu.draw_quad(prog)
        self.stats["passes"] += 1

    def _bakes_units(self, start=16):
        b, w = self.bakes, self.gpu.white
        return {"u_pos": (start, b.pos), "u_nrm": (start + 1, b.nrm), "u_ao": (start + 2, b.ao),
                "u_curv": (start + 3, b.curv), "u_thick": (start + 4, b.thick or w),
                "u_id": (start + 5, b.id or w), "u_part": (start + 6, b.part or self.gpu.black),
                "u_hbake": (start + 7, b.height_hp or self.gpu.flat_normal)}

    def _copy_set(self, src, dst_fbo):
        p = self.p_copy
        self._use(dst_fbo)
        self.gpu.bind(p, {f"u_s{i}": (i, t) for i, t in enumerate(src)})
        self._draw(p)

    def _clear_acc(self, i):
        for t, v in zip(self.acc[i], ACC_CLEAR):
            self.gpu.fill(t, v)

    # ------------------------------------------------------------------ composite
    def composite(self, layers, normal_strength=1.0, resume_from: int | None = None,
                  cache_at: int | None = None):
        """Evaluate `layers` (bottom first). With resume_from=i and a valid snapshot taken at i on a
        previous call (cache_at=i), layers below i are skipped."""
        ctx = self.gpu.ctx
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        self.stats = {"layers": 0, "passes": 0}
        start, resumed = 0, False
        if resume_from is not None and self._cache is not None and self._cache_idx == resume_from \
                and resume_from <= len(layers):
            self._copy_set(self._cache[0], self.acc_fbo[self.cur])
            start, resumed = resume_from, True
        else:
            self._clear_acc(self.cur)
            self._cache_idx = None
        for i in range(start, len(layers)):
            if cache_at is not None and i == cache_at and not resumed:
                self._snapshot_cache(i)
            self._item(layers[i], 0)
        if cache_at is not None and cache_at >= len(layers) and not resumed:
            self._snapshot_cache(cache_at)
        self._finish(normal_strength)

    def _snapshot_cache(self, i):
        if self._cache is None:
            s = self._tex_set(ACC_DTYPES)
            self._cache = (s, self.gpu.ctx.framebuffer(s))
        self._copy_set(self.acc[self.cur], self._cache[1])
        self._cache_idx = i

    def invalidate_cache(self):
        self._cache_idx = None

    def _finish(self, normal_strength):
        g = self.gpu
        a = self.acc[self.cur]
        for t in a:
            g.dilate(t, self.bakes.cov, DILATE_ITERS)
        p = self.p_normal
        self._use(self.nfbo)
        baked = self.bakes.normal_hp
        g.bind(p, {"u_rmh": (0, a[1]), "u_nch": (1, a[3]), "u_baked": (2, baked or g.flat_normal)})
        g.set(p, "u_hasNch", 1)
        g.set(p, "u_hasBaked", int(baked is not None))
        g.set(p, "u_strength", float(normal_strength))
        self._draw(p)

    def _item(self, lay: Layer, depth: int):
        if not lay.visible or lay.opacity <= 0.0:
            return
        if lay.is_group:
            self._group(lay, depth)
        else:
            self._layer(lay)
        self._capture_anchors(lay)

    # ------------------------------------------------------------------ one layer
    def _layer(self, lay: Layer):
        self.stats["layers"] += 1
        t = self._content(lay)
        t = self._content_effects(lay, t)
        mask = self._mask(lay)
        self._blend(lay, t, mask)

    def _content(self, lay: Layer) -> int:
        g, p = self.gpu, self.p_content
        prev = self.acc[self.cur]
        units = {f"u_prev{i}": (7 + i, prev[i]) for i in range(4)}
        units["u_pos"] = (11, self.bakes.pos)
        units["u_nrm"] = (12, self.bakes.nrm)
        has_map = [0] * N_CH
        if lay.kind == "paint" and lay.tex:
            g.set(p, "u_type", 1)
            for i, k in enumerate(CH_KEYS):
                units[f"u_s{i}"] = (i, lay.tex.get(k) or g.black)
        else:
            g.set(p, "u_type", 0)
            for i, k in enumerate(CH_KEYS):
                tex = None
                path = (lay.maps or {}).get(k)
                if path and path.startswith("bake:"):
                    tex = self._bake_map(path[5:])
                elif path:
                    try:
                        tex = self.resources.texture(path, "color" if k in ("C", "E") else "data")
                    except Exception as e:      # missing file: fall back to the constant
                        print(f"[strata] could not load {path}: {e}")
                has_map[i] = int(tex is not None)
                units[f"u_s{i}"] = (i, tex or g.black)
            self._set_proj(p, lay.proj)
        g.bind(p, units)
        g.set(p, "u_hasMap", tuple(has_map))
        g.set(p, "u_pass", tuple(int(lay.blend_for(i) == B_PASSTHROUGH) for i in range(N_CH)))
        g.set(p, "u_color", tuple(float(c) for c in lay.color))
        g.set(p, "u_normal", tuple(float(c) for c in lay.normal))
        g.set(p, "u_emissive", tuple(float(c) for c in lay.emissive))
        g.set(p, "u_rough", float(lay.rough)); g.set(p, "u_metal", float(lay.metal))
        g.set(p, "u_height", float(lay.height)); g.set(p, "u_opac", float(lay.opac))
        g.set(p, "u_var", float(lay.variation)); g.set(p, "u_bump", float(lay.bump))
        g.set(p, "u_varScale", float(lay.var_scale))
        s = lay.seed
        g.set(p, "u_seed", (s * 3.1, s * 7.7, s * 1.3))
        self._use(self.T_fbo[0])
        self._draw(p)
        return 0

    def _bake_map(self, name):
        """A mesh map of this texture set used as layer content ('bake:curvature' etc.)."""
        tex = self.bakes.maps().get(name) if self.bakes is not None else None
        if tex is not None and tex.components == 1:
            tex.swizzle = "RRR1"
        return tex

    def _set_proj(self, p, proj):
        g = self.gpu
        g.set(p, "u_projMode", int(proj.mode))
        g.set(p, "u_projScale", tuple(float(x) for x in proj.scale))
        g.set(p, "u_projOffset", tuple(float(x) for x in proj.offset))
        g.set(p, "u_projRot", float(np.radians(proj.rotation)))
        g.set(p, "u_projSharp", float(proj.sharpness))
        g.set(p, "u_projAxis", int(proj.axis))

    def _ensure_T1(self):
        if len(self.T) < 2:
            self.T.append(self._tex_set(T_DTYPES))
            self.T_fbo.append(self.gpu.ctx.framebuffer(self.T[1]))

    def _content_effects(self, lay: Layer, t: int) -> int:
        effects = [e for e in lay.effects if e.enabled and e.kind in CONTENT_KINDS]
        if not effects:
            return t
        self._ensure_T1()
        g, p = self.gpu, self.p_ceffect
        for e in effects:
            kind = CONTENT_KINDS[e.kind]
            src = self.T[t]
            units = {f"u_t{i}": (i, tex) for i, tex in enumerate(src)}
            if kind == 4:
                if self.TB is None:
                    self.TB = self._tex_set(T_DTYPES)
                for a, b in zip(src, self.TB):
                    g.blur(a, b, float(e.params.get("radius", 4.0)))
                units.update({f"u_b{i}": (5 + i, tex) for i, tex in enumerate(self.TB)})
            else:
                units.update({f"u_b{i}": (5 + i, g.black) for i in range(5)})
            g.bind(p, units)
            pr = e.params
            g.set(p, "u_kind", kind)
            g.set(p, "u_channel", int(pr.get("channel", -1 if kind == 4 else 0)))
            g.set(p, "u_opacity", float(e.opacity))
            g.set(p, "u_hsl", (float(pr.get("hue", 0)), float(pr.get("saturation", 0)), float(pr.get("lightness", 0))))
            g.set(p, "u_target", int(pr.get("target", 0)))
            g.set(p, "u_lvIn", (float(pr.get("in_lo", 0)), float(pr.get("in_hi", 1)), float(pr.get("gamma", 1))))
            g.set(p, "u_lvOut", (float(pr.get("out_lo", 0)), float(pr.get("out_hi", 1))))
            g.set(p, "u_bc", (float(pr.get("brightness", 0)), float(pr.get("contrast", 0))))
            t = 1 - t
            self._use(self.T_fbo[t])
            self._draw(p)
        return t

    # ------------------------------------------------------------------ masks
    def _mask(self, lay: Layer):
        """Evaluate the mask stack; returns a texture or None (= fully visible)."""
        if not lay.has_mask_stack():
            return None
        g = self.gpu
        p = self.p_mbase
        units = self._bakes_units(1)
        has_paint = lay.has_mask and lay.mask_tex is not None
        units["u_maskTex"] = (0, lay.mask_tex if has_paint else g.white)
        g.bind(p, units)
        g.set(p, "u_hasMask", int(has_paint))
        self._set_gen(p, lay.gen, lay.seed)
        m = 0
        self._use(self.mask_fbo[m])
        self._draw(p)
        for e in lay.mask_effects:
            if not e.enabled:
                continue
            m = self._mask_effect(lay, e, m)
        if lay.part_mask is not None:
            m = self._part_filter(lay, m)
        return self.masks[m]

    def _set_gen(self, p, gen: MaskGen, seed: float):
        g = self.gpu
        g.set(p, "u_gKind", int(gen.kind))
        g.set(p, "u_gLevel", float(gen.level))
        g.set(p, "u_gSoft", float(gen.softness))
        g.set(p, "u_gNoiseAmt", float(gen.noise_amount))
        g.set(p, "u_gNoiseScale", float(gen.noise_scale))
        g.set(p, "u_gInvert", int(bool(gen.invert)))
        g.set(p, "u_gAxis", int(gen.axis))
        g.set(p, "u_gAz", float(gen.azimuth))
        g.set(p, "u_gEl", float(gen.elevation))
        s = seed + gen.seed
        g.set(p, "u_gSeed", (s * 3.1, s * 7.7, s * 1.3))

    def _mask_pass(self, m, kind, units, setup, blend=0, opacity=1.0):
        g, p = self.gpu, self.p_meffect
        u = self._bakes_units(3)
        u["u_prev"] = (0, self.masks[m])
        u.setdefault("u_map", (1, g.black))
        u.setdefault("u_partLUT", (2, g.black))
        u.update(units)
        g.bind(p, u)
        g.set(p, "u_kind", kind)
        g.set(p, "u_blend", int(blend))
        g.set(p, "u_opacity", float(opacity))
        g.set(p, "u_hasMap", 0)
        g.set(p, "u_lvIn", (0.0, 1.0, 1.0))
        g.set(p, "u_lvOut", (0.0, 1.0))
        setup(p)
        n = 1 - m
        self._use(self.mask_fbo[n])
        self._draw(p)
        return n

    def _mask_effect(self, lay: Layer, e: Effect, m: int) -> int:
        g = self.gpu
        pr = e.params
        kind = e.kind
        if kind == "blur":
            g.blur(self.masks[m], self.mask_tmp, float(pr.get("radius", 4.0)))
            return self._mask_pass(m, 9, {"u_map": (1, self.mask_tmp)}, lambda p: None, 0, e.opacity)
        if kind not in MASK_KINDS:
            return m
        k = MASK_KINDS[kind]
        units = {}

        def setup(p):
            if kind == "fill":
                g.set(p, "u_value", float(pr.get("value", 1.0)))
                g.set(p, "u_hasMap", int(units.get("u_map") is not None and pr.get("map") is not None))
                self._set_proj(p, pr.get("proj") or lay.proj)
            elif kind == "generator":
                self._set_gen(p, pr["gen"], lay.seed)
            elif kind in ("levels", "mesh_map"):
                g.set(p, "u_lvIn", (float(pr.get("in_lo", 0)), float(pr.get("in_hi", 1)), float(pr.get("gamma", 1))))
                g.set(p, "u_lvOut", (float(pr.get("out_lo", 0)), float(pr.get("out_hi", 1))))
                g.set(p, "u_meshMap", int(pr.get("map", 0)))
            elif kind == "color_select":
                cols = [tuple(float(c) for c in col[:3]) for col in pr.get("colors", [])][:8]
                arr = np.zeros((8, 3), np.float32)
                if cols:
                    arr[:len(cols)] = cols
                if "u_colors" in p:
                    p["u_colors"].write(arr.tobytes())
                g.set(p, "u_nColors", len(cols))
                g.set(p, "u_tol", float(pr.get("tolerance", 0.1)))
                g.set(p, "u_hard", float(pr.get("hardness", 0.8)))
            elif kind == "anchor":
                g.set(p, "u_comp", self._anchor_comp(int(pr.get("channel", 3))))
            elif kind == "threshold":
                g.set(p, "u_th", (float(pr.get("level", 0.5)), float(pr.get("softness", 0.02))))

        if kind == "fill" and pr.get("map"):
            try:
                units["u_map"] = (1, self.resources.texture(pr["map"], "gray"))
            except Exception as ex:
                print(f"[strata] could not load {pr['map']}: {ex}")
        elif kind == "anchor":
            src = self.anchors.get(pr.get("source") or pr.get("name"))
            ch = int(pr.get("channel", 3))
            tex = None
            if src is not None:
                tex = src[0][{0: 0, 5: 2, 4: 3}.get(ch, 1)]
            units["u_map"] = (1, tex or g.black)
        return self._mask_pass(m, k, units, setup, e.blend, e.opacity)

    @staticmethod
    def _anchor_comp(ch: int) -> int:
        return {0: -1, 1: 0, 2: 1, 3: 2, 4: -1, 5: -1, 6: 3}.get(ch, 2)

    def _part_filter(self, lay: Layer, m: int) -> int:
        key = tuple(sorted(int(i) for i in lay.part_mask))
        lut = self._luts.get(key)
        if lut is None:
            vals = np.zeros(1024, np.float32)
            for i in key:
                if 0 <= i < 1024:
                    vals[i] = 1.0
            lut = self._luts[key] = self.resources.lut(vals)
        return self._mask_pass(m, 10, {"u_partLUT": (2, lut)}, lambda p: None)

    # ------------------------------------------------------------------ blending
    def _channel_ops(self, lay: Layer):
        modes = [lay.blend_for(i) for i in range(N_CH)]
        modes = [B_NORMAL if m == B_PASSTHROUGH else m for m in modes]
        ops = [float(lay.opacity * lay.chan_opacity[i] * (1.0 if lay.enabled[i] else 0.0)) for i in range(N_CH)]
        return modes, ops

    def _blend(self, lay: Layer, t: int, mask):
        g, p = self.gpu, self.p_blend
        prev = self.acc[self.cur]
        units = {f"u_prev{i}": (i, prev[i]) for i in range(4)}
        units.update({f"u_t{i}": (4 + i, tex) for i, tex in enumerate(self.T[t])})
        units["u_mask"] = (9, mask if mask is not None else g.white)
        g.bind(p, units)
        modes, ops = self._channel_ops(lay)
        g.set(p, "u_mode", tuple(modes))
        g.set(p, "u_chOp", tuple(ops))
        nxt = 1 - self.cur
        self._use(self.acc_fbo[nxt])
        self._draw(p)
        self.cur = nxt

    # ------------------------------------------------------------------ groups
    def _save_set(self, depth):
        while len(self._saves) <= depth:
            s = self._tex_set(ACC_DTYPES)
            self._saves.append((s, self.gpu.ctx.framebuffer(s)))
        return self._saves[depth]

    def _group(self, grp: Layer, depth: int):
        save, sfbo = self._save_set(depth)
        self._copy_set(self.acc[self.cur], sfbo)
        for child in grp.children:
            self._item(child, depth + 1)
        mask = self._mask(grp)
        modes, ops = self._channel_ops(grp)
        if mask is None and all(m == B_NORMAL for m in modes) and all(o == 1.0 for o in ops):
            return                                 # plain folder: nothing to merge
        g, p = self.gpu, self.p_group
        units = {f"u_save{i}": (i, save[i]) for i in range(4)}
        units.update({f"u_cur{i}": (4 + i, tex) for i, tex in enumerate(self.acc[self.cur])})
        units["u_mask"] = (8, mask if mask is not None else g.white)
        g.bind(p, units)
        g.set(p, "u_mode", tuple(modes))
        g.set(p, "u_chOp", tuple(ops))
        nxt = 1 - self.cur
        self._use(self.acc_fbo[nxt])
        self._draw(p)
        self.cur = nxt

    def _capture_anchors(self, lay: Layer):
        for e in lay.effects:
            if e.kind == "anchor" and e.enabled and e.params.get("name"):
                name = e.params["name"]
                entry = self.anchors.get(name)
                if entry is None:
                    s = self._tex_set(ACC_DTYPES)
                    entry = self.anchors[name] = (s, self.gpu.ctx.framebuffer(s))
                self._copy_set(self.acc[self.cur], entry[1])

    # ------------------------------------------------------------------ previews / reads
    def render_mask(self, lay: Layer):
        """Final mask of `lay` into mask_preview (white if it has none)."""
        self.gpu.ctx.disable(moderngl.BLEND)
        m = self._mask(lay)
        p = self.p_preview
        self._use(self.mpfbo)
        self.gpu.bind(p, {"u_src": (0, m if m is not None else self.gpu.white)})
        self._draw(p)

    def sample(self, uv) -> dict:
        """Composited channel values at a UV coordinate (material picker)."""
        g = self.gpu
        a0, a1, a2, a3 = (g.read_texel(t, uv) for t in self.acc[self.cur])
        return {"color": a0[:3].tolist(), "rough": float(a1[0]), "metal": float(a1[1]),
                "height": float(a1[2]), "opac": float(a1[3]), "emissive": a2[:3].tolist(),
                "normal": a3[:3].tolist()}

    def channel_textures(self) -> dict:
        a = self.acc[self.cur]
        return {"color": a[0], "rmho": a[1], "emissive": a[2], "normal_channel": a[3], "normal": self.normal}

    def release(self):
        objs = [self.normal, self.nfbo, self.mask_tmp, self.mask_preview, self.mpfbo]
        objs += self.masks + self.mask_fbo + self.acc_fbo + self.T_fbo
        for s in self.acc + self.T + ([self.TB] if self.TB else []):
            objs += s
        for s, f in self._saves + list(self.anchors.values()) + ([self._cache] if self._cache else []):
            objs += s + [f]
        objs += list(self._luts.values())
        for o in objs:
            o.release()
