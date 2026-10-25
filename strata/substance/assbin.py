"""Reader for the mesh embedded in Substance Painter projects (paint/scene.assbin).

Painter stores the imported mesh as an Assimp-style binary dump, but in its own variant that
current Assimp refuses ("Invalid version"). Layout, as observed in Painter 8 - 12 projects:

  512-byte header ("ASSIMP.binary-dump.<date>", version, source path, ...)
  scene  : u64 size (includes itself) | u32 flags | node tree record | u32 nMeshes | mesh records |
           u32 nMaterials | material records | ...
  record : u64 size (includes itself) followed by its content, so unknown records can be skipped
  mesh   : str name | u32 primitive types | u32 material index | u32 component flags |
           vectors (u32 count + items) for positions, normals, tangents + bitangents,
           colours (flag 0x10000 << n), uv sets (flag 0x100 << n: u32 components + vec3 list) |
           u32 nFaces | per face: u32 flag, u32 n, n x u32 indices
  string : u32 length + bytes

Vertices are already pre-transformed into object space (Painter keeps the node transforms only as
metadata), so the node tree is skipped.
"""
from __future__ import annotations

import struct

import numpy as np

HEADER = 512
MAGIC = b"ASSIMP.binary-dump."


class AssbinError(ValueError):
    pass


class _R:
    def __init__(self, d, p=0):
        self.d, self.p = d, p

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]; self.p += 4; return v

    def u64(self):
        v = struct.unpack_from("<Q", self.d, self.p)[0]; self.p += 8; return v

    def string(self):
        n = self.u32()
        if n > 1 << 20:
            raise AssbinError("bad string length")
        s = bytes(self.d[self.p:self.p + n]); self.p += n
        return s.split(b"\0")[0].decode("utf-8", "replace")

    def vecs(self, k):
        n = self.u32()
        nbytes = n * k * 4
        if self.p + nbytes > len(self.d):
            raise AssbinError("vector runs past end of data")
        a = np.frombuffer(self.d, np.float32, n * k, self.p).reshape(n, k).copy()
        self.p += nbytes
        return a


def read_scene(raw: bytes):
    """Return (meshes, material_names). meshes: list of dicts with name, material, positions,
    normals, uvs, indices (triangles only)."""
    if not raw.startswith(MAGIC):
        raise AssbinError("not an Assimp binary dump")
    if raw[HEADER + 0:HEADER + 1] == b"":
        raise AssbinError("empty scene")
    compressed = struct.unpack_from("<H", raw, 62)[0]
    if compressed:
        import zlib
        size = struct.unpack_from("<I", raw, HEADER)[0]
        data = zlib.decompress(raw[HEADER + 4:])
        if len(data) != size:
            raise AssbinError("decompressed size mismatch")
    else:
        data = raw[HEADER:]
    r = _R(memoryview(data))
    r.u64()                      # scene size
    r.u32()                      # scene flags
    start = r.p
    r.p = start + r.u64()        # skip node tree (vertices are pre-transformed)
    meshes = []
    for _ in range(r.u32()):
        mstart = r.p
        msize = r.u64()
        meshes.append(_read_mesh(r))
        r.p = mstart + msize
    materials = []
    try:
        for _ in range(r.u32()):
            mstart = r.p
            msize = r.u64()
            materials.append(_read_material_name(r))
            r.p = mstart + msize
    except Exception:
        pass                     # material names are a convenience; meshes are what matter
    return meshes, materials


def _read_mesh(r: _R):
    name = r.string()
    prim = r.u32()
    mat = r.u32()
    flags = r.u32()
    m = {"name": name, "material": mat, "positions": None, "normals": None, "uvs": None}
    if flags & 0x1:
        m["positions"] = r.vecs(3)
    if flags & 0x2:
        m["normals"] = r.vecs(3)
    if flags & 0x4:
        r.vecs(3); r.vecs(3)     # tangents, bitangents (Strata recomputes them)
    for c in range(8):
        if flags & (0x10000 << c):
            r.vecs(4)
    for t in range(8):
        if flags & (0x100 << t):
            ncomp = r.u32()
            uv = r.vecs(3)
            if t == 0:
                m["uvs"] = uv[:, :2]
            if ncomp not in (1, 2, 3):
                raise AssbinError(f"bad uv component count {ncomp}")
    nf = r.u32()
    nv = 0 if m["positions"] is None else len(m["positions"])
    tris = []
    # faces are [u32 flag][u32 n][n x u32]; fan-triangulate anything that isn't a triangle
    buf = np.frombuffer(r.d, np.uint32, (len(r.d) - r.p) // 4, r.p)
    i = 0
    for _ in range(nf):
        n = int(buf[i + 1])
        idx = buf[i + 2:i + 2 + n]
        if n >= 3:
            for k in range(1, n - 1):
                tris.append((idx[0], idx[k], idx[k + 1]))
        i += 2 + n
    r.p += i * 4
    m["indices"] = np.asarray(tris, np.uint32).reshape(-1, 3)
    if m["indices"].size and (m["indices"].max() >= nv):
        raise AssbinError(f"mesh {name}: face index out of range")
    m["prim"] = prim
    return m


def _read_material_name(r: _R) -> str:
    name = ""
    for _ in range(r.u32()):
        pstart = r.p
        psize = r.u64()                      # each property is its own sized record
        key = r.string()
        if key == "?mat.name":
            r.u32(); r.u32(); r.u32(); r.u32()   # semantic, index, data length, type
            name = r.string()
        r.p = pstart + psize
    return name
