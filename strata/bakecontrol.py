"""CPU contracts for explicit high/low pairing and authored projection cages."""
import numpy as np
from .mesh import Mesh

DEFAULTS = {"pairing": "all", "low_suffix": "_low", "high_suffix": "_high",
            "cage_path": "", "cage_hash": "", "supersampling": 1,
            "ray_correction_pid": "", "distance_correction_pid": "", "correction_hashes": {}}


def validate_settings(settings):
    if settings.pairing not in ("all", "name"):
        raise ValueError("Bake pairing must be all or name")
    if type(settings.supersampling) is not int or settings.supersampling not in (1, 2, 4):
        raise ValueError("Bake supersampling must be 1, 2 or 4")
    if any(not isinstance(getattr(settings, key), str) for key in ("low_suffix", "high_suffix", "cage_path", "cage_hash")):
        raise ValueError("Invalid bake source or pairing suffix")
    if settings.cage_hash and (len(settings.cage_hash) != 64 or any(c not in "0123456789abcdef" for c in settings.cage_hash)):
        raise ValueError("Invalid cage content identity")
    for key in ("ray_correction_pid", "distance_correction_pid"):
        value = getattr(settings, key)
        if not isinstance(value, str) or (value and (len(value) != 32 or any(c not in "0123456789abcdef" for c in value))):
            raise ValueError("Invalid bake correction owner identity")
    if (not isinstance(settings.correction_hashes, dict) or
            any(key not in ("ray", "distance") or not isinstance(value, str) or len(value) != 64 or
                any(c not in "0123456789abcdef" for c in value) for key, value in settings.correction_hashes.items())):
        raise ValueError("Invalid correction content identity")


def validate_cage(low, cage):
    if cage.positions.shape != low.positions.shape or not np.array_equal(cage.indices, low.indices):
        raise ValueError("Cage must retain the low mesh's vertex order and triangle topology")
    if not np.isfinite(cage.positions).all():
        raise ValueError("Cage positions must be finite")
    offset = cage.positions.astype(float) - low.positions
    distance = (offset * low.normals).sum(axis=1)
    if np.any(distance <= max(low.radius, 1e-6) * 1e-7):
        raise ValueError("Cage has inward or zero-distance vertices")
    def faces(mesh):
        points = mesh.positions[mesh.indices].astype(float)
        return np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    original, changed = faces(low), faces(cage)
    if np.any((original * changed).sum(axis=1) <= 1e-18):
        raise ValueError("Cage contains inverted or degenerate faces")
    return {"vertices": len(offset), "min_distance": float(distance.min()), "max_distance": float(distance.max())}


def named_parts(mesh):
    ids = mesh.parts[mesh.indices[:, 0], 0].astype(int)
    result = []
    for index in np.unique(ids):
        name = mesh.part_names[index] if index < len(mesh.part_names) else mesh.name
        # Unnamed single-part meshes pair by the actual source mesh name.
        if len(np.unique(ids)) == 1 and name in ("", "Part 0", "Default"):
            name = mesh.name
        result.append((int(index), name, Mesh(name, mesh.positions, mesh.normals, mesh.uvs,
                      mesh.indices[ids == index], colors=mesh.colors).finalize(light=True)))
    return result


def pair_sources(low, high, settings, active_parts=None):
    validate_settings(settings)
    high = [high] if isinstance(high, Mesh) else list(high)
    if settings.pairing == "all":
        return [(None, high)]
    def key(name, suffix):
        return name[:-len(suffix)] if suffix and name.endswith(suffix) else name
    sources = {}
    for mesh in high:
        for _, name, part in named_parts(mesh):
            sources.setdefault(key(name, settings.high_suffix), []).append(part)
    pairs = []
    missing = []
    for index, name, _ in named_parts(low):
        if active_parts is not None and index not in active_parts:
            continue
        matches = sources.get(key(name, settings.low_suffix))
        if not matches:
            missing.append(name)
        else:
            pairs.append((index, matches))
    if missing:
        raise ValueError("Unmatched low-poly names: " + ", ".join(missing))
    return pairs
