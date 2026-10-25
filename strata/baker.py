"""Texture-space bakes ("mesh maps"): position, world normal, curvature, coverage, ambient occlusion,
thickness, ID and mesh-part maps.

AO and thickness share one orthographic depth map per sample direction: AO looks at directions in the
hemisphere around the normal, thickness at directions pointing into the surface and measures how far
the ray travels before it leaves the mesh. Bakes can be limited to one texture set's triangles while
the whole mesh still occludes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import moderngl
import numpy as np

from . import shaders as S
from .gpu import GPU, GPUMesh
from .mathutil import look_at, ortho, glmat, fibonacci_sphere
from .mesh import Mesh
from .raycast import TriangleGrid

PAD = 16  # texels of dilation around UV islands

ID_SOURCES = ["Vertex Color", "Mesh Part", "Material"]
ID_GENERATORS = ["Random", "Hue Shift", "Grayscale"]
MESH_MAP_NAMES = ["Position", "World Space Normal", "Curvature", "Ambient Occlusion", "Thickness", "ID",
                  "Normal (high poly)", "Height (high poly)"]


@dataclass
class BakeSettings:
    ao_samples: int = 96
    ao_max_distance: float = 0.0       # fraction of mesh size; 0 = unlimited
    ao_spread: float = 90.0            # degrees from the normal
    ground_plane: bool = False
    ground_offset: float = 0.0         # fraction of mesh size below the lowest point
    thickness_max_distance: float = 0.5  # fraction of mesh size that counts as "fully thick"
    shadow_res: int = 1024             # depth map resolution per direction
    id_source: int = 1                 # ID_SOURCES index
    id_generator: int = 0              # ID_GENERATORS index
    dilation: int = PAD
    enabled: dict = field(default_factory=lambda: {"ao": True, "thickness": True, "id": True})
    # high poly -> low poly
    high_poly: list = field(default_factory=list)    # mesh file paths (in the low poly's space)
    hp_front: float = 0.02             # max frontal distance (fraction of mesh size)
    hp_rear: float = 0.02              # max rear distance
    hp_ignore_backface: bool = True
    id_from_high: bool = True          # ID from high-poly vertex colours (when id_source is Vertex Color)
    curv_from_normal: bool = True      # add normal-map detail to the curvature
    curv_normal_strength: float = 1.0

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        s = BakeSettings()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s


@dataclass
class BakeSet:
    pos: moderngl.Texture
    nrm: moderngl.Texture
    curv: moderngl.Texture
    ao: moderngl.Texture
    cov: moderngl.Texture
    res: int
    thick: moderngl.Texture = None
    id: moderngl.Texture = None
    part: moderngl.Texture = None
    settings: BakeSettings = None
    tangent: moderngl.Texture = None
    normal_hp: moderngl.Texture = None     # tangent-space normal baked from the high poly
    height_hp: moderngl.Texture = None     # height baked from the high poly (0.5 = on the low poly)
    hp_hits: float = 0.0                   # fraction of texels whose ray found the high poly

    def maps(self) -> dict:
        return {"position": self.pos, "world_normal": self.nrm, "curvature": self.curv,
                "ao": self.ao, "thickness": self.thick, "id": self.id, "coverage": self.cov,
                "part": self.part, "tangent": self.tangent, "normal": self.normal_hp,
                "height": self.height_hp}

    def release(self):
        for t in (self.pos, self.nrm, self.curv, self.ao, self.cov, self.thick, self.id, self.part,
                  self.tangent, self.normal_hp, self.height_hp):
            if t is not None:
                t.release()


class Baker:
    def __init__(self, gpu: GPU):
        self.gpu = gpu

    def bake(self, gm: GPUMesh, res: int, ao_samples: int = None, ao_res: int = None,
             progress=None, subset=None, settings: BakeSettings | None = None,
             high: list | None = None) -> BakeSet:
        """Bake one texture set. high: high-poly Mesh objects (already in the low poly's space)."""
        st = settings or BakeSettings()
        if ao_samples is not None:
            st.ao_samples = int(ao_samples)
        if ao_res is not None:
            st.shadow_res = int(ao_res)
        g, ctx = self.gpu, self.gpu.ctx
        pos = g.texture((res, res), 4, dtype="f4")
        nrm = g.texture((res, res), 4)
        curv = g.texture((res, res), 4)
        cov = g.texture((res, res), 1, dtype="f1", filt=False)
        idt = g.texture((res, res), 4, dtype="f1")
        part = g.texture((res, res), 4, dtype="f2", filt=False)
        tan = g.texture((res, res), 4)
        fbo = ctx.framebuffer([pos, nrm, curv, cov, idt, part, tan])
        fbo.use()
        ctx.viewport = (0, 0, res, res)
        fbo.clear(0, 0, 0, 0)
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        prog = g.program("bake_geom", S.UV_VS, S.BAKE_GEOM_FS)
        g.set(prog, "u_idSource", int(st.id_source))
        g.set(prog, "u_idGen", int(st.id_generator))
        gm.render(prog, subset)
        fbo.release()

        hp = self._bake_high(gm, high, pos, nrm, tan, idt, res, st) if high else None
        occluder, spos, snrm = gm, pos, nrm
        if hp is not None:
            occluder, spos, snrm = hp["gm"], hp["pos"], hp["nrm"]
        ao, thick = self._bake_ao(occluder, spos, snrm, res, st, progress, frame=gm.mesh)
        normal_hp = height_hp = None
        hits = 0.0
        if hp is not None:
            normal_hp, height_hp, hits = hp["normal"], hp["height"], hp["hits"]
            if st.curv_from_normal:
                curv = self._curv_from_normal(normal_hp, curv, st.curv_normal_strength)
            for k in ("pos", "nrm", "info", "col"):
                hp[k].release()
            hp["gm"].release()
        for t in (nrm, curv, ao, thick, pos, idt, tan, normal_hp, height_hp):
            if t is not None:
                g.dilate(t, cov, st.dilation)
        return BakeSet(pos, nrm, curv, ao, cov, res, thick=thick, id=idt, part=part, settings=st,
                       tangent=tan, normal_hp=normal_hp, height_hp=height_hp, hp_hits=hits)

    # ------------------------------------------------------------------ high poly
    @staticmethod
    def merge_high(meshes) -> Mesh:
        P, N, I, C = [], [], [], []
        base = 0
        for m in meshes:
            P.append(m.positions); N.append(m.normals); C.append(m.colors)
            I.append(m.indices.astype(np.int64) + base)
            base += len(m.positions)
        P = np.concatenate(P)
        return Mesh("high", P, np.concatenate(N), np.zeros((len(P), 2), np.float32), np.concatenate(I),
                    colors=np.concatenate(C)).finalize(light=True)

    def _bake_high(self, gm, high, pos, nrm, tan, idt, res, st: BakeSettings):
        g, ctx = self.gpu, self.gpu.ctx
        hm = high if isinstance(high, Mesh) else self.merge_high(high)
        grid = TriangleGrid(hm.positions, hm.normals, hm.indices, hm.colors)
        tex = grid.upload(g)
        size = gm.mesh.radius * 2
        front, rear = float(st.hp_front * size), float(st.hp_rear * size)
        out = {"pos": g.texture((res, res), 4, dtype="f4"), "nrm": g.texture((res, res), 4),
               "info": g.texture((res, res), 4, dtype="f4", filt=False), "col": g.texture((res, res), 4, dtype="f1")}
        prog = g.fs_program("hp_ray", S.HP_RAY_FS)
        units = {"u_pos": (0, pos), "u_nrm": (1, nrm), "u_tpos": (2, tex["tri_pos"]), "u_tnrm": (3, tex["tri_nrm"]),
                 "u_tcol": (4, tex["tri_col"]), "u_cells": (5, tex["cells"]), "u_items": (6, tex["items"])}
        g.bind(prog, units)
        for k, v in grid.uniforms().items():
            g.set(prog, k, v)
        g.set(prog, "u_front", front)
        g.set(prog, "u_rear", rear)
        g.set(prog, "u_ignoreBack", int(bool(st.hp_ignore_backface)))
        pos.filter = nrm.filter = (moderngl.NEAREST, moderngl.NEAREST)
        fbo = ctx.framebuffer([out["pos"], out["nrm"], out["info"], out["col"]])
        fbo.use()
        ctx.viewport = (0, 0, res, res)
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST)
        g.draw_quad(prog)
        fbo.release()
        pos.filter = nrm.filter = (moderngl.LINEAR, moderngl.LINEAR)
        for t in tex.values():
            t.release()
        normal_hp, height_hp = g.texture((res, res), 4), g.texture((res, res), 4)
        cprog = g.fs_program("hp_convert", S.HP_CONVERT_FS)
        g.bind(cprog, {"u_lnrm": (0, nrm), "u_tan": (1, tan), "u_hnrm": (2, out["nrm"]), "u_info": (3, out["info"])})
        g.set(cprog, "u_front", front)
        g.set(cprog, "u_rear", rear)
        fbo = ctx.framebuffer([normal_hp, height_hp])
        fbo.use()
        ctx.viewport = (0, 0, res, res)
        g.draw_quad(cprog)
        fbo.release()
        info = g.read(out["info"])
        hits = float((info[..., 1] > 0.5).sum() / max(1, (g.read(pos)[..., 3] > 0.5).sum()))
        if st.id_source == 0 and st.id_from_high:
            g.blit(out["col"], idt)
        out["gm"] = GPUMesh(g, hm)
        out["normal"], out["height"], out["hits"] = normal_hp, height_hp, hits
        return out

    def _curv_from_normal(self, nmap, curv, strength):
        g = self.gpu
        out = g.texture(curv.size, 4)
        p = g.fs_program("curv_from_normal", S.CURV_FROM_NORMAL_FS)
        g.bind(p, {"u_nmap": (0, nmap), "u_curv": (1, curv)})
        g.set(p, "u_strength", float(strength))
        fbo = g.ctx.framebuffer([out])
        fbo.use()
        g.ctx.viewport = (0, 0, curv.size[0], curv.size[1])
        g.draw_quad(p)
        fbo.release()
        curv.release()
        return out

    def _bake_ao(self, gm, pos, nrm, res, st: BakeSettings, progress, frame=None):
        g, ctx = self.gpu, self.gpu.ctx
        mesh = frame or gm.mesh
        c, r = mesh.center, mesh.radius * 1.02
        size = mesh.radius * 2
        smap_res = int(st.shadow_res)
        depth = ctx.depth_texture((smap_res, smap_res))
        depth.filter = (moderngl.NEAREST, moderngl.NEAREST)
        depth.compare_func = ""
        dfbo = ctx.framebuffer(depth_attachment=depth)
        acc = g.texture((res, res), 4, dtype="f4")
        tacc = g.texture((res, res), 4, dtype="f4")
        afbo = ctx.framebuffer([acc, tacc])
        afbo.clear(0, 0, 0, 0)
        dprog = g.program("depth", S.DEPTH_VS, S.DEPTH_FS)
        aprog = g.fs_program("ao_accum", S.AO_ACCUM_FS)
        aprog["u_pos"], aprog["u_nrm"], aprog["u_depth"] = 0, 1, 2
        near, far = 0.01, 4 * r
        bias = r * 0.006
        aprog["u_bias"] = bias
        aprog["u_dbias"] = bias / (far - near)
        g.set(aprog, "u_depthRange", float(far - near))
        g.set(aprog, "u_aoMax", float(st.ao_max_distance * size))
        g.set(aprog, "u_spreadCos", float(np.cos(np.radians(np.clip(st.ao_spread, 1, 90)))))
        g.set(aprog, "u_ground", int(bool(st.ground_plane)))
        g.set(aprog, "u_groundY", float(mesh.bounds[0][1] - st.ground_offset * size))
        g.set(aprog, "u_thickMax", float(max(st.thickness_max_distance, 1e-3) * size))
        n = max(int(st.ao_samples), 1)
        for i, d in enumerate(fibonacci_sphere(n)):
            vp = ortho(-r, r, -r, r, near, far) @ look_at(c + d * 2 * r, c)
            dfbo.use()
            ctx.viewport = (0, 0, smap_res, smap_res)
            dfbo.clear(depth=1.0)
            ctx.disable(moderngl.BLEND | moderngl.CULL_FACE)
            ctx.enable(moderngl.DEPTH_TEST)
            dprog["u_vp"].write(glmat(vp))
            gm.render(dprog)
            afbo.use()
            ctx.viewport = (0, 0, res, res)
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
        out = []
        rprog = g.fs_program("ao_resolve", S.AO_RESOLVE_FS)
        for src, empty in ((acc, 1.0), (tacc, 1.0)):
            t = g.texture((res, res), 4)
            rfbo = ctx.framebuffer([t])
            rfbo.use()
            ctx.viewport = (0, 0, res, res)
            src.use(0)
            rprog["u_acc"] = 0
            g.set(rprog, "u_empty", empty)
            g.draw_quad(rprog)
            rfbo.release()
            out.append(t)
        for o in (afbo, dfbo, acc, tacc, depth):
            o.release()
        return out[0], out[1]
