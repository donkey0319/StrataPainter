"""CPU tile addressing and triangle coverage; no GL imports or material duplication."""
from dataclasses import dataclass
import hashlib
import numbers
import numpy as np


@dataclass(frozen=True)
class TileAddress:
    u: int = 0
    v: int = 0

    def __lt__(self, other):
        if not isinstance(other, TileAddress):
            return NotImplemented
        return self.udim < other.udim

    def __post_init__(self):
        if any(isinstance(value, bool) or not isinstance(value, numbers.Integral) for value in (self.u, self.v)):
            raise ValueError("Tile coordinates must be integers")
        object.__setattr__(self, "u", int(self.u))
        object.__setattr__(self, "v", int(self.v))
        if not 0 <= self.u < 10 or self.v < 0 or self.udim > 9999:
            raise ValueError("UDIM tiles require U 0–9, nonnegative V, and a four-digit number")

    @property
    def udim(self):
        return 1001 + self.u + 10 * self.v

    @classmethod
    def from_udim(cls, value):
        if isinstance(value, bool) or not isinstance(value, numbers.Integral) or not 1001 <= value <= 9999:
            raise ValueError("UDIM number must be an integer from 1001 through 9999")
        v, u = divmod(int(value) - 1001, 10)
        return cls(u, v)

    def to_list(self):
        return [self.u, self.v]

    def local(self, uv):
        value = np.asarray(uv, float)
        if value.shape != (2,) or not np.isfinite(value).all():
            raise ValueError("UV coordinates must be two finite values")
        return value - (self.u, self.v)


def address_at(uv, available=None):
    """Half-open point ownership, with lower-neighbor fallback on an outer edge."""
    uv = np.asarray(uv, float)
    if uv.shape != (2,) or not np.isfinite(uv).all() or (uv < 0).any():
        raise ValueError("UV coordinates must be finite and nonnegative")
    base = np.floor(uv).astype(int)
    candidates = [tuple(base)]
    for axis in (0, 1):
        if uv[axis] == base[axis] and base[axis] > 0:
            candidates += [tuple(value - np.eye(2, dtype=int)[axis]) for value in map(np.array, list(candidates))]
    for u, v in candidates:
        try:
            address = TileAddress(u, v)
        except ValueError:
            continue
        if available is None or address in available:
            return address
    raise ValueError("No supported tile contains this UV coordinate")


def _clip(weights, uvs, axis, boundary, greater):
    if not len(weights):
        return weights
    result = []
    previous = weights[-1]
    previous_value = float(previous @ uvs[:, axis] - boundary)
    previous_inside = previous_value >= 0 if greater else previous_value <= 0
    for current in weights:
        value = float(current @ uvs[:, axis] - boundary)
        inside = value >= 0 if greater else value <= 0
        if inside != previous_inside:
            factor = previous_value / (previous_value - value)
            result.append(previous + factor * (current - previous))
        if inside:
            result.append(current)
        previous, previous_value, previous_inside = current, value, inside
    return np.asarray(result, float).reshape(-1, 3)


def _area(triangle):
    a, b = triangle[1] - triangle[0], triangle[2] - triangle[0]
    return float(a[0] * b[1] - a[1] * b[0])


@dataclass(frozen=True)
class TileGeometry:
    address: TileAddress
    source_triangles: np.ndarray
    barycentrics: np.ndarray
    revision: str

    def raster_mesh(self, source, retain_topology=False):
        """Original triangle attributes with shifted UVs; GL clips at tile edges.

        Keeping original corners avoids changing smooth-normal interpolation when
        a face crosses a boundary. World geometry, material IDs and parts remain
        those of the source mesh. The caller owns the new GPU mesh, if uploaded.
        """
        from .mesh import Mesh
        mesh = Mesh(source.name, source.positions, source.normals,
                    source.uvs - self.address.to_list(), source.indices if retain_topology else source.indices[self.source_triangles],
                    tangents=source.tangents, curvature=source.curvature, parts=source.parts,
                    colors=source.colors, tri_material=source.tri_material if retain_topology else source.tri_material[self.source_triangles],
                    material_names=list(source.material_names), part_names=list(source.part_names),
                    extra={**{key: value for key, value in source.extra.items() if key != "uv_missing_triangles"},
                           "tile_address": self.address.to_list()})
        # Source is already finalized; do not normalize or recompute its normals.
        return mesh


@dataclass(frozen=True)
class TilePartition:
    pages: dict
    degenerate_faces: tuple
    revision: str


def partition(mesh, materials=None, max_tiles=256):
    """Find positive-area tile coverage, retaining clipped barycentric provenance.

    A boundary-touching triangle belongs only to tiles containing nonzero area.
    Crossing faces are included in every intersected tile; no centroid shortcut.
    The source mesh is never modified. Degenerate UV faces are reported.
    """
    if type(max_tiles) is not int or max_tiles < 1:
        raise ValueError("Tile limit must be a positive integer")
    uv = np.asarray(mesh.uvs, float)
    indices = np.asarray(mesh.indices)
    if (uv.ndim != 2 or uv.shape[1] != 2 or not np.isfinite(uv).all()
            or indices.ndim != 2 or indices.shape[1] != 3 or indices.dtype.kind not in "iu"
            or indices.size and (indices.min() < 0 or indices.max() >= len(uv))):
        raise ValueError("Invalid tile mesh UVs or indices")
    selected = np.arange(len(indices))
    if materials is not None:
        selected = selected[np.isin(mesh.tri_material, list(materials))]
    digest = hashlib.sha256()
    for values in (mesh.positions, mesh.normals, uv, indices, mesh.tri_material,
                   mesh.tangents, mesh.curvature, mesh.parts, mesh.colors):
        values = np.ascontiguousarray(values)
        digest.update(str(values.shape).encode())
        digest.update(values.tobytes())
    revision = digest.hexdigest()
    pages, degenerate = {}, []
    for face in selected:
        triangle = uv[indices[face]]
        if abs(_area(triangle)) <= 1e-14:
            degenerate.append(int(face))
            continue
        low, high = triangle.min(0), triangle.max(0)
        if (low < 0).any() or high[0] > 10 or high[1] > 900:
            raise ValueError(f"Face {face}: UVs exceed supported nonnegative four-digit UDIM coordinates")
        lo, hi = np.floor(low).astype(int), np.ceil(high).astype(int) - 1
        for v in range(lo[1], hi[1] + 1):
            for u in range(lo[0], hi[0] + 1):
                weights = np.eye(3)
                for axis, boundary, greater in ((0, u, True), (0, u + 1, False), (1, v, True), (1, v + 1, False)):
                    weights = _clip(weights, triangle, axis, boundary, greater)
                pieces = []
                for corner in range(1, len(weights) - 1):
                    piece = weights[[0, corner, corner + 1]]
                    if abs(_area(piece @ triangle)) > 1e-14:
                        pieces.append(piece)
                if not pieces:
                    continue
                address = TileAddress(u, v)
                if address not in pages:
                    if len(pages) >= max_tiles:
                        raise ValueError(f"Mesh tile coverage exceeds the configured limit ({max_tiles})")
                    pages[address] = ([], [])
                pages[address][0].append(int(face))
                pages[address][1].extend((int(face), piece) for piece in pieces)
    result = {}
    for address in sorted(pages):
        faces, pieces = pages[address]
        # Each clipped triangle row starts with the original face ID, followed by
        # its 3x3 source-corner weights, in a compact numeric array.
        barycentrics = np.array([[face, *weights.ravel()] for face, weights in pieces], np.float64)
        source_faces = np.array(faces, np.int64)
        barycentrics.flags.writeable = source_faces.flags.writeable = False
        result[address] = TileGeometry(address, source_faces, barycentrics, revision)
    return TilePartition(result, tuple(degenerate), revision)


def validate_material_tiles(meta, arrays, mesh, set_pid, materials, resolution):
    """CPU-only v9 payload validation, before restoration can allocate GL objects."""
    from .journal import mesh_revision, validate_operation
    from .tilestore import TileStore
    from .channels import BY_KEY
    from .userchannels import is_user
    import re
    revision = mesh_revision(mesh)
    if (not isinstance(meta, dict) or type(meta.get("version")) is not int or meta["version"] != 1
            or meta.get("res") != resolution or meta.get("mesh_revision") != revision
            or not isinstance(meta.get("operations"), list) or not isinstance(meta.get("mask_defaults"), dict)):
        raise ValueError("Invalid material tile payload")
    coverage = partition(mesh, materials)
    if meta.get("addresses") != [address.to_list() for address in coverage.pages]:
        raise ValueError("Tile addresses differ from the material's mesh coverage")
    backing = TileStore.from_snapshot(None, 1, meta.get("backing"), arrays)
    if any(pid != set_pid or address not in coverage.pages for pid, address in backing.pages):
        raise ValueError("Tile backing belongs to a different material or address")
    if any(record["size"] != (resolution, resolution) for page in backing.pages.values() for record in page.saved.values()):
        raise ValueError("Tile raster dimensions differ from the material resolution")
    base = TileStore.from_snapshot(None, 1, meta.get("base"), arrays)
    if any(pid != set_pid or address not in coverage.pages for pid, address in base.pages):
        raise ValueError("Tile base belongs to a different material or address")
    for operation in meta["operations"]:
        validate_operation(operation)
        if (operation["set_pid"] != set_pid or not isinstance(operation.get("owner_pid"), str)
                or operation["mesh_revision"] != revision):
            raise ValueError("Tile operation has invalid material/mesh provenance")
    if any(not isinstance(key, str) or not isinstance(value, (int, float)) or not np.isfinite(value)
           or not 0 <= value <= 1 for key, value in meta["mask_defaults"].items()):
        raise ValueError("Invalid tile mask default")
    sequences = meta.get("sequences", {})
    if not isinstance(sequences, dict):
        raise ValueError("Invalid tile image sequences")
    for owner, channels in sequences.items():
        if not isinstance(owner, str) or not re.fullmatch(r"[0-9a-f]{32}", owner) or not isinstance(channels, dict):
            raise ValueError("Invalid tile image owner")
        for channel, paths in channels.items():
            if (channel not in BY_KEY and not is_user(channel)) or not isinstance(paths, dict):
                raise ValueError("Invalid tile image channel")
            for udim, path in paths.items():
                if (not isinstance(udim, str) or not re.fullmatch(r"[1-9][0-9]{3}", udim)
                        or TileAddress.from_udim(int(udim)) not in coverage.pages or not isinstance(path, str) or not path):
                    raise ValueError("Invalid tile image address or path")
