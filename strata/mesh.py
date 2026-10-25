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
    parts: np.ndarray = None         # (N,2) float32: mesh part (object) id, material id
    colors: np.ndarray = None        # (N,4) float32 vertex colours (ID baking)
    tri_material: np.ndarray = None  # (M,) int32 material id per triangle -> texture set
    material_names: list = None
    part_names: list = None

    def finalize(self, normalize_size: bool = False, xform=None, light: bool = False) -> "Mesh":
        """Clean arrays and compute derived data. normalize_size: centre and scale to a 2-unit box
        (the transform is kept in extra["xform"] = (centre, scale) so a matching high-poly mesh can
        reuse it via xform=). light: skip tangents/curvature (high-poly bake sources)."""
        self.positions = np.ascontiguousarray(self.positions, np.float32)
        self.normals = _normalize(np.ascontiguousarray(self.normals, np.float32))
        self.uvs = np.ascontiguousarray(self.uvs, np.float32)
        self.indices = np.ascontiguousarray(self.indices, np.uint32).reshape(-1, 3)
        if xform is None and normalize_size:
            lo, hi = self.positions.min(0), self.positions.max(0)
            xform = ((lo + hi) * 0.5, 2.0 / max(float((hi - lo).max()), 1e-6))
        if xform is not None:
            c, s = np.asarray(xform[0], np.float32), float(xform[1])
            self.positions = ((self.positions - c) * s).astype(np.float32)
            self.extra["xform"] = (c.tolist(), s)
        if light:
            if self.tangents is None:
                self.tangents = np.zeros((len(self.positions), 4), np.float32)
            if self.curvature is None:
                self.curvature = np.full(len(self.positions), 0.5, np.float32)
        if self.tangents is None:
            self.tangents = compute_tangents(self.positions, self.normals, self.uvs, self.indices)
        if self.curvature is None:
            self.curvature = compute_curvature(self.positions, self.normals, self.indices)
        n, m = len(self.positions), len(self.indices)
        if self.tri_material is None:
            if self.parts is not None:
                self.tri_material = np.asarray(self.parts, np.float32).reshape(-1, 2)[self.indices[:, 0], 1]
            else:
                self.tri_material = np.zeros(m, np.int32)
        self.tri_material = np.ascontiguousarray(self.tri_material, np.int32).reshape(-1)
        if self.parts is None:
            self.parts = np.zeros((n, 2), np.float32)
            # vertices shared between materials take the first triangle's material
            self.parts[self.indices[:, 0], 1] = self.tri_material
            self.parts[self.indices[:, 1], 1] = self.tri_material
            self.parts[self.indices[:, 2], 1] = self.tri_material
        self.parts = np.ascontiguousarray(self.parts, np.float32).reshape(n, 2)
        if self.colors is None:
            self.colors = np.ones((n, 4), np.float32)
        self.colors = np.ascontiguousarray(self.colors, np.float32).reshape(n, 4)
        nmat = int(self.tri_material.max()) + 1 if m else 1
        if not self.material_names or len(self.material_names) < nmat:
            names = list(self.material_names or [])
            names += [f"Material {i}" if i else "Default" for i in range(len(names), nmat)]
            self.material_names = names
        npart = int(self.parts[:, 0].max()) + 1 if n else 1
        if not self.part_names or len(self.part_names) < npart:
            names = list(self.part_names or [])
            names += [f"Part {i}" for i in range(len(names), npart)]
            self.part_names = names
        self._topo = None
        return self

    @property
    def topology(self) -> "Topology":
        if getattr(self, "_topo", None) is None:
            self._topo = Topology(self)
        return self._topo

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
        """pos3 nrm3 uv2 tan4 curv1 part2 col4 -> 19 floats per vertex."""
        return np.hstack([
            self.positions, self.normals, self.uvs, self.tangents,
            self.curvature.reshape(-1, 1), self.parts, self.colors,
        ]).astype(np.float32)


VERTEX_FORMAT = "3f 3f 2f 4f 1f 2f 4f"
VERTEX_ATTRS = ("in_pos", "in_nrm", "in_uv", "in_tan", "in_curv", "in_part", "in_vcol")


class Topology:
    """Triangle adjacency used by polygon fill and selection tools."""

    def __init__(self, mesh: Mesh):
        self.mesh = mesh
        idx = mesh.indices.astype(np.int64)
        m = len(idx)
        self.n_tris = m
        # UV islands: triangles connected through shared vertex indices (seams split vertices)
        self.uv_island = _components(idx, len(mesh.positions))
        # geometric connectivity: weld by position so seams don't split
        pos = mesh.positions
        size = float(np.linalg.norm(pos.max(0) - pos.min(0))) or 1.0
        q = np.round(pos / (size * 1e-5)).astype(np.int64)
        _, weld = np.unique(q, axis=0, return_inverse=True)
        widx = weld.reshape(-1)[idx]
        self.welded = widx
        self.wpos = np.zeros((int(weld.max()) + 1 if weld.size else 0, 3))
        self.wpos[weld.reshape(-1)] = pos
        tri = pos[idx]
        fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        self.area = np.linalg.norm(fn, axis=1) * 0.5
        self.face_normal = fn / np.maximum(self.area[:, None] * 2, 1e-20)
        uv = mesh.uvs[idx]
        d1, d2 = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
        self.uv_area = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) * 0.5
        # edge -> triangles (welded)
        e = np.concatenate([widx[:, [0, 1]], widx[:, [1, 2]], widx[:, [2, 0]]])
        e.sort(axis=1)
        t = np.concatenate([np.arange(m)] * 3)
        order = np.lexsort((e[:, 1], e[:, 0]))
        e, t = e[order], t[order]
        same = np.all(e[1:] == e[:-1], axis=1)
        self.edge_pairs = np.stack([t[:-1][same], t[1:][same]], 1)   # adjacent triangle pairs
        self.parts = mesh.parts[idx[:, 0], 0].astype(np.int64)

    def wire_segments(self, tris=None, angle_deg: float = 1.0):
        """Wireframe for polygon fill, as (inner, outline) line segments, float32 arrays (N, 2, 3).
        outline: polygon borders (edges between faces that aren't coplanar), open borders and creases;
        inner: triangle edges inside a flat polygon (e.g. the diagonal of a quad).
        tris: optional triangle ids to restrict to (one texture set)."""
        w = self.welded
        t = np.arange(self.n_tris)
        if tris is not None:
            t = np.unique(np.asarray(tris, np.int64))
            w = w[t]
        if len(t) == 0:
            z = np.zeros((0, 2, 3), np.float32)
            return z, z
        nw = max(len(self.wpos), 1)
        e = np.concatenate([w[:, [0, 1]], w[:, [1, 2]], w[:, [2, 0]]])
        e.sort(axis=1)
        k = e[:, 0] * nw + e[:, 1]
        et = np.concatenate([t] * 3)
        order = np.argsort(k, kind="stable")
        ks, ts = k[order], et[order]
        same = ks[1:] == ks[:-1]
        a, b = ts[:-1][same], ts[1:][same]
        flat = np.sum(self.face_normal[a] * self.face_normal[b], axis=1) >= np.cos(np.radians(angle_deg))
        uk, cnt = np.unique(k, return_counts=True)
        inner_mask = np.isin(uk, ks[:-1][same][flat]) & (cnt == 2)

        def seg(keys):
            return np.stack([self.wpos[keys // nw], self.wpos[keys % nw]], 1).astype(np.float32)
        return seg(uk[inner_mask]), seg(uk[~inner_mask])

    def uv_scale(self, tri: int) -> float:
        """World units per UV unit around a triangle."""
        a, u = self.area[tri], self.uv_area[tri]
        return float(np.sqrt(a / u)) if u > 1e-14 else 1.0

    def expand(self, tris, mode: int, angle_deg: float = 1.0) -> np.ndarray:
        """mode 0 triangle, 1 polygon (coplanar neighbours), 2 UV island, 3 mesh part, 4 material."""
        tris = np.unique(np.asarray(tris, np.int64))
        tris = tris[(tris >= 0) & (tris < self.n_tris)]
        if mode == 0 or tris.size == 0:
            return tris
        if mode == 2:
            return np.nonzero(np.isin(self.uv_island, self.uv_island[tris]))[0]
        if mode == 3:
            return np.nonzero(np.isin(self.parts, self.parts[tris]))[0]
        if mode == 4:
            mat = self.mesh.tri_material
            return np.nonzero(np.isin(mat, mat[tris]))[0]
        # polygon: flood across edges whose faces are (nearly) coplanar
        cos_t = np.cos(np.radians(angle_deg))
        a, b = self.edge_pairs[:, 0], self.edge_pairs[:, 1]
        flat = np.sum(self.face_normal[a] * self.face_normal[b], axis=1) >= cos_t
        lab = _components(np.stack([a[flat], b[flat]], 1), self.n_tris, edges=True)
        return np.nonzero(np.isin(lab, lab[tris]))[0]


def _components(idx: np.ndarray, n: int, edges=False) -> np.ndarray:
    """Connected components. idx: triangles (M,3) over n vertices -> label per triangle;
    or with edges=True an (E,2) list of node pairs over n nodes -> label per node."""
    parent = np.arange(n)

    def find_all(p):
        while True:
            q = p[p]
            if np.array_equal(q, p):
                return p
            p = q

    pairs = idx if edges else np.concatenate([idx[:, [0, 1]], idx[:, [1, 2]]])
    if len(pairs):
        for _ in range(4096):
            r = find_all(parent)
            a, b = r[pairs[:, 0]], r[pairs[:, 1]]
            diff = a != b
            if not diff.any():
                break
            lo, hi = np.minimum(a[diff], b[diff]), np.maximum(a[diff], b[diff])
            np.minimum.at(parent, hi, lo)
        parent = find_all(parent)
    return parent if edges else parent[idx[:, 0]]


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
    parts = np.repeat(np.arange(6, dtype=np.float32), n * n)
    P, N, UV = np.concatenate(P), np.concatenate(N), np.concatenate(UV)
    I = np.concatenate(I)
    I = _fix_winding(P, N, I)
    PM = np.stack([parts, np.zeros_like(parts)], 1)
    names = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
    return Mesh("Rounded Cube", P, N, UV, I, parts=PM, part_names=names).finalize()


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


def combine(meshes, name="Combined", offsets=None, materials=None) -> Mesh:
    """Merge meshes into one; each input becomes a mesh part, and (by default) its own
    material / texture set. offsets: optional per-mesh translation."""
    P, N, T, I, PM, TM, C = [], [], [], [], [], [], []
    base = 0
    mats = materials or list(range(len(meshes)))
    for k, m in enumerate(meshes):
        off = np.zeros(3) if offsets is None else np.asarray(offsets[k], float)
        P.append(m.positions + off); N.append(m.normals); T.append(m.uvs); C.append(m.colors)
        I.append(m.indices + base)
        PM.append(np.tile(np.array([[k, mats[k]]], np.float32), (len(m.positions), 1)))
        TM.append(np.full(len(m.indices), mats[k], np.int32))
        base += len(m.positions)
    nm = max(mats) + 1
    return Mesh(name, np.concatenate(P), np.concatenate(N), np.concatenate(T), np.concatenate(I),
                parts=np.concatenate(PM), colors=np.concatenate(C), tri_material=np.concatenate(TM),
                material_names=[meshes[mats.index(i)].name for i in range(nm)],
                part_names=[m.name for m in meshes]).finalize()


def make_sphere_and_torus() -> Mesh:
    """Two objects, two materials: a quick way to try texture sets."""
    return combine([make_sphere(0.55, 96, 48), make_torus(0.9, 0.2, 128, 48)], "Sphere + Torus")


BUILTIN_MESHES = {
    "Rounded Cube": make_rounded_cube,
    "Sphere": make_sphere,
    "Torus": make_torus,
    "Canister": make_canister,
    "Sphere + Torus (2 texture sets)": make_sphere_and_torus,
}


# ----------------------------------------------------------------------------- loading

def load_mesh(path: str, xform=None, light=False, require_uvs=True) -> Mesh:
    """Load OBJ / FBX / glTF / ... Meshes are normalised to a 2-unit box unless xform=(centre, scale)
    is given (use the low-poly mesh's mesh.extra["xform"] for its high-poly)."""
    ext = os.path.splitext(path)[1].lower()
    kw = {"xform": xform, "light": light, "require_uvs": require_uvs}
    if ext == ".obj":
        return load_obj(path, **kw)
    if ext in (".fbx", ".gltf", ".glb", ".dae", ".3ds", ".blend", ".ply", ".stl", ".abc", ".usd", ".usda", ".usdc"):
        return load_with_assimp(path, **kw)
    raise ValueError(f"Unsupported mesh format: {ext}")


def load_high_poly(path: str, low: Mesh) -> Mesh:
    """Load a high-poly bake source in the low-poly mesh's normalised space (UVs not needed)."""
    return load_mesh(path, xform=low.extra.get("xform"), light=True, require_uvs=False)


def load_obj(path: str, xform=None, light=False, require_uvs=True) -> Mesh:
    vs, vts, vns, faces = [], [], [], []
    part_ids, mats = {"": 0}, {}
    cur_part, cur_mat = 0, 0
    with open(path, "r", errors="ignore") as f:
        for line in f:
            if line.startswith(("o ", "g ")):
                nm = line[2:].strip()
                cur_part = part_ids.setdefault(nm, len(part_ids))
            elif line.startswith("usemtl"):
                nm = line[6:].strip()
                cur_mat = mats.setdefault(nm, len(mats))
            elif line.startswith("v "):
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
                    faces.append((corners[0], corners[k], corners[k + 1], cur_part, cur_mat))
    if not vts:
        if require_uvs:
            raise ValueError("This mesh has no UVs - unwrap it before texturing.")
        vts = [(0.0, 0.0)]
    vs, vts = np.array(vs, np.float32), np.array(vts, np.float32)
    vns = np.array(vns, np.float32) if vns else None

    def fix(i, n):  # OBJ indices are 1-based, negatives are relative
        return i - 1 if i > 0 else n + i

    key_to_index, P, T, Nn, I, PM, TM = {}, [], [], [], [], [], []
    for (*tri, part, mat) in faces:
        out = []
        for (vi, ti, ni) in tri:
            key = (vi, ti, ni, part, mat)
            if key not in key_to_index:
                key_to_index[key] = len(P)
                P.append(vs[fix(vi, len(vs))])
                T.append(vts[fix(ti, len(vts))] if ti else (0.0, 0.0))
                Nn.append(vns[fix(ni, len(vns))] if (ni and vns is not None) else (0.0, 0.0, 0.0))
                PM.append((part, mat))
            out.append(key_to_index[key])
        I.append(out)
        TM.append(mat)
    P, T, Nn, I = np.array(P), np.array(T), np.array(Nn), np.array(I, np.uint32)
    PM = np.array(PM, np.float32)
    # renumber parts densely (the implicit "" part may be unused)
    used = np.unique(PM[:, 0]).astype(int)
    remap = {int(u): i for i, u in enumerate(used)}
    PM[:, 0] = [remap[int(p)] for p in PM[:, 0]]
    inv_parts = {v: k for k, v in part_ids.items()}
    part_names = [inv_parts[int(u)] or f"Part {i}" for i, u in enumerate(used)]
    mat_names = [k for k, _ in sorted(mats.items(), key=lambda kv: kv[1])] or ["Default"]
    if vns is None or not np.any(Nn):
        Nn = compute_vertex_normals(P, I)
    name = os.path.splitext(os.path.basename(path))[0]
    return Mesh(name, P, Nn, T, I, parts=PM, tri_material=np.array(TM, np.int32),
                material_names=mat_names, part_names=part_names).finalize(normalize_size=True, xform=xform, light=light)


def load_with_assimp(path: str, xform=None, light=False, require_uvs=True) -> Mesh:
    try:
        import assimp_py
    except ImportError as e:
        raise RuntimeError("FBX/glTF import needs the 'assimp-py' package: pip install assimp-py") from e
    flags = (assimp_py.Process_Triangulate | assimp_py.Process_JoinIdenticalVertices
             | assimp_py.Process_GenSmoothNormals | assimp_py.Process_PreTransformVertices
             | assimp_py.Process_SortByPType)
    scene = assimp_py.import_file(path, flags)
    P, N, T, I, PM, TM, C = [], [], [], [], [], [], []
    part_names, mat_ids = [], {}
    mat_names = []
    for i, md in enumerate(getattr(scene, "materials", []) or []):
        nm = ""
        if isinstance(md, dict):
            for k, v in md.items():
                if "name" in str(k).lower():
                    nm = str(v); break
        mat_names.append(nm or f"Material {i}")
    base = 0
    for m in scene.meshes:
        if len(m.indices) == 0:
            continue
        has_uv = bool(m.texcoords) and len(m.texcoords[0]) > 0
        if not has_uv and require_uvs:
            continue
        pos = np.asarray(m.vertices, np.float32).reshape(-1, 3)
        nrm = np.asarray(m.normals, np.float32).reshape(-1, 3)
        ncomp = getattr(m, "num_uv_components", 2)
        if isinstance(ncomp, (list, tuple)) or hasattr(ncomp, "__getitem__"):
            ncomp = ncomp[0] if len(ncomp) else 2
        ncomp = int(ncomp) or 2
        uv = np.asarray(m.texcoords[0], np.float32).reshape(-1, ncomp)[:, :2] if has_uv \
            else np.zeros((len(pos), 2), np.float32)
        idx = np.asarray(m.indices, np.uint32).reshape(-1, 3)
        if len(nrm) != len(pos):
            nrm = compute_vertex_normals(pos, idx)
        src_mat = int(getattr(m, "material_index", 0) or 0)
        mat = mat_ids.setdefault(src_mat, len(mat_ids))
        part = len(part_names)
        part_names.append(getattr(m, "name", "") or f"Part {part}")
        col = np.ones((len(pos), 4), np.float32)
        cols = getattr(m, "colors", None)
        if cols and len(cols) and cols[0] is not None:
            c0 = np.asarray(cols[0], np.float32).reshape(-1)
            if c0.size == len(pos) * 4:
                col = c0.reshape(-1, 4)
        P.append(pos); N.append(nrm); T.append(uv); I.append(idx + base); C.append(col)
        PM.append(np.tile(np.array([[part, mat]], np.float32), (len(pos), 1)))
        TM.append(np.full(len(idx), mat, np.int32))
        base += len(pos)
    if not P:
        raise ValueError("No mesh with UVs found in file - unwrap it before texturing.")
    name = os.path.splitext(os.path.basename(path))[0]
    names = [mat_names[s] if s < len(mat_names) else f"Material {s}"
             for s, _ in sorted(mat_ids.items(), key=lambda kv: kv[1])]
    return Mesh(name, np.concatenate(P), np.concatenate(N), np.concatenate(T),
                np.concatenate(I), parts=np.concatenate(PM), colors=np.concatenate(C),
                tri_material=np.concatenate(TM), material_names=names,
                part_names=part_names).finalize(normalize_size=True, xform=xform, light=light)
