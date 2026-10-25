"""Viewport: orbit camera, PBR shading, picking buffer, brush cursor and the 2D (UV) view."""
from __future__ import annotations

import math

import moderngl
import numpy as np

from . import shaders as S
from .gpu import GPU, GPUMesh
from .mathutil import look_at, perspective, glmat, normalize

DISPLAY_MODES = ["Material", "Base Color", "Roughness", "Metallic", "Height", "Normal",
                 "Layer Mask", "Ambient Occlusion", "Curvature", "UV Checker",
                 "Emissive", "Opacity", "Thickness", "ID", "World Space Normal", "Position"]
VIEW_MODES = ["3D", "2D", "3D + 2D"]


class Camera:
    def __init__(self):
        self.target = np.zeros(3)
        self.yaw, self.pitch, self.dist, self.fov = 0.6, 0.35, 4.0, 40.0
        self.ortho = False

    def frame(self, center, radius):
        self.target = np.asarray(center, float)
        self.dist = radius / math.sin(math.radians(self.fov) / 2) * 1.15

    @property
    def eye(self):
        cp = math.cos(self.pitch)
        d = np.array([cp * math.sin(self.yaw), math.sin(self.pitch), cp * math.cos(self.yaw)])
        return self.target + d * self.dist

    def view(self):
        # "up" follows the pitch so straight top / bottom views (pitch = +-90 degrees) stay well defined
        sp, cp = math.sin(self.pitch), math.cos(self.pitch)
        up = (-sp * math.sin(self.yaw), cp, -sp * math.cos(self.yaw))
        return look_at(self.eye, self.target, up)

    def snap_to_axis(self, axis):
        """Look along a world axis: axis is '+x', '-x', '+y', '-y', '+z' or '-z' (the side the camera sits on)."""
        q = math.pi / 2
        if axis[1] == "y":
            self.yaw = round(self.yaw / q) * q
            self.pitch = q if axis[0] == "+" else -q
        else:
            self.yaw = {"+z": 0.0, "+x": q, "-z": math.pi, "-x": -q}[axis]
            self.pitch = 0.0

    def proj(self, aspect):
        if self.ortho:
            h = self.dist * math.tan(math.radians(self.fov) / 2)
            from .mathutil import ortho
            return ortho(-h * aspect, h * aspect, -h, h, self.dist * 0.02, self.dist * 10)
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
        if self.ortho:
            return 2 * self.dist * math.tan(math.radians(self.fov) / 2) / max(viewport_h, 1)
        d = float(np.dot(np.asarray(point) - self.eye, normalize(self.target - self.eye)))
        return 2 * max(d, 1e-4) * math.tan(math.radians(self.fov) / 2) / max(viewport_h, 1)

    @property
    def right(self):
        return self.view()[0, :3]

    def to_dict(self):
        return {"target": list(map(float, self.target)), "yaw": self.yaw, "pitch": self.pitch,
                "dist": self.dist, "fov": self.fov, "ortho": self.ortho}

    def load_dict(self, d):
        for k, v in d.items():
            setattr(self, k, np.asarray(v, float) if k == "target" else v)


class Renderer:
    def __init__(self, gpu: GPU):
        self.gpu = gpu
        g = gpu
        self.scene = g.program("scene", S.SCENE_VS, S.SCENE_FS)
        self.pick = g.program("pick", S.SCENE_VS, S.PICK_FS)
        self.bg = g.fs_program("bg", S.BG_FS)
        self.line = g.program("line", S.LINE_VS, S.LINE_FS)
        self.view2d = g.program("view2d", S.VIEW2D_VS, S.VIEW2D_FS)
        self.wire = g.program("wire", S.WIRE_VS, S.LINE_FS)
        self._wire = {}               # key -> (vao inner edges, n, vao outline edges, n)
        self._wire_hl = None          # (key, vbo, vao, n) hovered polygon-fill selection
        self.pick_size = (0, 0)
        self.pick_pos = self.pick_nrm = self.pick_uv = self.pick_fbo = None
        circle = np.zeros((65, 3), np.float32)
        self.cursor_vbo = g.ctx.buffer(reserve=circle.nbytes * 2)
        self.cursor_vao = g.ctx.vertex_array(self.line, [(self.cursor_vbo, "3f", "in_pos")])
        self.env_rot = 0.0
        self.exposure = 1.0
        self.use_ao = True
        self.mode = 0
        self.emissive_intensity = 1.0
        self.alpha_test = False
        self.env_tex = None
        self.env_path = None
        self.env_blur = 0.0

    # -- environment -------------------------------------------------------------
    def load_environment(self, path: str | None):
        """Equirectangular HDR/EXR/LDR environment for image-based lighting (None = studio)."""
        if self.env_tex is not None:
            self.env_tex.release()
            self.env_tex = None
        self.env_path = path
        if not path:
            return
        from .imageio import read_image
        img = read_image(path)[::-1].astype(np.float32)
        if img.shape[2] == 1:
            img = np.repeat(img, 3, 2)
        img = img[..., :3]
        h, w = img.shape[:2]
        t = self.gpu.texture((w, h), 3, img, dtype="f2")
        t.repeat_x, t.repeat_y = True, False
        t.build_mipmaps()
        t.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        self.env_tex = t

    # -- picking ----------------------------------------------------------------
    def _ensure_pick(self, w, h):
        if self.pick_size == (w, h):
            return
        for o in (self.pick_fbo, self.pick_pos, self.pick_nrm, self.pick_uv, getattr(self, "_pick_depth", None)):
            if o is not None:
                o.release()
        ctx = self.gpu.ctx
        self.pick_pos = self.gpu.texture((w, h), 4, dtype="f4", filt=False)
        self.pick_nrm = self.gpu.texture((w, h), 4, dtype="f4", filt=False)
        self.pick_uv = self.gpu.texture((w, h), 4, dtype="f4", filt=False)
        self._pick_depth = ctx.depth_renderbuffer((w, h))
        self.pick_fbo = ctx.framebuffer([self.pick_pos, self.pick_nrm, self.pick_uv], self._pick_depth)
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

    def _read_px(self, x, y, att):
        return np.frombuffer(self.pick_fbo.read(viewport=(x, y, 1, 1), components=4, attachment=att,
                                                dtype="f4"), np.float32)

    def read_pick(self, x, y):
        """x, y in viewport pixels with origin bottom-left -> (position, normal) or None."""
        info = self.read_pick_info(x, y)
        return None if info is None else (info["pos"], info["nrm"])

    def read_pick_info(self, x, y):
        """Full pick: position, normal, uv, triangle id, mesh part, screen pixel."""
        w, h = self.pick_size
        if not (0 <= x < w and 0 <= y < h):
            return None
        xi, yi = int(x), int(y)
        p = self._read_px(xi, yi, 0)
        if p[3] < 0.5:
            return None
        n = self._read_px(xi, yi, 1)
        u = self._read_px(xi, yi, 2)
        return {"pos": p[:3].astype(float), "nrm": normalize(n[:3]), "uv": u[:2].astype(float),
                "tri": int(round(u[2])), "part": int(round(u[3])), "px": (float(x), float(y))}

    def read_pick_region(self, x0, y0, x1, y1):
        """Triangle ids visible in a screen rectangle -> (H, W) int array (-1 = background)."""
        w, h = self.pick_size
        x0, x1 = sorted((int(np.clip(x0, 0, w - 1)), int(np.clip(x1, 0, w - 1))))
        y0, y1 = sorted((int(np.clip(y0, 0, h - 1)), int(np.clip(y1, 0, h - 1))))
        rw, rh = x1 - x0 + 1, y1 - y0 + 1
        vp = (x0, y0, rw, rh)
        u = np.frombuffer(self.pick_fbo.read(viewport=vp, components=4, attachment=2, dtype="f4"),
                          np.float32).reshape(rh, rw, 4)
        p = np.frombuffer(self.pick_fbo.read(viewport=vp, components=4, attachment=0, dtype="f4"),
                          np.float32).reshape(rh, rw, 4)
        ids = np.where(p[..., 3] > 0.5, np.round(u[..., 2]).astype(np.int64), -1)
        return ids, (x0, y0)

    # -- shading ----------------------------------------------------------------
    def render(self, gm: GPUMesh, cam: Camera, vp, comp, bakes, rect):
        """Single texture set (kept for compatibility)."""
        self.render_sets(gm, cam, vp, [(None, comp, bakes)], rect)

    def render_sets(self, gm: GPUMesh, cam: Camera, vp, sets, rect, background=True):
        """sets: list of (subset key, compositor, bakes)."""
        ctx = self.gpu.ctx
        ctx.viewport = rect
        ctx.scissor = rect
        if background:
            ctx.clear(0.0, 0.0, 0.0, 1.0, depth=1.0, viewport=rect)
            ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND | moderngl.CULL_FACE)
            self.gpu.draw_quad(self.bg)
        ctx.enable(moderngl.DEPTH_TEST)
        s, g = self.scene, self.gpu
        s["u_vp"].write(glmat(vp))
        g.set(s, "u_campos", tuple(map(float, cam.eye)))
        g.set(s, "u_mode", int(self.mode))
        g.set(s, "u_exposure", float(self.exposure))
        g.set(s, "u_envRot", float(self.env_rot))
        g.set(s, "u_useAO", int(self.use_ao))
        g.set(s, "u_emissiveIntensity", float(self.emissive_intensity))
        g.set(s, "u_alphaTest", int(bool(self.alpha_test)))
        g.set(s, "u_hasEnv", int(self.env_tex is not None))
        mesh = gm.mesh
        lo, hi = mesh.bounds
        g.set(s, "u_bmin", tuple(map(float, lo)))
        g.set(s, "u_bmax", tuple(map(float, hi)))
        if self.env_tex is not None:
            levels = max(int(math.log2(max(self.env_tex.size))) - 2, 1)
            g.set(s, "u_envMaxLod", float(levels))
        for key, comp, bakes in sets:
            units = {"u_texC": (0, comp.color), "u_texR": (1, comp.rmh), "u_texN": (2, comp.normal),
                     "u_ao": (3, bakes.ao), "u_curv": (4, bakes.curv), "u_maskPrev": (5, comp.mask_preview),
                     "u_texE": (6, comp.emissive), "u_thick": (7, bakes.thick or g.white),
                     "u_id": (8, bakes.id or g.white), "u_pos": (9, bakes.pos), "u_wnrm": (10, bakes.nrm),
                     "u_envMap": (11, self.env_tex or g.black)}
            g.bind(s, units)
            gm.render(s, key)
        ctx.scissor = None

    def render_2d(self, gm: GPUMesh, subset, texture, rect, zoom=1.0, pan=(0.0, 0.0), comp=-1,
                  wire=True):
        """Draw a texture-set channel flat in UV space. comp: -1 rgb, else component index."""
        ctx = self.gpu.ctx
        x, y, w, h = rect
        ctx.viewport = rect
        ctx.scissor = rect
        ctx.clear(0.09, 0.095, 0.1, 1.0, viewport=rect)
        ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND | moderngl.CULL_FACE)
        aspect = w / max(h, 1)
        sx, sy = 2.0 * zoom / max(aspect, 1e-6), 2.0 * zoom
        if aspect < 1:
            sx, sy = 2.0 * zoom, 2.0 * zoom * aspect
        xf = np.array([[sx, 0, -sx * 0.5 + pan[0]], [0, sy, -sy * 0.5 + pan[1]], [0, 0, 1]], np.float32)
        p = self.view2d
        p["u_xf"].write(np.ascontiguousarray(xf.T).tobytes())
        self.gpu.bind(p, {"u_tex": (0, texture)})
        self.gpu.set(p, "u_comp", int(comp))
        self.gpu.set(p, "u_flat", 0)
        gm.render(p, subset)
        if wire:
            ctx.wireframe = True
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self.gpu.set(p, "u_flat", 1)
            self.gpu.set(p, "u_tint", (0.9, 0.9, 0.9, 0.12))
            gm.render(p, subset)
            ctx.wireframe = False
            ctx.disable(moderngl.BLEND)
        ctx.scissor = None
        return xf

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

    # ------------------------------------------------------------------ polygon fill wireframe
    def draw_wire(self, key, segments, cam, vp, rect, highlight=None):
        """Mesh wireframe drawn over the 3D view (depth tested, nudged towards the camera).
        segments() -> (inner, outline) float32 (N, 2, 3) arrays, only called when key is new.
        highlight: (hkey, tris (M, 3, 3)) triangles to tint, e.g. what a polygon-fill click would fill."""
        ctx, g = self.gpu.ctx, self.gpu
        if key not in self._wire:
            for old in self._wire.values():
                for o in old[::2]:
                    if o is not None:
                        o.release()
            self._wire.clear()
            entry = []
            for seg in segments():
                seg = np.ascontiguousarray(seg, np.float32).reshape(-1, 3)
                if len(seg):
                    vbo = ctx.buffer(seg.tobytes())
                    entry += [ctx.vertex_array(self.wire, [(vbo, "3f", "in_pos")]), len(seg)]
                else:
                    entry += [None, 0]
            self._wire[key] = tuple(entry)
        vao_in, n_in, vao_out, n_out = self._wire[key]
        p = self.wire
        p["u_vp"].write(glmat(vp))
        g.set(p, "u_campos", tuple(map(float, cam.eye)))
        ctx.viewport = rect
        ctx.scissor = rect
        ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        ctx.disable(moderngl.CULL_FACE)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        ctx.line_width = 1.0
        if highlight is not None:
            hkey, tris = highlight
            if self._wire_hl is None or self._wire_hl[0] != hkey:
                if self._wire_hl is not None:
                    self._wire_hl[1].release()
                    self._wire_hl[2].release()
                tris = np.ascontiguousarray(tris, np.float32).reshape(-1, 3)
                vbo = ctx.buffer(tris.tobytes() if len(tris) else np.zeros(9, np.float32).tobytes())
                self._wire_hl = (hkey, vbo, ctx.vertex_array(p, [(vbo, "3f", "in_pos")]), len(tris))
            g.set(p, "u_bias", 0.002)
            p["u_color"] = (1.0, 1.0, 1.0, 0.24)
            if self._wire_hl[3]:
                self._wire_hl[2].render(moderngl.TRIANGLES, vertices=self._wire_hl[3])
        g.set(p, "u_bias", 0.003)
        if vao_in is not None:
            p["u_color"] = (0.86, 0.87, 0.9, 0.16)
            vao_in.render(moderngl.LINES, vertices=n_in)
        if vao_out is not None:
            p["u_color"] = (0.9, 0.91, 0.93, 0.6)
            vao_out.render(moderngl.LINES, vertices=n_out)
        ctx.disable(moderngl.BLEND)
        ctx.scissor = None
