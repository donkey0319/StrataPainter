"""Small moderngl helpers shared by the engine."""
from __future__ import annotations

import moderngl
import numpy as np

from . import shaders as S
from .mesh import Mesh, VERTEX_FORMAT, VERTEX_ATTRS


class GPU:
    """Owns the context-wide utilities: programs, full-screen quad, blit and dilation."""

    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        self._programs = {}
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], np.float32)
        self.quad_vbo = ctx.buffer(quad.tobytes())
        self._quad_vaos = {}
        self.white = self.texture((1, 1), 4, np.full(4, 1.0, np.float32))
        self.black = self.texture((1, 1), 4, np.zeros(4, np.float32))

    # -- programs -----------------------------------------------------------------
    def program(self, name: str, vs: str, fs: str) -> moderngl.Program:
        if name not in self._programs:
            self._programs[name] = self.ctx.program(vertex_shader=vs, fragment_shader=fs)
        return self._programs[name]

    def fs_program(self, name: str, fs: str) -> moderngl.Program:
        return self.program(name, S.FSQ_VS, fs)

    def quad(self, prog: moderngl.Program) -> moderngl.VertexArray:
        key = prog.glo
        if key not in self._quad_vaos:
            self._quad_vaos[key] = self.ctx.vertex_array(prog, [(self.quad_vbo, "2f", "in_pos")])
        return self._quad_vaos[key]

    def draw_quad(self, prog):
        self.quad(prog).render(moderngl.TRIANGLE_STRIP)

    # -- textures -----------------------------------------------------------------
    def texture(self, size, comps, data=None, dtype="f2", filt=True) -> moderngl.Texture:
        if data is not None and not isinstance(data, (bytes, bytearray)):
            np_dtype = {"f2": np.float16, "f4": np.float32, "f1": np.uint8}[dtype]
            arr = np.asarray(data)
            if arr.size == comps:  # constant fill
                arr = np.broadcast_to(arr.reshape(1, 1, comps), (size[1], size[0], comps))
            data = np.ascontiguousarray(arr, np_dtype).tobytes()
        t = self.ctx.texture(size, comps, data=data, dtype=dtype)
        t.filter = (moderngl.LINEAR, moderngl.LINEAR) if filt else (moderngl.NEAREST, moderngl.NEAREST)
        t.repeat_x = t.repeat_y = False
        return t

    def clone(self, tex: moderngl.Texture) -> moderngl.Texture:
        t = self.texture(tex.size, tex.components, dtype=tex.dtype)
        self.blit(tex, t)
        return t

    def blit(self, src: moderngl.Texture, dst: moderngl.Texture):
        prog = self.fs_program("blit", S.BLIT_FS)
        fbo = self.ctx.framebuffer([dst])
        fbo.use()
        self.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        src.use(0)
        prog["u_src"] = 0
        self.draw_quad(prog)
        fbo.release()

    def fill(self, tex: moderngl.Texture, value):
        fbo = self.ctx.framebuffer([tex])
        fbo.clear(*value)
        fbo.release()

    def dilate(self, tex: moderngl.Texture, coverage: moderngl.Texture, iterations: int):
        """Grow texel data outward from UV islands, in place."""
        if iterations <= 0:
            return
        prog = self.fs_program("dilate", S.DILATE_FS)
        size, comps, dtype = tex.size, tex.components, tex.dtype
        val = [tex, self.texture(size, comps, dtype=dtype)]
        cov = [self.clone_r(coverage), self.texture(size, 1, dtype="f1", filt=False)]
        fbos = [self.ctx.framebuffer([val[1], cov[1]]), self.ctx.framebuffer([val[0], cov[0]])]
        self.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        prog["u_src"] = 0
        prog["u_cov"] = 1
        for i in range(iterations):
            s = i % 2
            fbos[s].use()
            val[s].use(0); cov[s].use(1)
            val[s].filter = cov[s].filter = (moderngl.NEAREST, moderngl.NEAREST)
            self.draw_quad(prog)
        if iterations % 2 == 1:
            self.blit(val[1], tex)
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        for f in fbos:
            f.release()
        val[1].release(); cov[0].release(); cov[1].release()

    def clone_r(self, tex):
        t = self.texture(tex.size, 1, dtype="f1", filt=False)
        self.blit(tex, t)
        return t

    def read(self, tex: moderngl.Texture, comps=None) -> np.ndarray:
        """Read a texture to a float32 array (H, W, C) with row 0 = bottom (GL order)."""
        comps = comps or tex.components
        fbo = self.ctx.framebuffer([tex])
        data = fbo.read(components=comps, dtype="f4")
        fbo.release()
        return np.frombuffer(data, np.float32).reshape(tex.size[1], tex.size[0], comps)


class GPUMesh:
    def __init__(self, gpu: GPU, mesh: Mesh):
        self.gpu = gpu
        self.mesh = mesh
        self.vbo = gpu.ctx.buffer(mesh.interleaved().tobytes())
        self.ibo = gpu.ctx.buffer(mesh.indices.astype(np.uint32).tobytes())
        self._vaos = {}

    def vao(self, prog: moderngl.Program) -> moderngl.VertexArray:
        key = prog.glo
        if key not in self._vaos:
            # skip attributes the program optimised away
            fmt, names = [], []
            for f, n in zip(VERTEX_FORMAT.split(), VERTEX_ATTRS):
                if n in prog:
                    fmt.append(f); names.append(n)
                else:
                    fmt.append(f"{f[:-1]}x4")
            self._vaos[key] = self.gpu.ctx.vertex_array(
                prog, [(self.vbo, " ".join(fmt), *names)], index_buffer=self.ibo, index_element_size=4)
        return self._vaos[key]

    def render(self, prog):
        self.vao(prog).render(moderngl.TRIANGLES)

    def release(self):
        for v in self._vaos.values():
            v.release()
        self.vbo.release(); self.ibo.release()
