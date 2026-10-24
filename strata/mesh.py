"""Mesh data, built-in test meshes, tangent/curvature computation and file loading."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Mesh:
    name: str
    positions: np.ndarray            # (N,3) float32
    normals: np.ndarray              # (N,3) float32
    uvs: np.ndarray                  # (N,2) float32
    indices: np.ndarray              # (M,3) uint32
    tangents: np.ndarray = None      # (N,4) float32, w = handedness
    curvature: np.ndarray = None     # (N,)  float32, 0..1, 0.5 = flat
    extra: dict = field(default_factory=dict)

    def finalize(self, normalize_size: bool = False) -> "Mesh":
        self.positions = np.ascontiguousarray(self.positions, np.float32)
        self.normals = _normalize(np.ascontiguousarray(self.normals, np.float32))
        self.uvs = np.ascontiguousarray(self.uvs, np.float32)
        self.indices = np.ascontiguousarray(self.indices, np.uint32).reshape(-1, 3)
        if normalize_size:
            lo, hi = self.positions.min(0), self.positions.max(0)
            c = (lo + hi) * 0.5
            s = 2.0 / max(float((hi - lo).max()), 1e-6)
            self.positions = ((self.positions - c) * s).astype(np.float32)
        if self.tangents is None:
            self.tangents = compute_tangents(self.positions, self.normals, self.uvs, self.indices)
        if self.curvature is None:
            self.curvature = compute_curvature(self.positions, self.normals, self.indices)
        return self

    @property
    def bounds(self):
        return self.positions.min(0), self.positions.max(0)

    @property
    def radius(self) -> float:
        lo, hi = self.bounds
        return float(np.linalg.norm(hi - lo) * 0.5)

    @property
    def center(self) -> np.ndarray:
        lo, hi = self.bounds
        return (lo + hi) * 0.5

    def interleaved(self) -> np.ndarray:
        """pos3 nrm3 uv2 tan4 curv1 -> 13 floats per vertex."""
        return np.hstack([
            self.positions, self.normals, self.uvs, self.tangents,
            self.curvature.reshape(-1, 1),
        ]).astype(np.float32)


VERTEX_FORMAT = "3f 3f 2f 4f 1f"
VERTEX_ATTRS = ("in_pos", "in_nrm", "in_uv", "in_tan", "in_curv")


# ----------------------------------------------------------------------------- helpers

def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return (v / np.maximum(n, 1e-12)).astype(np.float32)


def compute_vertex_normals(pos: np.ndarray, idx: np.ndarray) -> np.ndarray:
    tri = pos[idx]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])  # area weighted
    n = np.zeros_like(pos)
    for k in range(3):
        np.add.at(n, idx[:, k], fn)
    return _normalize(n)


def compute_tangents(pos, nrm, uv, idx) -> np.ndarray:
    p0, p1, p2 = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
    w0, w1, w2 = uv[idx[:, 0]], uv[idx[:, 1]], uv[idx[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = w1 - w0, w2 - w0
    r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(r) < 1e-12, 1e-12, r)
    r = 1.0 / r
    sdir = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r[:, None]
    tdir = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r[:, None]
    t = np.zeros_like(pos)
    b = np.zeros_like(pos)
    for k in range(3):
        np.add.at(t, idx[:, k], sdir)
        np.add.at(b, idx[:, k], tdir)
    # Gram-Schmidt
    t = t - nrm * np.sum(nrm * t, axis=1, keepdims=True)
    bad = np.linalg.norm(t, axis=1) < 1e-8
    if bad.any():  # fallback: any vector perpendicular to the normal
        alt = np.where(np.abs(nrm[bad, 1:2]) < 0.99, [[0, 1, 0]], [[1, 0, 0]])
        t[bad] = np.cross(alt, nrm[bad])
    t = _normalize(t)
    w = np.where(np.sum(np.cross(nrm, t) * b, axis=1) < 0.0, -1.0, 1.0)
    return np.hstack([t, w[:, None]]).astype(np.float32)


def compute_curvature(pos, nrm, idx, smooth_iters: int = 2) -> np.ndarray:
    """Per-vertex mean-curvature estimate mapped to 0..1 (0.5 flat, >0.5 convex).

    Vertices are welded by position first so UV seams don't show up as edges.
    """
    size = float(np.linalg.norm(pos.max(0) - pos.min(0))) or 1.0
    q = np.round(pos / (size * 1e-5)).astype(np.int64)
    _, weld, inv_count = np.unique(q, axis=0, return_inverse=True, return_counts=True)
    weld = weld.reshape(-1)
    nw = int(weld.max()) + 1
    wpos = np.zeros((nw, 3)); wnrm = np.zeros((nw, 3))
    np.add.at(wpos, weld, pos); np.add.at(wnrm, weld, nrm)
    wpos /= inv_count[:, None]
    wnrm = _normalize(wnrm)

    widx = weld[idx]
    edges = np.concatenate([widx[:, [0, 1]], widx[:, [1, 2]], widx[:, [2, 0]]])
    edges = np.concatenate([edges, edges[:, ::-1]])
    edges = edges[edges[:, 0] != edges[:, 1]]
    edges = np.unique(edges, axis=0)
    i, j = edges[:, 0], edges[:, 1]
    d = wpos[i] - wpos[j]
    l2 = np.maximum(np.sum(d * d, axis=1), 1e-12)
    k = 2.0 * np.sum(wnrm[i] * d, axis=1) / l2
    ksum = np.zeros(nw); kcnt = np.zeros(nw)
    np.add.at(ksum, i, k); np.add.at(kcnt, i, 1.0)
    kv = ksum / np.maximum(kcnt, 1.0)
    for _ in range(smooth_iters):
        s = np.zeros(nw)
        np.add.at(s, i, kv[j])
        kv = 0.5 * kv + 0.5 * s / np.maximum(kcnt, 1.0)
    c = 0.5 + 0.5 * np.tanh(kv * size * 0.08)
    return c[weld].astype(np.float32)


def _grid_indices(nu: int, nv: int, offset: int = 0) -> np.ndarray:
    """Quads for an (nu x nv) vertex grid laid out row-major (v rows of u)."""
    a = np.arange(nv - 1)[:, None] * nu + np.arange(nu - 1)[None, :]
    a = a.reshape(-1) + offset
    b, c, d = a + 1, a + nu, a + nu + 1
    return np.concatenate([np.stack([a, b, d], 1), np.stack([a, d, c], 1)])


# ----------------------------------------------------------------------------- generators

def make_sphere(radius=1.0, seg_u=128, seg_v=64) -> Mesh:
    u = np.linspace(0, 1, seg_u + 1)
    v = np.linspace(0, 1, seg_v + 1)
    uu, vv = np.meshgrid(u, v)
    th, ph = uu * 2 * np.pi, vv * np.pi
    n = np.stack([np.sin(ph) * np.cos(th), -np.cos(ph), -np.sin(ph) * np.sin(th)], -1).reshape(-1, 3)
    uv = np.stack([uu, vv], -1).reshape(-1, 2)
    return Mesh("Sphere", n * radius, n, uv, _grid_indices(seg_u + 1, seg_v + 1)).finalize()


def make_torus(R=0.75, r=0.3, seg_u=128, seg_v=64) -> Mesh:
    u = np.linspace(0, 1, seg_u + 1)
    v = np.linspace(0, 1, seg_v + 1)
    uu, vv = np.meshgrid(u, v)
    a, b = uu * 2 * np.pi, vv * 2 * np.pi
    n = np.stack([np.cos(b) * np.cos(a), np.sin(b), -np.cos(b) * np.sin(a)], -1)
    c = np.stack([np.cos(a) * R, np.zeros_like(a), -np.sin(a) * R], -1)
    p = c + n * r
    uv = np.stack([uu, vv], -1).reshape(-1, 2)
    return Mesh("Torus", p.reshape(-1, 3), n.reshape(-1, 3), uv,
                _grid_indices(seg_u + 1, seg_v + 1)).finalize()


def make_rounded_cube(half=0.85, bevel=0.1, n_bevel=8, n_flat=24) -> Mesh:
    """Cube with rounded edges; each face gets a cell of a 3x2 UV atlas."""
    inner = half - bevel
    coords = np.concatenate([
        np.linspace(-half, -inner, n_bevel, endpoint=False),
        np.linspace(-inner, inner, n_flat, endpoint=False),
        np.linspace(inner, half, n_bevel + 1),
    ])
    n = len(coords)
    aa, bb = np.meshgrid(coords, coords)
    # (axis, sign, u-axis, v-axis) chosen so faces read upright and outward
    faces = [
        (0, +1, (2, -1), (1, +1)), (0, -1, (2, +1), (1, +1)),
        (1, +1, (0, +1), (2, -1)), (1, -1, (0, +1), (2, +1)),
        (2, +1, (0, +1), (1, +1)), (2, -1, (0, -1), (1, +1)),
    ]
    pad = 0.02
    P, N, UV, I = [], [], [], []
    for fi, (ax, sg, (ua, us), (va, vs)) in enumerate(faces):
        q = np.zeros((n, n, 3))
        q[..., ax] = sg * half
        q[..., ua] = aa * us
        q[..., va] = bb * vs
        ins = np.clip(q, -inner, inner)
        nd = _normalize(q - ins)
        p = ins + nd * bevel
        cx, cy = fi % 3, fi // 3
        cu = (aa / half * 0.5 + 0.5)
        cv = (bb / half * 0.5 + 0.5)
        cell = 1.0 / 3.0, 0.5
        uv = np.stack([(cx + pad + cu * (1 - 2 * pad)) * cell[0],
                       (cy + pad * 1.5 + cv * (1 - 3 * pad)) * cell[1]], -1)
        # winding: make sure triangles face outward
        idx = _grid_indices(n, n, len(P) * n * n)
        P.append(p.reshape(-1, 3)); N.append(nd.reshape(-1, 3)); UV.append(uv.reshape(-1, 2))
        I.append(idx)
    P, N, UV = np.concatenate(P), np.concatenate(N), np.concatenate(UV)
    I = np.concatenate(I)
    I = _fix_winding(P, N, I)
    return Mesh("Rounded Cube", P, N, UV, I).finalize()


def _fix_winding(P, N, I):
    tri = P[I]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    flip = np.sum(fn * N[I].mean(1), axis=1) < 0
    I = I.copy()
    I[flip] = I[flip][:, [0, 2, 1]]
    return I


def _chaikin(pts: np.ndarray, iters=3) -> np.ndarray:
    for _ in range(iters):
        q = 0.75 * pts[:-1] + 0.25 * pts[1:]
        r = 0.25 * pts[:-1] + 0.75 * pts[1:]
        mid = np.empty((len(q) * 2, 2)); mid[0::2] = q; mid[1::2] = r
        pts = np.vstack([pts[:1], mid, pts[-1:]])
    return pts


def make_lathe(profile, name="Canister", seg_u=128) -> Mesh:
    """Revolve a (radius, height) polyline around Y. Profile runs bottom-centre -> top-centre."""
    prof = _chaikin(np.asarray(profile, float), 3)
    # resample by arc length so texel density is even along the profile
    seg = np.linalg.norm(np.diff(prof, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], 160)
    prof = np.stack([np.interp(t, s, prof[:, 0]), np.interp(t, s, prof[:, 1])], 1)
    prof[0, 0] = 0.0; prof[-1, 0] = 0.0
    d = np.gradient(prof, axis=0)
    n2 = _normalize(np.stack([d[:, 1], -d[:, 0]], 1))  # outward for bottom->top
    v = t / t[-1]
    u = np.linspace(0, 1, seg_u + 1)
    uu, vi = np.meshgrid(u, np.arange(len(prof)))
    a = uu * 2 * np.pi
    r, y = prof[vi, 0], prof[vi, 1]
    p = np.stack([r * np.cos(a), y, -r * np.sin(a)], -1)
    nn = np.stack([n2[vi, 0] * np.cos(a), n2[vi, 1], -n2[vi, 0] * np.sin(a)], -1)
    uv = np.stack([uu, v[vi]], -1)
    P, N, UV = p.reshape(-1, 3), nn.reshape(-1, 3), uv.reshape(-1, 2)
    I = _grid_indices(seg_u + 1, len(prof))
    tri = P[I]
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    I = I[area > 1e-12]
    I = _fix_winding(P, N, I)
    return Mesh(name, P, N, UV, I).finalize()


def make_canister() -> Mesh:
    prof = [
        (0.0, -1.0), (0.62, -1.0), (0.70, -0.94), (0.70, -0.62), (0.66, -0.58),
        (0.66, -0.50), (0.70, -0.46), (0.70, 0.40), (0.66, 0.44), (0.66, 0.52),
        (0.70, 0.56), (0.70, 0.78), (0.58, 0.86), (0.30, 0.88), (0.28, 0.96),
        (0.30, 1.0), (0.0, 1.0),
    ]
    return make_lathe(prof, "Canister")


BUILTIN_MESHES = {
    "Rounded Cube": make_rounded_cube,
    "Sphere": make_sphere,
    "Torus": make_torus,
    "Canister": make_canister,
}


# ----------------------------------------------------------------------------- loading

def load_mesh(path: str) -> Mesh:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        return load_obj(path)
    if ext in (".fbx", ".gltf", ".glb", ".dae", ".3ds", ".blend"):
        return load_with_assimp(path)
    raise ValueError(f"Unsupported mesh format: {ext}")


def load_obj(path: str) -> Mesh:
    vs, vts, vns, faces = [], [], [], []
    with open(path, "r", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                vs.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("vt "):
                vts.append([float(x) for x in line.split()[1:3]])
            elif line.startswith("vn "):
                vns.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("f "):
                corners = []
                for tok in line.split()[1:]:
                    parts = tok.split("/") + ["", ""]
                    vi = int(parts[0]); ti = int(parts[1]) if parts[1] else 0
                    ni = int(parts[2]) if parts[2] else 0
                    corners.append((vi, ti, ni))
                for k in range(1, len(corners) - 1):  # fan triangulation
                    faces.append((corners[0], corners[k], corners[k + 1]))
    if not vts:
        raise ValueError("This mesh has no UVs - unwrap it before texturing.")
    vs, vts = np.array(vs, np.float32), np.array(vts, np.float32)
    vns = np.array(vns, np.float32) if vns else None

    def fix(i, n):  # OBJ indices are 1-based, negatives are relative
        return i - 1 if i > 0 else n + i

    key_to_index, P, T, Nn, I = {}, [], [], [], []
    for tri in faces:
        out = []
        for (vi, ti, ni) in tri:
            key = (vi, ti, ni)
            if key not in key_to_index:
                key_to_index[key] = len(P)
                P.append(vs[fix(vi, len(vs))])
                T.append(vts[fix(ti, len(vts))] if ti else (0.0, 0.0))
                Nn.append(vns[fix(ni, len(vns))] if (ni and vns is not None) else (0.0, 0.0, 0.0))
            out.append(key_to_index[key])
        I.append(out)
    P, T, Nn, I = np.array(P), np.array(T), np.array(Nn), np.array(I, np.uint32)
    if vns is None or not np.any(Nn):
        Nn = compute_vertex_normals(P, I)
    name = os.path.splitext(os.path.basename(path))[0]
    return Mesh(name, P, Nn, T, I).finalize(normalize_size=True)


def load_with_assimp(path: str) -> Mesh:
    try:
        import assimp_py
    except ImportError as e:
        raise RuntimeError("FBX/glTF import needs the 'assimp-py' package: pip install assimp-py") from e
    flags = (assimp_py.Process_Triangulate | assimp_py.Process_JoinIdenticalVertices
             | assimp_py.Process_GenSmoothNormals | assimp_py.Process_PreTransformVertices
             | assimp_py.Process_SortByPType)
    scene = assimp_py.import_file(path, flags)
    P, N, T, I = [], [], [], []
    base = 0
    for m in scene.meshes:
        if not m.texcoords or len(m.texcoords[0]) == 0 or len(m.indices) == 0:
            continue
        pos = np.asarray(m.vertices, np.float32).reshape(-1, 3)
        nrm = np.asarray(m.normals, np.float32).reshape(-1, 3)
        ncomp = m.num_uv_components[0] if hasattr(m, "num_uv_components") else 2
        ncomp = int(ncomp) or 2
        uv = np.asarray(m.texcoords[0], np.float32).reshape(-1, ncomp)[:, :2]
        idx = np.asarray(m.indices, np.uint32).reshape(-1, 3)
        if len(nrm) != len(pos):
            nrm = compute_vertex_normals(pos, idx)
        P.append(pos); N.append(nrm); T.append(uv); I.append(idx + base)
        base += len(pos)
    if not P:
        raise ValueError("No mesh with UVs found in file - unwrap it before texturing.")
    name = os.path.splitext(os.path.basename(path))[0]
    return Mesh(name, np.concatenate(P), np.concatenate(N), np.concatenate(T),
                np.concatenate(I)).finalize(normalize_size=True)
