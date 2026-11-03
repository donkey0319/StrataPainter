"""Small moderngl helpers shared by the engine."""
from __future__ import annotations

import moderngl
import numpy as np
import weakref

from . import shaders as S
from .mesh import Mesh, VERTEX_FORMAT, VERTEX_ATTRS
from .memory import MemoryBudget

_NP = {"f2": np.float16, "f4": np.float32, "f1": np.uint8}


class GPU:
    """Owns the context-wide utilities: programs, full-screen quad, blit and dilation."""

    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        self.memory = MemoryBudget()
        self._programs = {}
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], np.float32)
        self.quad_vbo = ctx.buffer(quad.tobytes())
        self._quad_vaos = {}
        self.white = self.texture((1, 1), 4, np.full(4, 1.0, np.float32))
        self.black = self.texture((1, 1), 4, np.zeros(4, np.float32))
        self.flat_normal = self.texture((1, 1), 4, np.array([0.5, 0.5, 1.0, 1.0], np.float32))
        self._scratch = {}

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

    @staticmethod
    def set(prog, name, value):
        """Set a uniform if the program uses it (unused uniforms are optimised away)."""
        if name in prog:
            prog[name] = value

    @staticmethod
    def bind(prog, units: dict):
        """units: {sampler name: (unit, texture)}. Missing samplers are skipped."""
        for name, (unit, tex) in units.items():
            if name in prog:
                prog[name] = unit
                tex.use(unit)

    # -- textures -----------------------------------------------------------------
    def texture(self, size, comps, data=None, dtype="f2", filt=True, repeat=False, purpose="texture") -> moderngl.Texture:
        if data is not None and not isinstance(data, (bytes, bytearray)):
            arr = np.asarray(data)
            if arr.size == comps:  # constant fill
                arr = np.broadcast_to(arr.reshape(1, 1, comps), (size[1], size[0], comps))
            if dtype == "f1" and arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 1) * 255 + 0.5
            data = np.ascontiguousarray(arr, _NP[dtype]).tobytes()
        token = self.memory.reserve(int(size[0]) * int(size[1]) * comps * np.dtype(_NP[dtype]).itemsize, purpose)
        try:
            t = self.ctx.texture(size, comps, data=data, dtype=dtype)
        except Exception:
            self.memory.release(token)
            raise
        reference = weakref.ref(t)
        memory = self.memory
        native_release = type(t).release
        finalizer = weakref.finalize(t, memory.release, token)
        def release():
            texture = reference()
            if texture is not None and finalizer.alive:
                native_release(texture)
                finalizer()
        t.release = release
        t.filter = (moderngl.LINEAR, moderngl.LINEAR) if filt else (moderngl.NEAREST, moderngl.NEAREST)
        t.repeat_x = t.repeat_y = bool(repeat)
        return t

    def clone(self, tex: moderngl.Texture, purpose="snapshot") -> moderngl.Texture:
        t = self.texture(tex.size, tex.components, dtype=tex.dtype, purpose=purpose)
        self.blit(tex, t)
        return t

    def blit(self, src: moderngl.Texture, dst: moderngl.Texture):
        prog = self.fs_program("blit", S.BLIT_FS)
        fbo = self.ctx.framebuffer([dst])
        fbo.use()
        self.ctx.viewport = (0, 0, dst.size[0], dst.size[1])
        self.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        src.use(0)
        prog["u_src"] = 0
        self.draw_quad(prog)
        fbo.release()

    def resample(self, tex: moderngl.Texture, size) -> moderngl.Texture:
        """New texture of `size` with tex's content (linear filtering; mipmapped when shrinking)."""
        out = self.texture(size, tex.components, dtype=tex.dtype)
        if size[0] < tex.size[0]:
            tmp = self.clone(tex)
            tmp.build_mipmaps()
            tmp.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            self.blit(tmp, out)
            tmp.release()
        else:
            self.blit(tex, out)
        return out

    def fill(self, tex: moderngl.Texture, value):
        fbo = self.ctx.framebuffer([tex])
        fbo.clear(*value)
        fbo.release()

    def scratch(self, key, size, comps, dtype="f2") -> moderngl.Texture:
        """A cached work texture, reused across calls (contents undefined)."""
        k = (key, tuple(size), comps, dtype)
        t = self._scratch.get(k)
        if t is None:
            t = self._scratch[k] = self.texture(size, comps, dtype=dtype, purpose="scratch/" + key)
        return t

    def release_scratch(self):
        for t in self._scratch.values():
            t.release()
        self._scratch.clear()

    def dilate(self, tex: moderngl.Texture, coverage: moderngl.Texture, iterations: int):
        """Grow texel data outward from UV islands, in place."""
        if iterations <= 0:
            return
        prog = self.fs_program("dilate", S.DILATE_FS)
        size, comps, dtype = tex.size, tex.components, tex.dtype
        val = [tex, self.scratch("dil_val", size, comps, dtype)]
        cov = [self.scratch("dil_cov0", size, 1, "f1"), self.scratch("dil_cov1", size, 1, "f1")]
        self.blit(coverage, cov[0])
        fbos = [self.ctx.framebuffer([val[1], cov[1]]), self.ctx.framebuffer([val[0], cov[0]])]
        self.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        prog["u_src"] = 0
        prog["u_cov"] = 1
        old = tex.filter
        for i in range(iterations):
            s = i % 2
            fbos[s].use()
            self.ctx.viewport = (0, 0, size[0], size[1])
            val[s].filter = cov[s].filter = (moderngl.NEAREST, moderngl.NEAREST)
            val[s].use(0); cov[s].use(1)
            self.draw_quad(prog)
        if iterations % 2 == 1:
            self.blit(val[1], tex)
        tex.filter = old
        val[1].filter = (moderngl.LINEAR, moderngl.LINEAR)
        for f in fbos:
            f.release()

    def blur(self, src: moderngl.Texture, dst: moderngl.Texture, radius: float):
        """Separable gaussian blur src -> dst (same size/format)."""
        prog = self.fs_program("blur", S.BLUR_FS)
        tmp = self.scratch("blur_tmp", src.size, src.components, src.dtype)
        w, h = src.size
        self.ctx.disable(moderngl.BLEND)
        for s, d, step in ((src, tmp, (1.0 / w, 0.0)), (tmp, dst, (0.0, 1.0 / h))):
            fbo = self.ctx.framebuffer([d])
            fbo.use()
            self.ctx.viewport = (0, 0, w, h)
            s.use(0)
            prog["u_src"] = 0
            prog["u_dir"] = step
            prog["u_radius"] = float(radius)
            self.draw_quad(prog)
            fbo.release()

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

    def read_texel(self, tex: moderngl.Texture, uv) -> np.ndarray:
        x = int(np.clip(uv[0], 0, 1 - 1e-7) * tex.size[0])
        y = int(np.clip(uv[1], 0, 1 - 1e-7) * tex.size[1])
        fbo = self.ctx.framebuffer([tex])
        data = fbo.read(viewport=(x, y, 1, 1), components=tex.components, dtype="f4")
        fbo.release()
        return np.frombuffer(data, np.float32).copy()

    def write(self, tex: moderngl.Texture, arr: np.ndarray):
        """Upload a float array (H, W, C), row 0 = bottom, converting to the texture's dtype."""
        arr = np.asarray(arr, np.float32)
        if tex.dtype == "f1":
            arr = np.clip(arr, 0, 1) * 255 + 0.5
        tex.write(np.ascontiguousarray(arr, _NP[tex.dtype]).tobytes())


class GPUMesh:
    """Vertex buffer for a mesh plus one index buffer per triangle subset (texture set)."""

    def __init__(self, gpu: GPU, mesh: Mesh):
        self.gpu = gpu
        self.mesh = mesh
        self.vbo = gpu.ctx.buffer(mesh.interleaved().tobytes())
        self.ibo = gpu.ctx.buffer(mesh.indices.astype(np.uint32).tobytes())
        self._subsets = {}       # key -> index buffer
        self._vaos = {}

    def add_subset(self, key, tri_ids):
        idx = self.mesh.indices[np.asarray(tri_ids, np.int64)]
        old = self._subsets.pop(key, None)
        if old is not None:
            old.release()
            for k in [k for k in self._vaos if k[1] == key]:
                self._vaos.pop(k).release()
        self._subsets[key] = self.gpu.ctx.buffer(np.ascontiguousarray(idx, np.uint32).tobytes()) \
            if len(idx) else None
        return key

    def vao(self, prog: moderngl.Program, subset=None) -> moderngl.VertexArray:
        key = (prog.glo, subset)
        if key not in self._vaos:
            # skip attributes the program optimised away
            fmt, names = [], []
            for f, n in zip(VERTEX_FORMAT.split(), VERTEX_ATTRS):
                if n in prog:
                    fmt.append(f); names.append(n)
                else:
                    fmt.append(f"{f[:-1]}x4")
            ibo = self.ibo if subset is None else self._subsets[subset]
            self._vaos[key] = self.gpu.ctx.vertex_array(
                prog, [(self.vbo, " ".join(fmt), *names)], index_buffer=ibo, index_element_size=4)
        return self._vaos[key]

    def render(self, prog, subset=None):
        if subset is not None and self._subsets.get(subset) is None:
            return
        self.vao(prog, subset).render(moderngl.TRIANGLES)

    def render_tris(self, prog, tri_ids):
        """Draw an arbitrary triangle list (polygon fill). Not cached."""
        tri_ids = np.asarray(tri_ids, np.int64)
        if tri_ids.size == 0:
            return
        idx = np.ascontiguousarray(self.mesh.indices[tri_ids], np.uint32)
        ibo = self.gpu.ctx.buffer(idx.tobytes())
        fmt, names = [], []
        for f, n in zip(VERTEX_FORMAT.split(), VERTEX_ATTRS):
            if n in prog:
                fmt.append(f); names.append(n)
            else:
                fmt.append(f"{f[:-1]}x4")
        vao = self.gpu.ctx.vertex_array(prog, [(self.vbo, " ".join(fmt), *names)],
                                        index_buffer=ibo, index_element_size=4)
        vao.render(moderngl.TRIANGLES)
        vao.release(); ibo.release()

    def release(self):
        for v in self._vaos.values():
            v.release()
        for b in self._subsets.values():
            if b is not None:
                b.release()
        self.vbo.release(); self.ibo.release()
