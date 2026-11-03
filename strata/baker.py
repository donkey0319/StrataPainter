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
    external_maps: dict = field(default_factory=dict)
    # high poly -> low poly
    high_poly: list = field(default_factory=list)    # mesh file paths (in the low poly's space)
    hp_front: float = 0.02             # max frontal distance (fraction of mesh size)
    hp_rear: float = 0.02              # max rear distance
    hp_ignore_backface: bool = True
    id_from_high: bool = True          # ID from high-poly vertex colours (when id_source is Vertex Color)
    curv_from_normal: bool = True      # add normal-map detail to the curvature
    curv_normal_strength: float = 1.0
    pairing: str = "all"
    low_suffix: str = "_low"
    high_suffix: str = "_high"
    cage_path: str = ""
    cage_hash: str = ""
    supersampling: int = 1
    ray_correction_pid: str = ""
    distance_correction_pid: str = ""
    correction_hashes: dict = field(default_factory=dict)

    def to_dict(self):
        result = asdict(self)
        if not self.external_maps:
            result.pop("external_maps", None)
        from .bakecontrol import DEFAULTS
        for key, default in DEFAULTS.items():
            if result[key] == default:
                result.pop(key)
        return result

    @staticmethod
    def from_dict(d):
        s = BakeSettings()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                setattr(s, k, v)
        from .bakecontrol import validate_settings
        validate_settings(s)
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
    projection: moderngl.Texture = None     # green hits, red misses, blue cage crossings; coverage alpha

    def maps(self) -> dict:
        result = {"position": self.pos, "world_normal": self.nrm, "curvature": self.curv,
                "ao": self.ao, "thickness": self.thick, "id": self.id, "coverage": self.cov,
                "part": self.part, "tangent": self.tangent, "normal": self.normal_hp,
                "height": self.height_hp}
        if self.projection is not None:
            result["projection_diagnostics"] = self.projection
        return result

    def release(self):
        for t in (self.pos, self.nrm, self.curv, self.ao, self.cov, self.thick, self.id, self.part,
                  self.tangent, self.normal_hp, self.height_hp, self.projection):
            if t is not None:
                t.release()


class _BakeContext:
    def __init__(self, original):
        object.__setattr__(self, "original", original)
        object.__setattr__(self, "created", [])

    def __getattr__(self, name):
        original = getattr(self.original, name)
        if name in ("framebuffer", "depth_texture", "depth_renderbuffer", "buffer", "vertex_array"):
            def create(*args, **kwargs):
                result = original(*args, **kwargs)
                self.created.append(result)
                return result
            return create
        return original

    def __setattr__(self, name, value):
        setattr(self.original, name, value)


class _BakeAllocations:
    def __init__(self, gpu):
        self.original, self.created = gpu, []
        self.ctx = _BakeContext(gpu.ctx)

    def __getattr__(self, name):
        return getattr(self.original, name)

    def texture(self, *args, **kwargs):
        result = self.original.texture(*args, **kwargs)
        self.created.append(result)
        return result

    def resample(self, *args, **kwargs):
        source, size = args[:2]
        result = self.texture(size, source.components, dtype=source.dtype)
        if size[0] < source.size[0]:
            temporary = self.texture(source.size, source.components, dtype=source.dtype)
            self.original.blit(source, temporary)
            temporary.build_mipmaps()
            temporary.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            self.original.blit(temporary, result)
            temporary.release()
        else:
            self.original.blit(source, result)
        return result


class Baker:
    def __init__(self, gpu: GPU):
        self.gpu = gpu

    def bake(self, gm: GPUMesh, res: int, ao_samples: int = None, ao_res: int = None,
             progress=None, subset=None, settings: BakeSettings | None = None,
             high: list | None = None, cage=None, ray_correction=None, distance_correction=None) -> BakeSet:
        from .bakecontrol import validate_settings, validate_cage, pair_sources
        st = BakeSettings.from_dict((settings or BakeSettings()).to_dict())
        validate_settings(st)
        if cage is not None:
            if not high:
                raise ValueError("A projection cage requires high-poly sources")
            validate_cage(gm.mesh, cage)
        if high and subset is None:
            pair_sources(gm.mesh, high, st)  # reject unmatched names before allocations
        factor = st.supersampling
        if res * factor > self.gpu.ctx.info["GL_MAX_TEXTURE_SIZE"]:
            raise ValueError("Supersampled bake exceeds the GPU texture dimension limit")
        allocations = _BakeAllocations(self.gpu)
        result = None
        try:
            working = BakeSettings.from_dict(st.to_dict())
            working.dilation *= factor
            working.curv_normal_strength *= factor
            result = Baker(allocations)._bake(gm, res * factor, ao_samples, ao_res, progress, subset, working, high, cage,
                                               ray_correction, distance_correction)
            if factor > 1:
                fields = {"position": "pos", "world_normal": "nrm", "curvature": "curv", "ao": "ao",
                          "coverage": "cov", "thickness": "thick", "id": "id", "part": "part", "tangent": "tangent",
                          "normal": "normal_hp", "height": "height_hp", "projection_diagnostics": "projection"}
                for name, texture in result.maps().items():
                    if texture is None:
                        continue
                    if name in ("coverage", "part", "id", "projection_diagnostics"):
                        texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
                        reduced = allocations.texture((res, res), texture.components, dtype=texture.dtype, filt=False)
                        allocations.blit(texture, reduced)
                    else:
                        reduced = allocations.resample(texture, (res, res))
                        if name in ("world_normal", "normal", "tangent"):
                            normalized = allocations.texture((res, res), reduced.components, dtype=reduced.dtype)
                            program = allocations.fs_program("bake-reduce-normal", S.HEADER + """
uniform sampler2D u_src; uniform int u_encoded, u_tangent;
in vec2 v_uv; out vec4 o;
void main(){vec4 s=texture(u_src,v_uv); vec3 n=u_encoded==1?s.xyz*2.0-1.0:s.xyz;
n=length(n)>1e-8?normalize(n):vec3(0,0,1); o=vec4(u_encoded==1?n*.5+.5:n,u_tangent==1?(s.w<0.0?-1.0:1.0):s.w);}
""")
                            framebuffer = allocations.ctx.framebuffer([normalized])
                            framebuffer.use()
                            allocations.ctx.viewport = (0, 0, res, res)
                            allocations.ctx.scissor = None
                            allocations.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
                            allocations.bind(program, {"u_src": (0, reduced)})
                            allocations.set(program, "u_encoded", int(name == "normal"))
                            allocations.set(program, "u_tangent", int(name == "tangent"))
                            allocations.draw_quad(program)
                            framebuffer.release()
                            reduced = normalized
                    setattr(result, fields[name], reduced)
                result.res = res
            result.settings = st
            retained = {id(texture) for texture in result.maps().values() if texture is not None}
            for texture in allocations.created:
                if id(texture) not in retained:
                    texture.release()
            return result
        except Exception:
            for texture in allocations.created:
                texture.release()
            raise
        finally:
            for target in reversed(allocations.ctx.created):
                target.release()

    def _bake(self, gm, res, ao_samples=None, ao_res=None, progress=None, subset=None, settings=None, high=None, cage=None,
              ray_correction=None, distance_correction=None):
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

        hp = self._bake_high(gm, high, pos, nrm, tan, idt, res, st, part, cage, ray_correction, distance_correction, subset) if high else None
        occluder, spos, snrm = gm, pos, nrm
        if hp is not None:
            occluder, spos, snrm = hp["gm"], hp["pos"], hp["nrm"]
        if st.enabled.get("ao", True) or st.enabled.get("thickness", True):
            ao, thick = self._bake_ao(occluder, spos, snrm, res, st, progress, frame=gm.mesh)
        else:
            ao, thick = g.texture((res, res), 4), g.texture((res, res), 4)
        for key, texture, value in (("ao", ao, 1.), ("thickness", thick, 1.), ("id", idt, 0.)):
            if not st.enabled.get(key, True):
                g.fill(texture, (value, value, value, 1.))
        normal_hp = height_hp = projection = None
        hits = 0.0
        if hp is not None:
            normal_hp, height_hp, hits = hp["normal"], hp["height"], hp["hits"]
            projection = hp.get("projection")
            if st.curv_from_normal:
                curv = self._curv_from_normal(normal_hp, curv, st.curv_normal_strength)
            for k in ("pos", "nrm", "info", "col"):
                hp[k].release()
            hp["gm"].release()
        for t in (nrm, curv, ao, thick, pos, idt, tan, normal_hp, height_hp):
            if t is not None:
                g.dilate(t, cov, st.dilation)
        return BakeSet(pos, nrm, curv, ao, cov, res, thick=thick, id=idt, part=part, settings=st,
                       tangent=tan, normal_hp=normal_hp, height_hp=height_hp, hp_hits=hits, projection=projection)

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

    def _bake_high(self, gm, high, pos, nrm, tan, idt, res, st: BakeSettings, part=None, cage=None,
                   ray_correction=None, distance_correction=None, subset=None):
        g, ctx = self.gpu, self.gpu.ctx
        from .bakecontrol import pair_sources
        hm = high if isinstance(high, Mesh) else self.merge_high(high)
        size = gm.mesh.radius * 2
        front, rear = float(st.hp_front * size), float(st.hp_rear * size)
        out = {"pos": g.texture((res, res), 4, dtype="f4"), "nrm": g.texture((res, res), 4),
               "info": g.texture((res, res), 4, dtype="f4", filt=False), "col": g.texture((res, res), 4, dtype="f1")}
        prog = g.fs_program("hp_ray", S.HP_RAY_FS)
        g.set(prog, "u_front", front)
        g.set(prog, "u_rear", rear)
        g.set(prog, "u_ignoreBack", int(bool(st.hp_ignore_backface)))
        pos.filter = nrm.filter = (moderngl.NEAREST, moderngl.NEAREST)
        cage_pos = blocked = None
        if cage is not None:
            cg = GPUMesh(g, Mesh("Cage", cage.positions, gm.mesh.normals, gm.mesh.uvs, gm.mesh.indices,
                                 tangents=gm.mesh.tangents, parts=gm.mesh.parts, colors=gm.mesh.colors,
                                 tri_material=gm.mesh.tri_material, curvature=gm.mesh.curvature))
            cage_pos = g.texture((res, res), 4, dtype="f4", filt=False)
            cfbo = ctx.framebuffer([cage_pos])
            try:
                cfbo.use()
                ctx.viewport = (0, 0, res, res)
                ctx.scissor = None
                cfbo.clear()
                cp = g.program("cage_position", S.UV_VS, S.HEADER + "in vec3 v_pos; out vec4 o; void main(){o=vec4(v_pos,1.0);}")
                if subset is None:
                    cg.render(cp)
                elif gm._subsets[subset] is not None:
                    cg._subsets[subset] = ctx.buffer(gm._subsets[subset].read())
                    cg.render(cp, subset)
            finally:
                cfbo.release()
                cg.release()
            grid = TriangleGrid(gm.mesh.positions, gm.mesh.normals, gm.mesh.indices)
            low = grid.upload(g)
            blocked = g.texture((res, res), 4, dtype="f1", filt=False)
            block_fbo = ctx.framebuffer([blocked])
            try:
                block_fbo.use()
                ctx.viewport = (0, 0, res, res)
                ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
                cp = g.fs_program("cage_block", S.CAGE_BLOCK_FS)
                g.bind(cp, {"u_pos": (0, pos), "u_nrm": (1, nrm), "u_tpos": (2, low["tri_pos"]),
                    "u_tnrm": (3, low["tri_nrm"]), "u_tcol": (4, low["tri_col"]), "u_cells": (5, low["cells"]),
                    "u_items": (6, low["items"]), "u_cage": (8, cage_pos), "u_rayCorrection": (9, ray_correction or g.black),
                    "u_distanceCorrection": (10, distance_correction or g.black)})
                for key, value in grid.uniforms().items():
                    g.set(cp, key, value)
                for key, value in {"u_front": front, "u_rear": rear, "u_bias": max(gm.mesh.radius * 1e-5, 1e-6),
                                   "u_hasCage": 1, "u_hasRayCorrection": int(ray_correction is not None),
                                   "u_hasDistanceCorrection": int(distance_correction is not None), "u_ignoreBack": 0}.items():
                    g.set(cp, key, value)
                g.draw_quad(cp)
            finally:
                block_fbo.release()
                for texture in low.values():
                    texture.release()
        fbo = ctx.framebuffer([out["pos"], out["nrm"], out["info"], out["col"]])
        fbo.use()
        ctx.viewport = (0, 0, res, res)
        ctx.scissor = None
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST)
        fbo.clear()
        active_parts = None
        if st.pairing == "name":
            active_parts = set(g.read(part)[..., 0][g.read(pos)[..., 3] > .5].astype(int).tolist())
        for part_id, sources in pair_sources(gm.mesh, high, st, active_parts):
            matched = self.merge_high(sources)
            grid = TriangleGrid(matched.positions, matched.normals, matched.indices, matched.colors)
            tex = grid.upload(g)
            try:
                g.bind(prog, {"u_pos": (0, pos), "u_nrm": (1, nrm), "u_tpos": (2, tex["tri_pos"]),
                    "u_tnrm": (3, tex["tri_nrm"]), "u_tcol": (4, tex["tri_col"]), "u_cells": (5, tex["cells"]),
                    "u_items": (6, tex["items"]), "u_part": (7, part or g.black), "u_cage": (8, cage_pos or g.black),
                    "u_rayCorrection": (9, ray_correction or g.black), "u_distanceCorrection": (10, distance_correction or g.black),
                    "u_cageBlocked": (11, blocked or g.black)})
                for key, value in grid.uniforms().items():
                    g.set(prog, key, value)
                g.set(prog, "u_partID", -1 if part_id is None else part_id)
                g.set(prog, "u_hasCage", int(cage_pos is not None))
                g.set(prog, "u_hasRayCorrection", int(ray_correction is not None))
                g.set(prog, "u_hasDistanceCorrection", int(distance_correction is not None))
                fbo.use()
                ctx.viewport = (0, 0, res, res)
                g.draw_quad(prog)
            finally:
                for texture in tex.values():
                    texture.release()
        fbo.release()
        if cage_pos is not None:
            cage_pos.release()
            blocked.release()
        pos.filter = nrm.filter = (moderngl.LINEAR, moderngl.LINEAR)
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
        if cage is not None or st.pairing != "all" or st.supersampling != 1 or st.ray_correction_pid or st.distance_correction_pid:
            colors = np.zeros((res, res, 4), np.float32)
            coverage = g.read(pos)[..., 3] > .5
            colors[..., 0] = coverage & (info[..., 1] <= .5)
            colors[..., 1] = coverage & (info[..., 1] > .5)
            crossing = coverage & (info[..., 2] < -1.5)
            colors[crossing, 0] = 0.
            colors[..., 2] = crossing
            colors[..., 3] = coverage
            out["projection"] = g.texture((res, res), 4, colors, dtype="f1", filt=False)
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
