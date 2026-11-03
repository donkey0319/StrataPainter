"""Optional Blender UV preparation and declared physical source units."""
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import numpy as np

UNITS = {"unspecified": None, "m": 1., "cm": .01, "mm": .001, "in": .0254, "ft": .3048}


def uv_status(mesh):
    triangles = mesh.uvs[mesh.indices]
    a, b = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    valid = np.isfinite(triangles).all((1, 2)) & (abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) > 1e-12)
    missing = mesh.extra.get("uv_missing_triangles", [])
    valid[np.asarray(missing, np.int64)] = False
    return valid


def meters_per_project_unit(mesh):
    unit = mesh.extra.get("physical", {}).get("unit", "unspecified")
    if unit not in UNITS or UNITS[unit] is None:
        raise ValueError("Declare source units before using physical material repeat")
    scale = float(mesh.extra.get("xform", ([0, 0, 0], 1.))[1])
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid source normalization scale")
    return UNITS[unit] / scale


def projection_scale(mesh, projection):
    scale = np.asarray(projection.scale, float)
    if projection.repeat_meters > 0 and projection.mode in (1, 2):
        scale = scale * (mesh.radius * 2 * meters_per_project_unit(mesh) / projection.repeat_meters)
    return tuple(map(float, scale))


def options(settings):
    result = {"method": "smart", "preserve_valid": True, "padding_px": 8, "resolution": 1024,
              "angle_degrees": 66., "rotate": True, "tile_count": 1}
    if set(settings) - set(result):
        raise ValueError("Unknown automatic UV option")
    result.update(settings)
    if result["method"] not in ("smart", "angle"):
        raise ValueError("UV method must be smart or angle")
    for key in ("preserve_valid", "rotate"):
        if type(result[key]) is not bool:
            raise ValueError("Invalid UV boolean option")
    if (type(result["tile_count"]) is not int or not 1 <= result["tile_count"] <= 64
            or type(result["resolution"]) is not int or not 64 <= result["resolution"] <= 8192
            or type(result["padding_px"]) is not int or not 0 <= result["padding_px"] <= 64
            or result["padding_px"] * 4 >= result["resolution"]
            or not math.isfinite(result["angle_degrees"]) or not 1 <= result["angle_degrees"] <= 89):
        raise ValueError("Invalid UV resolution, padding or seam angle")
    return result


def _free_region(uvs, padding):
    """Conservative free rectangle; never move preserved UVs or overlap their bounds."""
    n = 64
    occupied = np.zeros((n, n), bool)
    for triangle in uvs:
        lo = np.floor((triangle.min(0) - padding) * n).astype(int).clip(0, n)
        hi = np.ceil((triangle.max(0) + padding) * n).astype(int).clip(0, n)
        occupied[lo[1]:hi[1], lo[0]:hi[0]] = True
    heights, best = np.zeros(n, int), (0, (0, 0, 0, 0))
    for y in range(n):
        heights = np.where(occupied[y], 0, heights + 1)
        for left in range(n):
            height = n
            for right in range(left, n):
                height = min(height, heights[right])
                area = height * (right - left + 1)
                if area > best[0]:
                    best = (area, (left / n, (y + 1 - height) / n, (right + 1) / n, (y + 1) / n))
    return best[1]


def _charts(mesh, ids, angle):
    """Stable geometric charts split by source parts and dihedral seams."""
    points = mesh.positions[mesh.indices[ids]].astype(float)
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    parents = list(range(len(ids)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    edges = {}
    for local, triangle in enumerate(mesh.indices[ids]):
        keys = [(int(mesh.parts[v, 0]), *map(float, mesh.positions[v])) for v in triangle]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            edges.setdefault(tuple(sorted((keys[a], keys[b]))), []).append(local)
    threshold = math.cos(math.radians(angle))
    for faces in edges.values():
        if len(faces) > 2:
            raise ValueError("Nonmanifold geometry: an edge has more than two faces; repair before unwrapping")
        if len(faces) == 2 and np.dot(normals[faces[0]], normals[faces[1]]) >= threshold:
            a, b = map(root, faces)
            parents[max(a, b)] = min(a, b)
    charts = {}
    for local, face in enumerate(ids):
        charts.setdefault(root(local), []).append(int(face))
    return list(charts.values())


def _packing_groups(mesh, selected, valid, setting):
    padding = setting["padding_px"] / setting["resolution"]
    count = setting["tile_count"]
    addresses = [(i % 10, i // 10) for i in range(count)]
    groups = []
    for material in np.unique(mesh.tri_material[selected]):
        ids = np.flatnonzero(selected & (mesh.tri_material == material))
        preserved = np.flatnonzero(valid & ~selected & (mesh.tri_material == material))
        fixed = mesh.uvs[mesh.indices[preserved]]
        # Preserved triangles must fit the chosen tile budget. No UV is moved.
        if len(fixed) and ((fixed < 0).any() or any(
                not any(np.all(triangle >= address) and np.all(triangle <= np.array(address) + 1)
                        for address in addresses) for triangle in fixed)):
            raise ValueError("Preserved UV faces cross tile boundaries or exceed the UV tile budget; increase the budget or regenerate valid UVs")
        regions = []
        for address in addresses:
            offset = np.array(address)
            local = fixed - offset
            inside = np.all((local >= 0) & (local <= 1), axis=(1, 2))
            region = _free_region(local[inside], padding) if inside.any() else (0., 0., 1., 1.)
            width, height = region[2] - region[0], region[3] - region[1]
            if min(width, height) > padding * 4 + .01:
                regions.append((address, region, width * height))
        if not regions:
            raise ValueError("No free UV region beside preserved faces; increase the tile budget, choose regenerate all or a separate material")
        # Multi-tile packing allocates intact angle-seam charts, then lets Blender
        # unwrap/pack the assigned charts inside each tile's free rectangle.
        charts = _charts(mesh, ids, setting["angle_degrees"])
        if count == 1:
            charts = [ids.tolist()]
        weighted = []
        for chart in charts:
            points = mesh.positions[mesh.indices[chart]].astype(float)
            area = float(np.linalg.norm(np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]), axis=1).sum())
            weighted.append((area, chart))
        loads, assignments = [0.] * len(regions), [[] for _ in regions]
        for area, chart in sorted(weighted, key=lambda value: (-value[0], value[1][0])):
            index = min(range(len(regions)), key=lambda i: (loads[i] / regions[i][2], i))
            assignments[index].extend(chart)
            loads[index] += area
        for (address, region, _), assigned in zip(regions, assignments):
            if assigned:
                offset = np.array([*address, *address])
                groups.append({"triangles": sorted(assigned), "region": (np.array(region) + offset).tolist()})
    return groups


def prepare_mesh(mesh, uv_settings=None, source_unit=None):
    if source_unit is not None and source_unit not in UNITS:
        raise ValueError("Unknown source physical unit")
    result = copy.deepcopy(mesh)
    if source_unit is not None:
        result.extra["physical"] = {"unit": source_unit, "meters_per_source_unit": UNITS[source_unit]}
    if uv_settings is None:
        return result
    setting = options(uv_settings)
    valid = uv_status(result)
    selected = ~valid if setting["preserve_valid"] else np.ones(len(valid), bool)
    if not selected.any():
        return result
    # Reject geometric degeneracy/nonmanifold incidence before invoking the backend.
    points = result.positions[result.indices].astype(float)
    if not np.isfinite(points).all() or np.any(np.linalg.norm(np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]), axis=1) < 1e-12):
        raise ValueError("Degenerate geometry cannot be unwrapped; repair zero-area faces")
    groups = _packing_groups(result, selected, valid, setting)
    from .tangents import blender_path
    executable = blender_path()
    if not executable:
        raise RuntimeError("Automatic UV preparation requires Blender; set STRATA_BLENDER")
    root = os.environ.get("STRATA_RESOURCE_CACHE")
    if root:
        Path(root).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="strata-unwrap-", dir=root) as temporary:
        directory = Path(temporary)
        source, output = directory / "input.npz", directory / "output.npz"
        np.savez(source, positions=result.positions, normals=result.normals, indices=result.indices,
                 uvs=result.uvs, parts=result.parts, settings=np.array(json.dumps(setting)),
                 groups=np.array(json.dumps(groups)))
        environment = os.environ.copy()
        environment.update(BLENDER_USER_CONFIG=str(directory / "config"), BLENDER_USER_SCRIPTS=str(directory / "scripts"))
        process = subprocess.run([executable, "--background", "--factory-startup", "--python",
                                  str(Path(__file__).with_name("unwrap_worker.py")), "--", str(source), str(output)],
                                 env=environment, capture_output=True, text=True, timeout=180,
                                 creationflags=0x08000000 if os.name == "nt" else 0)
        if process.returncode or not output.is_file():
            raise ValueError("Blender UV preparation failed: " + (process.stderr or process.stdout)[-1400:])
        with np.load(output, allow_pickle=False) as data:
            corner_uvs, version = data["uvs"].copy(), str(data["version"])
    if corner_uvs.shape != (len(result.indices), 3, 2) or not np.isfinite(corner_uvs).all():
        raise ValueError("Invalid automatic UV result")
    if setting["preserve_valid"] and not np.array_equal(corner_uvs[valid], result.uvs[result.indices[valid]]):
        raise ValueError("UV backend changed preserved faces")
    from .mesh import Mesh
    ids = result.indices.ravel()
    prepared = Mesh(result.name, result.positions[ids], result.normals[ids], corner_uvs.reshape(-1, 2),
                    np.arange(len(ids), dtype=np.uint32).reshape(-1, 3), extra=copy.deepcopy(result.extra),
                    curvature=result.curvature[ids],
                    parts=result.parts[ids], colors=result.colors[ids], tri_material=result.tri_material.copy(),
                    material_names=list(result.material_names), part_names=list(result.part_names)).finalize()
    prepared.extra.pop("uv_missing_triangles", None)
    if not uv_status(prepared).all():
        raise ValueError("UV preparation produced degenerate coordinates")
    for group in groups:
        values = corner_uvs[group["triangles"]]
        region = group["region"]
        if (values < np.array(region[:2]) - 1e-6).any() or (values > np.array(region[2:]) + 1e-6).any():
            raise ValueError("UV preparation exceeded its assigned tile region")
    from .tiles import partition
    pages = partition(prepared).pages
    addresses = sorted(pages)
    prepared.extra["uv_preparation"] = {"backend": "Blender", "version": version, "settings": setting,
                                       "generated_triangles": np.flatnonzero(selected).tolist(),
                                       "tiles": [address.to_list() for address in addresses]}
    if setting["tile_count"] == 1:
        prepared.extra["uv_preparation"]["tile"] = [0, 0]
    return prepared
