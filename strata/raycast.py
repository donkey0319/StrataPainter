"""Uniform-grid acceleration structure for ray casting meshes on the GPU (GL 3.3, no compute).

The grid is built on the CPU with numpy and uploaded as float textures:

  tri_pos   3 texels per triangle: vertex positions
  tri_nrm   3 texels per triangle: vertex normals
  tri_col   3 texels per triangle: vertex colours (ID transfer)
  cells     1 texel per cell: (first index into `items`, count)
  items     triangle ids, grouped by cell

Every texture is TEX_W texels wide; index i lives at (i % TEX_W, i // TEX_W). A fragment shader walks
the grid with a 3D DDA (see shaders.RAYCAST_LIB).
"""
from __future__ import annotations

import numpy as np

TEX_W = 4096


def _pack(arr: np.ndarray, comps: int) -> tuple[np.ndarray, tuple]:
    """(N, comps) -> (rows, TEX_W, comps) zero padded."""
    n = len(arr)
    rows = max((n + TEX_W - 1) // TEX_W, 1)
    out = np.zeros((rows * TEX_W, comps), np.float32)
    out[:n] = arr.reshape(n, comps)
    return out.reshape(rows, TEX_W, comps), (TEX_W, rows)


class TriangleGrid:
    def __init__(self, positions, normals, indices, colors=None, cells_per_tri=0.5, max_dim=160):
        pos = np.asarray(positions, np.float32)
        idx = np.asarray(indices, np.int64).reshape(-1, 3)
        tri = pos[idx]                                       # (M, 3, 3)
        m = len(idx)
        self.n_tris = m
        lo, hi = pos.min(0), pos.max(0)
        ext = np.maximum(hi - lo, 1e-6)
        pad = ext.max() * 1e-3
        lo, hi = lo - pad, hi + pad
        ext = hi - lo
        target = max(m * cells_per_tri, 1)
        unit = (np.prod(ext) / target) ** (1 / 3)
        dims = np.clip(np.ceil(ext / unit), 1, max_dim).astype(np.int64)
        self.lo, self.hi, self.dims = lo, hi, dims
        self.cell = ext / dims
        tmin = np.floor((tri.min(1) - lo) / self.cell).astype(np.int64)
        tmax = np.floor((tri.max(1) - lo) / self.cell).astype(np.int64)
        tmin = np.clip(tmin, 0, dims - 1)
        tmax = np.clip(tmax, 0, dims - 1)
        span = tmax - tmin + 1
        count = span.prod(1)
        total = int(count.sum())
        tid = np.repeat(np.arange(m), count)
        start = np.repeat(np.cumsum(count) - count, count)
        k = np.arange(total) - start
        sx, sy = span[tid, 0], span[tid, 1]
        cx = tmin[tid, 0] + k % sx
        cy = tmin[tid, 1] + (k // sx) % sy
        cz = tmin[tid, 2] + k // (sx * sy)
        cell_id = cx + dims[0] * (cy + dims[1] * cz)
        order = np.argsort(cell_id, kind="stable")
        cell_id, tid = cell_id[order], tid[order]
        n_cells = int(dims.prod())
        first = np.searchsorted(cell_id, np.arange(n_cells))
        last = np.searchsorted(cell_id, np.arange(n_cells), side="right")
        self.cells = np.stack([first, last - first], 1).astype(np.float32)
        self.items = tid.astype(np.float32)
        self.max_per_cell = int((last - first).max()) if n_cells else 0
        nrm = np.asarray(normals, np.float32)[idx]
        col = (np.ones((m, 3, 4), np.float32) if colors is None
               else np.asarray(colors, np.float32).reshape(-1, 4)[idx])
        self.tri_pos = tri.reshape(-1, 3)
        self.tri_nrm = nrm.reshape(-1, 3)
        self.tri_col = col.reshape(-1, 4)

    def upload(self, gpu) -> dict:
        """Create the GPU textures (caller releases them)."""
        out = {}
        for name, arr, comps in (("tri_pos", self.tri_pos, 3), ("tri_nrm", self.tri_nrm, 3),
                                 ("tri_col", self.tri_col, 4), ("cells", self.cells, 2),
                                 ("items", self.items.reshape(-1, 1), 1)):
            data, size = _pack(arr, comps)
            out[name] = gpu.texture(size, comps, data, dtype="f4", filt=False)
        return out

    def uniforms(self) -> dict:
        return {"u_W": TEX_W, "u_G": tuple(int(d) for d in self.dims),
                "u_lo": tuple(map(float, self.lo)), "u_hi": tuple(map(float, self.hi)),
                "u_cell": tuple(map(float, self.cell)),
                "u_maxSteps": int(self.dims.sum() * 2 + 4)}

    # ---- CPU reference (tests, picking)
    def raycast(self, origin, direction, tmax=np.inf):
        """Nearest hit (t, triangle, barycentrics) along a ray, brute force over the grid cells
        the ray passes through. Slow; meant for tests and occasional queries."""
        o = np.asarray(origin, float)
        d = np.asarray(direction, float)
        d = d / np.linalg.norm(d)
        best = (np.inf, -1, None)
        steps = int(np.linalg.norm(self.hi - self.lo) / self.cell.min() * 2) + 2
        seen = set()
        for i in range(steps):
            t = i * self.cell.min() * 0.5
            if t > tmax + self.cell.max():
                break
            p = o + d * t
            c = np.floor((p - self.lo) / self.cell).astype(int)
            if np.any(c < 0) or np.any(c >= self.dims):
                continue
            ci = int(c[0] + self.dims[0] * (c[1] + self.dims[1] * c[2]))
            if ci in seen:
                continue
            seen.add(ci)
            f, n = self.cells[ci]
            for tri in self.items[int(f):int(f + n)].astype(int):
                v0, v1, v2 = self.tri_pos[tri * 3:tri * 3 + 3]
                e1, e2 = v1 - v0, v2 - v0
                pv = np.cross(d, e2)
                det = e1 @ pv
                if abs(det) < 1e-12:
                    continue
                tv = o - v0
                u = tv @ pv / det
                qv = np.cross(tv, e1)
                v = d @ qv / det
                tt = e2 @ qv / det
                if u >= 0 and v >= 0 and u + v <= 1 and 0 <= tt <= tmax and tt < best[0]:
                    best = (tt, tri, (u, v))
        return best
