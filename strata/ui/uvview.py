"""2D (UV-space) view of the texture set, like Painter's 2D viewport. Shows the same channel as the
3D view's display mode; zoom with the wheel, pan with middle drag. View only (no 2D painting yet).
"""
from __future__ import annotations

import moderngl

from .. import shaders as S

UV_FS = S.HEADER + """
uniform sampler2D u_col; uniform sampler2D u_rmh; uniform sampler2D u_nrm;
uniform sampler2D u_mask; uniform sampler2D u_ao; uniform sampler2D u_curv; uniform sampler2D u_cov;
uniform int u_mode; uniform vec2 u_scale; uniform vec2 u_center; uniform vec2 u_px;
in vec2 v_uv; out vec4 o;
void main() {
    vec2 uv = (v_uv - 0.5) * u_scale + u_center;
    vec2 cell = floor(v_uv / u_px / 12.0);
    vec3 bg = vec3(mod(cell.x + cell.y, 2.0) < 1.0 ? 0.085 : 0.11);
    if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) { o = vec4(bg * 0.8, 1.0); return; }
    vec3 c;
    vec3 rmh = texture(u_rmh, uv).rgb;
    if (u_mode == 2) c = vec3(rmh.r);
    else if (u_mode == 3) c = vec3(rmh.g);
    else if (u_mode == 4) c = vec3(rmh.b);
    else if (u_mode == 5) c = texture(u_nrm, uv).rgb;
    else if (u_mode == 6) c = vec3(texture(u_mask, uv).r);
    else if (u_mode == 7) c = vec3(texture(u_ao, uv).r);
    else if (u_mode == 8) c = vec3(texture(u_curv, uv).r);
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


class UVView:
    def __init__(self, gpu):
        self.gpu = gpu
        self.prog = gpu.fs_program("uvview", UV_FS)
        self.zoom = 1.0
        self.center = [0.5, 0.5]

    def reset(self):
        self.zoom, self.center = 1.0, [0.5, 0.5]

    def _scale(self, w, h):
        a = w / max(h, 1)
        base = 1.08 / self.zoom                    # small margin around the 0-1 tile
        return (base * a, base) if a >= 1 else (base, base / a)

    def pan(self, dx, dy, w, h):
        sx, sy = self._scale(w, h)
        self.center[0] -= dx / w * sx
        self.center[1] += dy / h * sy

    def zoom_by(self, steps):
        self.zoom = min(max(self.zoom * (1.15 ** steps), 0.25), 32.0)

    def render(self, engine, rect):
        """rect = (x, y, w, h) in framebuffer pixels, origin bottom-left."""
        ctx = self.gpu.ctx
        x, y, w, h = rect
        if w < 2 or h < 2:
            return
        engine.update()          # also refreshes the mask preview (it renders into its own target)
        ctx.screen.use()
        ctx.viewport = rect
        ctx.scissor = rect
        ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND | moderngl.CULL_FACE)
        comp, bakes, p = engine.comp, engine.bakes, self.prog
        texs = [("u_col", comp.color), ("u_rmh", comp.rmh), ("u_nrm", comp.normal),
                ("u_mask", comp.mask_preview), ("u_ao", bakes.ao), ("u_curv", bakes.curv), ("u_cov", bakes.cov)]
        for i, (name, t) in enumerate(texs):
            t.use(i)
            if name in p:
                p[name] = i
        for name, v in (("u_mode", int(engine.renderer.mode)), ("u_scale", self._scale(w, h)),
                        ("u_center", tuple(self.center)), ("u_px", (1.0 / w, 1.0 / h))):
            if name in p:
                p[name] = v
        self.gpu.draw_quad(p)
        ctx.scissor = None
