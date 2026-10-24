"""Viewport: orbit camera, PBR shading, picking buffer and brush cursor."""
from __future__ import annotations

import math

import moderngl
import numpy as np

from . import shaders as S
from .gpu import GPU, GPUMesh
from .mathutil import look_at, perspective, glmat, normalize

DISPLAY_MODES = ["Material", "Base Color", "Roughness", "Metallic", "Height", "Normal",
                 "Layer Mask", "Ambient Occlusion", "Curvature", "UV Checker"]


class Camera:
    def __init__(self):
        self.target = np.zeros(3)
        self.yaw, self.pitch, self.dist, self.fov = 0.6, 0.35, 4.0, 40.0

    def frame(self, center, radius):
        self.target = np.asarray(center, float)
        self.dist = radius / math.sin(math.radians(self.fov) / 2) * 1.15

    @property
    def eye(self):
        cp = math.cos(self.pitch)
        d = np.array([cp * math.sin(self.yaw), math.sin(self.pitch), cp * math.cos(self.yaw)])
        return self.target + d * self.dist

    def view(self):
        return look_at(self.eye, self.target)

    def proj(self, aspect):
        return perspective(self.fov, aspect, self.dist * 0.02, self.dist * 10)

    def orbit(self, dx, dy):
        self.yaw -= dx * 0.008
        self.pitch = float(np.clip(self.pitch + dy * 0.008, -1.55, 1.55))

    def pan(self, dx, dy, viewport_h):
        v = self.view()
        right, up = v[0, :3], v[1, :3]
        s = 2 * self.dist * math.tan(math.radians(self.fov) / 2) / max(viewport_h, 1)
        self.target = self.target + (-right * dx + up * dy) * s

    def zoom(self, steps):
        self.dist *= 0.88 ** steps

    def world_per_pixel(self, point, viewport_h):
        d = float(np.dot(np.asarray(point) - self.eye, normalize(self.target - self.eye)))
        return 2 * max(d, 1e-4) * math.tan(math.radians(self.fov) / 2) / max(viewport_h, 1)


class Renderer:
    def __init__(self, gpu: GPU):
        self.gpu = gpu
        g = gpu
        self.scene = g.program("scene", S.SCENE_VS, S.SCENE_FS)
        self.pick = g.program("pick", S.SCENE_VS, S.PICK_FS)
        self.bg = g.fs_program("bg", S.BG_FS)
        self.line = g.program("line", S.LINE_VS, S.LINE_FS)
        for i, n in enumerate(["u_texC", "u_texR", "u_texN", "u_ao", "u_curv", "u_maskPrev"]):
            self.scene[n] = i
        self.pick_size = (0, 0)
        self.pick_pos = self.pick_nrm = self.pick_fbo = None
        circle = np.zeros((65, 3), np.float32)
        self.cursor_vbo = g.ctx.buffer(reserve=circle.nbytes * 2)
        self.cursor_vao = g.ctx.vertex_array(self.line, [(self.cursor_vbo, "3f", "in_pos")])
        self.env_rot = 0.0
        self.exposure = 1.0
        self.use_ao = True
        self.mode = 0

    # -- picking ----------------------------------------------------------------
    def _ensure_pick(self, w, h):
        if self.pick_size == (w, h):
            return
        for o in (self.pick_fbo, self.pick_pos, self.pick_nrm, getattr(self, "_pick_depth", None)):
            if o is not None:
                o.release()
        ctx = self.gpu.ctx
        self.pick_pos = self.gpu.texture((w, h), 4, dtype="f4", filt=False)
        self.pick_nrm = self.gpu.texture((w, h), 4, dtype="f4", filt=False)
        self._pick_depth = ctx.depth_renderbuffer((w, h))
        self.pick_fbo = ctx.framebuffer([self.pick_pos, self.pick_nrm], self._pick_depth)
        self.pick_size = (w, h)

    def render_pick(self, gm: GPUMesh, vp, w, h):
        self._ensure_pick(w, h)
        ctx = self.gpu.ctx
        self.pick_fbo.use()
        ctx.viewport = (0, 0, w, h)
        self.pick_fbo.clear(0, 0, 0, 0, depth=1.0)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND | moderngl.CULL_FACE)
        self.pick["u_vp"].write(glmat(vp))
        gm.render(self.pick)

    def read_pick(self, x, y):
        """x, y in viewport pixels with origin bottom-left."""
        w, h = self.pick_size
        if not (0 <= x < w and 0 <= y < h):
            return None
        x, y = int(x), int(y)
        p = np.frombuffer(self.pick_fbo.read(viewport=(x, y, 1, 1), components=4, attachment=0, dtype="f4"), np.float32)
        if p[3] < 0.5:
            return None
        n = np.frombuffer(self.pick_fbo.read(viewport=(x, y, 1, 1), components=4, attachment=1, dtype="f4"), np.float32)
        return p[:3].astype(float), normalize(n[:3])

    # -- shading ----------------------------------------------------------------
    def render(self, gm: GPUMesh, cam: Camera, vp, comp, bakes, rect):
        ctx = self.gpu.ctx
        x, y, w, h = rect
        ctx.viewport = rect
        ctx.scissor = rect
        ctx.clear(0.0, 0.0, 0.0, 1.0, depth=1.0, viewport=rect)
        ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND | moderngl.CULL_FACE)
        self.gpu.draw_quad(self.bg)
        ctx.enable(moderngl.DEPTH_TEST)
        s = self.scene
        s["u_vp"].write(glmat(vp))
        s["u_campos"] = tuple(map(float, cam.eye))
        s["u_mode"] = int(self.mode)
        s["u_exposure"] = float(self.exposure)
        s["u_envRot"] = float(self.env_rot)
        s["u_useAO"] = int(self.use_ao)
        comp.color.use(0); comp.rmh.use(1); comp.normal.use(2)
        bakes.ao.use(3); bakes.curv.use(4); comp.mask_preview.use(5)
        gm.render(s)
        ctx.scissor = None

    def draw_cursor(self, hit, nrm, radius, vp, rect, color=(1, 1, 1, 0.85)):
        ctx = self.gpu.ctx
        n = normalize(nrm)
        a = normalize(np.cross(n, [0, 1, 0] if abs(n[1]) < 0.95 else [1, 0, 0]))
        b = np.cross(n, a)
        t = np.linspace(0, 2 * np.pi, 65)
        lift = n * radius * 0.02
        ring = hit + lift + (np.outer(np.cos(t), a) + np.outer(np.sin(t), b)) * radius
        dot = hit + lift + (np.outer(np.cos(t), a) + np.outer(np.sin(t), b)) * radius * 0.04
        pts = np.vstack([ring, dot]).astype(np.float32)
        self.cursor_vbo.write(pts.tobytes())
        ctx.viewport = rect
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.line["u_vp"].write(glmat(vp))
        self.line["u_color"] = (0, 0, 0, 0.5)
        self.cursor_vao.render(moderngl.LINE_STRIP, vertices=65)
        self.line["u_color"] = tuple(color)
        ctx.line_width = 1.0
        self.cursor_vao.render(moderngl.LINE_STRIP, vertices=65)
        self.cursor_vao.render(moderngl.LINE_STRIP, vertices=65, first=65)
        ctx.disable(moderngl.BLEND)
