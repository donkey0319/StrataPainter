"""2D (UV-space) view of the texture set, like Painter's 2D viewport. Shows the same channel as the
3D view's display mode; zoom with the wheel, pan with middle drag, paint with left drag.
"""
from __future__ import annotations

import moderngl
import numpy as np

from .. import shaders as S
from ..viewinput import UVMapping

UV_FS = S.HEADER + S.ALBEDO_VALIDATION + """
uniform sampler2D u_col; uniform sampler2D u_rmh; uniform sampler2D u_nrm;
uniform sampler2D u_mask; uniform sampler2D u_ao; uniform sampler2D u_curv; uniform sampler2D u_cov;
uniform sampler2D u_extra;
uniform sampler2D u_tangent, u_worldNormal;
uniform vec3 u_bmin, u_bmax;
uniform int u_materialModel, u_hasCoat;
uniform int u_mode; uniform vec2 u_scale; uniform vec2 u_center; uniform vec2 u_px;
uniform mat2 u_uvAxes;
in vec2 v_uv; out vec4 o;
void main() {
    vec2 uv = u_uvAxes * ((v_uv - 0.5) * u_scale) + u_center;
    vec2 cell = floor(v_uv / u_px / 12.0);
    vec3 bg = vec3(mod(cell.x + cell.y, 2.0) < 1.0 ? 0.085 : 0.11);
    if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) { o = vec4(bg * 0.8, 1.0); return; }
    vec3 c;
    vec4 rmh = texture(u_rmh, uv);
    if (u_mode == 2) c = vec3(rmh.r);
    else if (u_mode == 3) c = vec3(rmh.g);
    else if (u_mode == 4) c = vec3(rmh.b);
    else if (u_mode == 5) c = texture(u_nrm, uv).rgb;
    else if (u_mode == 6) c = vec3(texture(u_mask, uv).r);
    else if (u_mode == 7) c = vec3(texture(u_ao, uv).r);
    else if (u_mode == 8) c = vec3(texture(u_curv, uv).r);
    else if (u_mode == 9) c = vec3(mod(floor(uv.x * 16.0) + floor(uv.y * 16.0), 2.0) * 0.4 + 0.2);
    else if (u_mode == 10) c = texture(u_extra, uv).rgb;
    else if (u_mode == 11) c = vec3(rmh.a);
    else if (u_mode == 12) c = vec3(texture(u_extra, uv).r);
    else if (u_mode == 13) c = texture(u_extra, uv).rgb;
    else if (u_mode == 14) c = normalize(texture(u_extra, uv).xyz) * 0.5 + 0.5;
    else if (u_mode == 15) c = (texture(u_extra, uv).xyz - u_bmin) / max(u_bmax - u_bmin, vec3(1e-5));
    else if (u_mode == 16) c = texture(u_extra, uv).rgb;
    else if (u_mode == 17 || u_mode == 19) c = vec3(texture(u_extra, uv).r);
    else if (u_mode == 20) c = u_materialModel==1 ? texture(u_extra, uv).rgb : mix(vec3(.04),pow(texture(u_col,uv).rgb,vec3(2.2)),rmh.g);
    else if (u_mode == 21) c = vec3(u_materialModel==1 ? clamp(1.0-texture(u_extra, uv).a,.04,1.0) : clamp(rmh.r,.04,1.0));
    else if (u_mode == 22) c = u_hasCoat==1 ? vec3(texture(u_extra, uv).rg,0.0) : vec3(0.,.1,0.);
    else if (u_mode == 23) c = validateAlbedo(texture(u_col, uv).rgb);
    else if (u_mode == 18) {
        vec3 N = normalize(texture(u_worldNormal, uv).xyz);
        vec4 tangent = texture(u_tangent, uv);
        vec3 T = tangent.xyz - N * dot(N, tangent.xyz);
        vec3 normal = texture(u_nrm, uv).xyz * 2.0 - 1.0;
        c = (length(T) > 1e-8 ? normalize(normalize(T) * normal.x + cross(N, normalize(T)) * tangent.w * normal.y + N * normal.z) : N) * 0.5 + 0.5;
    }
    else c = texture(u_col, uv).rgb;
    float cov = texture(u_cov, uv).r;
    // outside UV islands: dim checker, so the islands read clearly
    c = mix(bg + 0.03, c, step(0.5, cov));
    // frame of the 0-1 tile
    vec2 e = min(uv, 1.0 - uv) / (u_px * u_scale);
    if (min(e.x, e.y) < 1.0) c = vec3(0.35);
    o = vec4(c, 1.0);
}
"""

TILED_UV_FS = UV_FS.replace(
    "if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) { o = vec4(bg * 0.8, 1.0); return; }",
    "if (uv.x < 0.0 || uv.y < 0.0 || uv.x >= 1.0 || uv.y >= 1.0) discard;")


class UVView:
    def __init__(self, gpu):
        self.gpu = gpu
        self.prog = gpu.fs_program("uvview", UV_FS)
        self.zoom = 1.0
        self.center = [0.5, 0.5]
        self.rotation = 0.
        self.wire = False
        self.tile_source = None
        self.diagnostics = []
        self.min_zoom = .25

    def reset(self):
        self.zoom, self.center = 1.0, [0.5, 0.5]
        self.rotation = 0.
        self.min_zoom = .25

    def _scale(self, w, h):
        return tuple(self.mapping(w, h).scale)

    def mapping(self, w, h):
        return UVMapping((max(int(w), 1), max(int(h), 1)), self.zoom, tuple(self.center), self.rotation)

    def pan(self, dx, dy, w, h):
        self.center = (np.asarray(self.center) + self.mapping(w, h).uv_delta((-dx, dy))).tolist()

    def anchor(self, uv, pixel, size):
        """Keep a UV point fixed under the pointer while changing the view."""
        mapping = self.mapping(*size)
        self.center = (np.asarray(self.center) + np.asarray(uv) - mapping.uv(pixel)).tolist()

    def zoom_by(self, steps):
        self.zoom = min(max(self.zoom * (1.15 ** steps), self.min_zoom), 32.0)

    def fit_tiles(self, engine, size):
        self.rotation = 0.
        addresses = engine.ts.tile_addresses
        low = np.min([address.to_list() for address in addresses], axis=0)
        high = np.max([address.to_list() for address in addresses], axis=0) + 1
        self.center = ((low + high) / 2).tolist()
        base = UVMapping(size).scale
        self.zoom = float(np.min(base / ((high - low) * 1.08)))
        self.min_zoom = min(.25, self.zoom * .25)

    def render_tiles(self, engine, rect, refresh=True):
        ctx, target = self.gpu.ctx, self.gpu.ctx.fbo
        x, y, w, h = rect
        material = engine.ts.tiles
        identity = (id(engine.mesh), engine.ts.pid, material.addresses)
        if identity != self.tile_source:
            self.fit_tiles(engine, (w, h))
            self.tile_source = identity
        if refresh:
            engine.update()
        target.use()
        ctx.viewport, ctx.scissor = rect, rect
        ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND | moderngl.CULL_FACE)
        ctx.clear(.065, .07, .075, 1., viewport=rect)
        mapping = self.mapping(w, h)
        self.diagnostics = []
        try:
            for address in material.addresses:
                corners = mapping.pixel(np.asarray(address.to_list()) + np.array(((0, 0), (1, 0), (0, 1), (1, 1))))
                lo, hi = corners.min(axis=0), corners.max(axis=0)
                left, bottom = max(0, int(np.floor(lo[0]))), max(0, int(np.floor(lo[1])))
                right, top = min(w, int(np.ceil(hi[0]))), min(h, int(np.ceil(hi[1])))
                if right <= left or top <= bottom:
                    continue
                try:
                    with material.cached_evaluation(address, min(material.res, 512), refresh) as tile:
                        target.use()
                        self.render(engine, rect, refresh, _tile=tile,
                                    _scissor=(x + left, y + bottom, right - left, top - bottom))
                except ValueError as error:
                    self.diagnostics.append({"udim": address.udim, "message": str(error)})
            target.use()
            if self.wire:
                ctx.viewport, ctx.scissor = rect, rect
                self._wire(engine, rect, self.gpu.white)
        finally:
            target.use()
            ctx.scissor = None

    def render(self, engine, rect, refresh=True, _tile=None, _scissor=None):
        """rect = (x, y, w, h) in framebuffer pixels, origin bottom-left."""
        ctx = self.gpu.ctx
        x, y, w, h = rect
        if w < 2 or h < 2:
            return
        if _tile is None and engine.ts.tiles is not None:
            return self.render_tiles(engine, rect, refresh)
        if _tile is None and self.tile_source is not None:
            self.tile_source = None
            self.reset()
        if _tile is None:
            self.diagnostics = []
        target = ctx.fbo
        if _tile is None:
            engine.update()          # also refreshes the mask preview
        if _tile is None and engine.renderer.mode == 6 and engine.layer is not None:
            engine.comp.render_mask(engine.layer)
        target.use()
        ctx.viewport = rect
        ctx.scissor = _scissor or rect
        ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND | moderngl.CULL_FACE)
        comp, bakes = (engine.comp, engine.bakes) if _tile is None else (_tile.comp, _tile.bakes)
        source = UV_FS if _tile is None else TILED_UV_FS
        key = "uvview" if _tile is None else "uvview/tiles"
        p = self.prog if _tile is None else self.gpu.fs_program(key, source)
        if engine.color.managed:
            source = source.replace(S.HEADER, S.HEADER + engine.color.display_shader, 1)
            source = source.replace("pow(texture(u_col,uv).rgb,vec3(2.2))","texture(u_col,uv).rgb")
            source = source.replace("float cov = texture(u_cov, uv).r;", "if (u_mode == 0 || u_mode == 1 || u_mode == 10) c = ocio_display(vec4(c, 1.0)).rgb;\n    float cov = texture(u_cov, uv).r;")
            p = self.gpu.fs_program(key + "/managed/" + engine.color.config_id, source)
        texs = [("u_col", comp.color), ("u_rmh", comp.rmh), ("u_nrm", comp.normal),
                ("u_mask", comp.mask_preview), ("u_ao", bakes.ao), ("u_curv", bakes.curv), ("u_cov", bakes.cov)]
        mode = int(engine.renderer.mode)
        self.gpu.set(p,"u_materialModel",int(engine.shader_workflow["model"]=="spec_gloss"))
        self.gpu.set(p,"u_hasCoat",int("coat" in engine.shader_workflow["bindings"]))
        extra = {10: comp.emissive, 12: bakes.thick, 13: bakes.id,
                 14: bakes.nrm, 15: bakes.pos,
                 16: bakes.normal_hp or self.gpu.flat_normal, 17: bakes.height_hp}.get(mode)
        if mode == 19:
            extra=comp.user_outputs.get(engine.renderer.user_preview)
        elif mode in (20,21,22) and comp.semantic_textures:
            extra=comp.semantic_textures[1 if mode==22 else 0]
        texs.append(("u_extra", extra or self.gpu.black))
        texs.extend([("u_tangent", bakes.tangent or self.gpu.black), ("u_worldNormal", bakes.nrm)])
        for i, (name, t) in enumerate(texs):
            t.use(i)
            if name in p:
                p[name] = i
        for name, v in (("u_mode", int(engine.renderer.mode)), ("u_scale", self._scale(w, h)),
                        ("u_albedoThreshold", float(engine.renderer.albedo_threshold) / 255.0),
                        ("u_linearAlbedo", int(engine.color.managed)),
                        ("u_center", tuple(np.asarray(self.center) - (_tile.address.to_list() if _tile is not None else (0, 0)))), ("u_px", (1.0 / w, 1.0 / h)),
                        ("u_bmin", tuple(engine.mesh.positions.min(0))), ("u_bmax", tuple(engine.mesh.positions.max(0)))):
            if name in p:
                p[name] = v
        p["u_uvAxes"].write(np.ascontiguousarray(self.mapping(w, h).axes.T, np.float32).tobytes())
        self.gpu.draw_quad(p)
        if self.wire and _tile is None:
            self._wire(engine, rect, comp.color)
        ctx.scissor = None

    def _wire(self, engine, rect, texture):
        ctx, wire = self.gpu.ctx, engine.renderer.view2d
        wire["u_xf"].write(np.ascontiguousarray(self.mapping(*rect[2:]).matrix().T).tobytes())
        self.gpu.set(wire, "u_flat", 1)
        self.gpu.set(wire, "u_tint", (.9, .9, .9, .2))
        self.gpu.bind(wire, {"u_tex": (0, texture)})
        ctx.wireframe = True
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        try:
            engine.gm.render(wire, engine.ts.key)
        finally:
            ctx.wireframe = False
            ctx.disable(moderngl.BLEND)
