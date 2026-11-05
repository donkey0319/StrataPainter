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
from .layers import (Layer, Effect, Projection, N_CH, B_NORMAL, B_PASSTHROUGH, MaskGen,
                     bind_anchor_references)
from .mesh import Mesh
from .resources import Resources
from .channels import CHANNEL_DESCRIPTORS, BY_KEY, ACC_DTYPES, ACC_CLEAR

T_DTYPES = ("f1", "f2", "f1", "f1", "f1")
CONTENT_KINDS = {"hsl": 1, "levels": 2, "invert": 3, "blur": 4, "brightness_contrast": 5, "graph": 6}
MASK_KINDS = {"fill": 1, "generator": 2, "levels": 3, "invert": 4, "color_select": 5, "anchor": 6,
              "mesh_map": 7, "threshold": 8, "bevel": 12}
DILATE_ITERS = 4


class Compositor:
    def __init__(self, gpu: GPU, res: int, bakes: BakeSet, mesh: Mesh, resources: Resources | None = None):
        self.gpu, self.res, self.bakes, self.mesh = gpu, res, bakes, mesh
        self.resources = resources or Resources(gpu)
        from .userchannels import validate_resolution
        validate_resolution(self.resources.user_channels, res)
        self.pipeline = self.resources.pipeline
        self.acc_dtypes = ("f4", "f2", "f4", "f1") if self.pipeline.managed else ACC_DTYPES
        self.t_dtypes = ("f4", "f2", "f4", "f1", "f1") if self.pipeline.managed else T_DTYPES
        ctx = gpu.ctx
        r = (res, res)
        self.acc = [self._tex_set(self.acc_dtypes) for _ in range(2)]
        self.acc_fbo = [ctx.framebuffer(a) for a in self.acc]
        self.user_outputs = {}
        self.semantic_textures = []
        self._user_compositor = None
        self.cur = 0
        self.normal = gpu.texture(r, 4)
        self.nfbo = ctx.framebuffer([self.normal])
        self.T = [self._tex_set(self.t_dtypes)]
        self.T_fbo = [ctx.framebuffer(self.T[0])]
        self.TB = None                                    # blur copies of T, lazily
        self.masks = [gpu.texture(r, 1) for _ in range(2)]
        self.mask_fbo = [ctx.framebuffer([m]) for m in self.masks]
        self.mask_tmp = gpu.texture(r, 1)
        self.mask_preview = gpu.texture(r, 4, dtype="f1")
        self.mpfbo = ctx.framebuffer([self.mask_preview])
        self.anchors = {}                                 # effect pid -> current evaluation capture
        self._anchor_storage = {}                        # reusable GPU storage, never read directly
        self._mask_anchor_storage = {}
        self.anchor_diagnostics = []
        self._anchor_available_before = {}
        self._saves = []                                  # group save sets, one per depth
        self._cache = None                                # accumulator snapshot for partial re-composites
        self._cache_idx = None
        self._luts = {}
        self.stats = {"layers": 0, "passes": 0}
        pipeline = self.pipeline
        class Programs:
            def fs_program(_, name, source):
                return gpu.fs_program(name + ("/managed" if pipeline.managed else ""), pipeline.working_shader(source))
            set = staticmethod(gpu.set)
        g = Programs()
        self.p_content = g.fs_program("content", S.CONTENT_FS)
        self.p_ceffect = g.fs_program("content_effect", S.CONTENT_EFFECT_FS)
        self.p_mbase = g.fs_program("mask_base", S.MASK_BASE_FS)
        self.p_meffect = g.fs_program("mask_effect", S.MASK_EFFECT_FS)
        self.p_blend = g.fs_program("blend", S.BLEND_FS)
        self.p_group = g.fs_program("group", S.GROUP_FS)
        self.p_copy = g.fs_program("copy4", S.COPY4_FS)
        self.p_normal = g.fs_program("nfromh", S.NORMAL_FROM_HEIGHT_FS)
        self.p_preview = g.fs_program("mask_preview", S.MASK_PREVIEW_FS)
        self._set_mesh_uniforms()

    def _set_mesh_uniforms(self):
        # Programs are shared by all compositors, including material thumbnails.
        # Mesh-dependent uniforms must follow the current evaluator, not whichever
        # mesh happened to create or last use the cached shader program.
        mesh, g = self.mesh, self.gpu
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
        self.gpu.ctx.scissor = None

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
        values = list(ACC_CLEAR)
        if self.pipeline.managed:
            values[0] = (*self.pipeline.working(values[0][:3]), values[0][3])
        if hasattr(self, "_scalar_default"):
            values[1] = (.6, 0., self._scalar_default, 1.)
        for t, v in zip(self.acc[i], values):
            self.gpu.fill(t, v)

    # ------------------------------------------------------------------ composite
    def composite(self, layers, normal_strength=1.0, resume_from: int | None = None,
                  cache_at: int | None = None):
        """Evaluate `layers` (bottom first). With resume_from=i and a valid snapshot taken at i on a
        previous call (cache_at=i), layers below i are skipped."""
        self._set_mesh_uniforms()
        ctx = self.gpu.ctx
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        # Accumulator clears happen before _use(). An ImGui/window scissor must
        # not leave channels that no layer writes (especially Normal) uncleared.
        ctx.scissor = None
        self.stats = {"layers": 0, "passes": 0}
        self.anchors.clear()
        self.anchor_diagnostics = bind_anchor_references(layers)
        # Mask previews run after the whole composite. They must retain the same
        # dependency boundary as the layer's original mask evaluation, rather than
        # seeing captures from layers evaluated later in this frame.
        self._anchor_available_before.clear()
        available = set()
        def dependencies(nodes):
            for layer in nodes:
                if not layer.visible or layer.opacity <= 0:
                    continue
                if layer.is_group:
                    dependencies(layer.children)
                self._anchor_available_before.setdefault(id(layer), frozenset(available))
                available.update(e.pid for e in layer.effects + layer.mask_effects
                                 if e.kind in ("anchor", "mask_anchor") and e.enabled and e.params.get("name"))
        dependencies(layers)
        live_ids = {e.pid for root in layers for lay in root.walk() for e in lay.effects
                    if e.kind == "anchor"}
        for pid in list(self._anchor_storage):
            if pid not in live_ids:
                textures, framebuffer = self._anchor_storage.pop(pid)
                framebuffer.release()
                for texture in textures:
                    texture.release()
        live_masks = {e.pid for root in layers for lay in root.walk() for e in lay.mask_effects
                      if e.kind == "mask_anchor"}
        for pid in list(self._mask_anchor_storage):
            if pid not in live_masks:
                texture, framebuffer = self._mask_anchor_storage.pop(pid)
                framebuffer.release()
                texture.release()
        anchored = any(e.kind == "anchor" for root in layers for lay in root.walk()
                       for e in lay.effects + lay.mask_effects) or bool(live_masks)
        if anchored:
            # A partial accumulator snapshot does not include dependency captures.
            resume_from = cache_at = None
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
        if not getattr(self, "_scalar_pass", False):
            self._evaluate_user_channels(layers)

    def _evaluate_user_channels(self, layers):
        from .userchannels import mapped_layers, validate_resolution
        definitions = self.resources.user_channels
        for key in list(self.user_outputs):
            if key not in definitions:
                self.user_outputs.pop(key).release()
        if not definitions:
            return
        validate_resolution(definitions, self.res)
        if self._user_compositor is None:
            self._user_compositor = Compositor(self.gpu, self.res, self.bakes, self.mesh, self.resources)
            self._user_compositor._scalar_pass = True
        scalar = self._user_compositor
        scalar.bakes, scalar.mesh = self.bakes, self.mesh
        scalar.authored_origin = getattr(self, "authored_origin", (0, 0))
        for key, definition in definitions.items():
            mapped, originals = mapped_layers(layers, key, definition["default"])
            scalar._mask = lambda layer, shape=None: self._mask(originals[id(layer)], shape)
            scalar._scalar_default = definition["default"]
            scalar.composite(mapped)
            if key not in self.user_outputs:
                self.user_outputs[key] = self.gpu.texture((self.res, self.res), 1, dtype="f2", purpose="user channel/" + key)
            p = self.gpu.fs_program("user_extract", S.HEADER + "uniform sampler2D u_source; in vec2 v_uv; out float o; void main(){o=texture(u_source,v_uv).b;}")
            fbo = self.gpu.ctx.framebuffer([self.user_outputs[key]])
            try:
                self._use(fbo)
                self.gpu.bind(p, {"u_source": (0, scalar.rmh)})
                self._draw(p)
            finally:
                fbo.release()
        workflow = self.resources.shader_workflow
        if workflow["model"] == "spec_gloss" or workflow["bindings"]:
            self._pack_semantics(workflow)

    def _pack_semantics(self, workflow):
        if not self.semantic_textures:
            self.semantic_textures = [self.gpu.texture((self.res, self.res), 4, dtype="f2", purpose="shader semantics") for _ in range(2)]
        names = ("specular_r", "specular_g", "specular_b", "glossiness", "coat", "coat_roughness")
        defaults = (.04, .04, .04, .5, 0., .1)
        source = S.HEADER + "in vec2 v_uv; layout(location=0) out vec4 a; layout(location=1) out vec4 b;\n"
        source += "\n".join(f"uniform sampler2D t{i}; uniform int h{i};" for i in range(6))
        source += "void main(){" + "".join(f"float v{i}=h{i}==1?texture(t{i},v_uv).r:{value};" for i,value in enumerate(defaults))
        source += "a=clamp(vec4(v0,v1,v2,v3),0.,1.);b=clamp(vec4(v4,v5,0.,1.),0.,1.);}"
        p = self.gpu.fs_program("shader_semantics", source)
        units = {}
        for i, name in enumerate(names):
            texture = self.user_outputs.get(workflow["bindings"].get(name))
            units[f"t{i}"] = (i, texture or self.gpu.black)
            self.gpu.set(p, f"h{i}", int(texture is not None))
        fbo = self.gpu.ctx.framebuffer(self.semantic_textures)
        try:
            self._use(fbo); self.gpu.bind(p, units); self._draw(p)
        finally:
            fbo.release()

    def _snapshot_cache(self, i):
        if self._cache is None:
            s = self._tex_set(self.acc_dtypes)
            self._cache = (s, self.gpu.ctx.framebuffer(s))
        self._copy_set(self.acc[self.cur], self._cache[1])
        self._cache_idx = i

    def invalidate_cache(self):
        self._cache_idx = None
        self.anchors.clear()

    def _finish(self, normal_strength):
        g = self.gpu
        a = self.acc[self.cur]
        for t in a:
            g.dilate(t, self.bakes.cov, DILATE_ITERS)
        self.finish_normal(normal_strength)

    def finish_normal(self, normal_strength, edges=None):
        """Combine authored/baked normals with height, optionally across tile edges."""
        g, a = self.gpu, self.acc[self.cur]
        p = self.p_normal
        self._use(self.nfbo)
        baked = self.bakes.normal_hp
        g.bind(p, {"u_rmh": (0, a[1]), "u_nch": (1, a[3]), "u_baked": (2, baked or g.flat_normal),
                   "u_edges": (3, edges or g.black)})
        g.set(p, "u_hasEdges", int(edges is not None))
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
        if lay.authored is not None or lay.proj.decal:
            from .authored import evaluate
            with evaluate(self,lay) as shape:
                t=self._content(lay,shape)
                t=self._content_effects(lay,t)
                self._blend(lay,t,self._mask(lay,shape))
        else:
            t = self._content(lay)
            t = self._content_effects(lay, t)
            mask = self._mask(lay)
            self._blend(lay, t, mask)

    def _content(self, lay: Layer, shape=None) -> int:
        g, p = self.gpu, self.p_content
        prev = self.acc[self.cur]
        units = {f"u_prev{i}": (7 + i, prev[i]) for i in range(4)}
        units["u_pos"] = (11, self.bakes.pos)
        units["u_nrm"] = (12, self.bakes.nrm)
        units["u_authored"]=(13,shape or g.black)
        g.set(p,"u_ribbon",int(lay.authored is not None and lay.authored["kind"]=="ribbon"))
        has_map = [0] * N_CH
        if lay.kind == "paint" and lay.tex:
            g.set(p, "u_type", 1)
            for channel in CHANNEL_DESCRIPTORS:
                i, k = channel.index, channel.key
                units[f"u_s{i}"] = (i, lay.tex.get(k) or g.black)
        else:
            g.set(p, "u_type", 0)
            for channel in CHANNEL_DESCRIPTORS:
                i, k = channel.index, channel.key
                tex = None
                path = (lay.maps or {}).get(k)
                if path and path.startswith("bake:"):
                    tex = self._bake_map(path[5:])
                elif path:
                    try:
                        tex = self.resources.texture(path, channel.resource_kind)
                    except Exception as e:      # missing file: fall back to the constant
                        print(f"[strata] could not load {path}: {e}")
                has_map[i] = int(tex is not None)
                units[f"u_s{i}"] = (i, tex or g.black)
            self._set_proj(p, lay.proj)
        g.bind(p, units)
        g.set(p, "u_hasMap", tuple(has_map))
        g.set(p, "u_pass", tuple(int(lay.blend_for(i) == B_PASSTHROUGH) for i in range(N_CH)))
        for channel in CHANNEL_DESCRIPTORS:
            value = getattr(lay, channel.attribute)
            if channel.key in ("C", "E"):
                value = self.pipeline.working(value)
            value = tuple(float(c) for c in value) if channel.value_components > 1 else float(value)
            g.set(p, "u_" + channel.attribute, value)
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
        from .uvprep import projection_scale
        g.set(p, "u_projScale", projection_scale(self.mesh, proj))
        g.set(p, "u_projOffset", tuple(float(x) for x in proj.offset))
        g.set(p, "u_projRot", float(np.radians(proj.rotation)))
        g.set(p, "u_projSharp", float(proj.sharpness))
        g.set(p, "u_projAxis", int(proj.axis))
        from .authored import warp_matrix
        from .mathutil import glmat
        g.set(p,"u_hasWarp",int(proj.warp is not None))
        g.set(p,"u_projClip",int(proj.decal))
        if "u_projWarp" in p:p["u_projWarp"].write(glmat(warp_matrix(proj.warp)))

    def _ensure_T1(self):
        if len(self.T) < 2:
            self.T.append(self._tex_set(self.t_dtypes))
            self.T_fbo.append(self.gpu.ctx.framebuffer(self.T[1]))

    def _content_effects(self, lay: Layer, t: int) -> int:
        effects = [e for e in lay.effects if e.enabled and e.kind in CONTENT_KINDS and not e.params.get("user_channel")]
        if not effects:
            return t
        self._ensure_T1()
        g, p = self.gpu, self.p_ceffect
        for e in effects:
            if e.kind == "graph":
                t = self._graph_content(e, t)
                continue
            kind = CONTENT_KINDS[e.kind]
            src = self.T[t]
            units = {f"u_t{i}": (i, tex) for i, tex in enumerate(src)}
            if kind == 4:
                if self.TB is None:
                    self.TB = self._tex_set(self.t_dtypes)
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
            g.set(p, "u_effectBlend", int(e.blend))
            g.set(p, "u_hsl", (float(pr.get("hue", 0)), float(pr.get("saturation", 0)), float(pr.get("lightness", 0))))
            g.set(p, "u_target", int(pr.get("target", 0)))
            g.set(p, "u_lvIn", (float(pr.get("in_lo", 0)), float(pr.get("in_hi", 1)), float(pr.get("gamma", 1))))
            g.set(p, "u_lvOut", (float(pr.get("out_lo", 0)), float(pr.get("out_hi", 1))))
            g.set(p, "u_bc", (float(pr.get("brightness", 0)), float(pr.get("contrast", 0))))
            t = 1 - t
            self._use(self.T_fbo[t])
            self._draw(p)
        return t

    def _graph_content(self, effect, t):
        from .graphs import evaluate
        g, p = self.gpu, self.p_ceffect
        channel = int(effect.params.get("channel", 0))
        if not 0 <= channel < N_CH:
            raise ValueError("Native graph content requires one channel")
        index, component = ((0,-1),(1,0),(1,1),(1,2),(3,-1),(2,-1),(1,3))[channel]
        src = self.T[t]
        with evaluate(g, effect.params["graph"], src[index], component) as result:
            units = {f"u_t{i}": (i, tex) for i, tex in enumerate(src)}
            units.update({f"u_b{i}": (5+i, result if i == 0 else g.black) for i in range(5)})
            g.bind(p, units)
            for key, value in {"u_kind":6,"u_channel":channel,"u_opacity":float(effect.opacity),"u_effectBlend":int(effect.blend)}.items():
                g.set(p,key,value)
            t = 1-t
            self._use(self.T_fbo[t])
            self._draw(p)
        return t

    # ------------------------------------------------------------------ masks
    def _mask(self, lay: Layer, shape=None):
        """Evaluate the mask stack; returns a texture or None (= fully visible)."""
        self._set_mesh_uniforms()
        if not lay.has_mask_stack() and shape is None:
            return None
        if shape is not None and not lay.mask_enabled:
            self.gpu.fill(self.masks[0],(1.,1.,1.,1.))
            m=self._mask_pass(0,11,{"u_map":(1,shape)},lambda p:None)
            return self.masks[m]
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
            if e.kind == "mask_anchor":
                if not e.params.get("capture", 0):
                    self._capture_mask_anchor(e, self.masks[m])
                continue
            m = self._mask_effect(lay, e, m)
        if lay.part_mask is not None:
            m = self._part_filter(lay, m)
        if shape is not None:m=self._mask_pass(m,11,{"u_map":(1,shape)},lambda p:None)
        for e in lay.mask_effects:
            if e.enabled and e.kind == "mask_anchor" and e.params.get("capture", 0) == 1:
                self._capture_mask_anchor(e, self.masks[m])
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
        g.set(p, "u_microNormal", 0)
        g.set(p, "u_microStrength", 1.0)
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
        if kind == "graph":
            from .graphs import evaluate
            with evaluate(g, pr["graph"], self.masks[m], 0) as result:
                return self._mask_pass(m, 9, {"u_map": (1, result)}, lambda p: None, e.blend, e.opacity)
        if kind == "paint":
            def painted(p):
                g.set(p, "u_hasMap", int(e.tex is not None))
                g.set(p, "u_value", float(pr.get("initial", 0)))
                self._set_proj(p, Projection())  # independent paint is always in mesh UV space
            return self._mask_pass(m, 1, {"u_map": (1, e.tex or g.black)}, painted, e.blend, e.opacity)
        if kind == "blur":
            g.blur(self.masks[m], self.mask_tmp, float(pr.get("radius", 4.0)))
            return self._mask_pass(m, 9, {"u_map": (1, self.mask_tmp)}, lambda p: None, e.blend, e.opacity)
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
                g.set(p, "u_microNormal", int(pr.get("micro_normal", False)))
                g.set(p, "u_microStrength", float(pr.get("micro_strength", 1.0)))
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
                g.set(p, "u_comp", 0 if pr.get("source_pid") in self._mask_anchor_storage
                      else self._anchor_comp(int(pr.get("channel", 3))))
            elif kind == "bevel":
                g.set(p, "u_bevelRadius", float(pr.get("radius", 4.0)))
            elif kind == "threshold":
                g.set(p, "u_th", (float(pr.get("level", 0.5)), float(pr.get("softness", 0.02))))

        if kind == "fill" and pr.get("map"):
            try:
                units["u_map"] = (1, self.resources.texture(pr["map"], "gray"))
            except Exception as ex:
                print(f"[strata] could not load {pr['map']}: {ex}")
        elif kind == "anchor" or (kind == "generator" and pr.get("micro_normal")):
            source = pr.get("source_pid")
            allowed = self._anchor_available_before.get(id(lay), ())
            src = self.anchors.get(source) if source in allowed else None
            ch = int(pr.get("channel", 3))
            tex = None
            if src is not None:
                if kind == "generator":
                    tex = src[0][BY_KEY["N"].accumulator_index] if source not in self._mask_anchor_storage else None
                else:
                    channel = CHANNEL_DESCRIPTORS[ch] if 0 <= ch < N_CH else BY_KEY["H"]
                    tex = src[0][channel.accumulator_index]
            units["u_map"] = (1, tex or (g.flat_normal if kind == "generator" else g.black))
        return self._mask_pass(m, k, units, setup, e.blend, e.opacity)

    def _capture_mask_anchor(self, effect, mask):
        entry = self._mask_anchor_storage.get(effect.pid)
        if entry is None:
            texture = self.gpu.texture((self.res, self.res), 1)
            entry = self._mask_anchor_storage[effect.pid] = (texture, self.gpu.ctx.framebuffer([texture]))
        self._use(entry[1])
        self.gpu.bind(self.p_preview, {"u_src": (0, mask)})
        self._draw(self.p_preview)
        self.anchors[effect.pid] = ([entry[0]] * 4, entry[1])

    @staticmethod
    def _anchor_comp(ch: int) -> int:
        channel = CHANNEL_DESCRIPTORS[ch] if 0 <= ch < N_CH else BY_KEY["H"]
        return channel.accumulator_components[0] if channel.value_components == 1 else -1

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
            s = self._tex_set(self.acc_dtypes)
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
                entry = self._anchor_storage.get(e.pid)
                if entry is None:
                    s = self._tex_set(self.acc_dtypes)
                    entry = self._anchor_storage[e.pid] = (s, self.gpu.ctx.framebuffer(s))
                self._copy_set(self.acc[self.cur], entry[1])
                self.anchors[e.pid] = entry

    # ------------------------------------------------------------------ previews / reads
    def render_mask(self, lay: Layer):
        """Final mask of `lay` into mask_preview (white if it has none)."""
        self.gpu.ctx.disable(moderngl.BLEND)
        if lay.authored is not None or lay.proj.decal:
            from .authored import evaluate
            with evaluate(self, lay) as shape:
                m = self._mask(lay, shape)
        else:
            m = self._mask(lay)
        p = self.p_preview
        self._use(self.mpfbo)
        self.gpu.bind(p, {"u_src": (0, m if m is not None else self.gpu.white)})
        self._draw(p)

    def sample(self, uv) -> dict:
        """Composited channel values at a UV coordinate (material picker)."""
        g = self.gpu
        accumulators = [g.read_texel(t, uv) for t in self.acc[self.cur]]
        result = {}
        for channel in CHANNEL_DESCRIPTORS:
            values = accumulators[channel.accumulator_index]
            components = channel.accumulator_components
            result[channel.attribute] = ([float(values[c]) for c in components]
                                         if channel.value_components > 1 else float(values[components[0]]))
        return result

    def channel_textures(self) -> dict:
        a = self.acc[self.cur]
        return {"color": a[0], "rmho": a[1], "emissive": a[2], "normal_channel": a[3], "normal": self.normal}

    def release(self):
        if self._user_compositor is not None:
            self._user_compositor.release()
            self._user_compositor = None
        for texture in self.user_outputs.values():
            texture.release()
        self.user_outputs.clear()
        for texture in self.semantic_textures:
            texture.release()
        self.semantic_textures.clear()
        objs = [self.normal, self.nfbo, self.mask_tmp, self.mask_preview, self.mpfbo]
        objs += self.masks + self.mask_fbo + self.acc_fbo + self.T_fbo
        for s in self.acc + self.T + ([self.TB] if self.TB else []):
            objs += s
        for s, f in self._saves + list(self._anchor_storage.values()) + ([self._cache] if self._cache else []):
            objs += s + [f]
        objs += list(self._luts.values())
        for texture, framebuffer in self._mask_anchor_storage.values():
            objs += [framebuffer, texture]
        for o in objs:
            o.release()
