"""CPU-only native project archive contracts and resource packaging.

No GPU/UI imports: all archive validation happens before project restoration.
Resource IDs describe immutable bytes, not mutable layer identities.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

import numpy as np

VERSION = 15
_HASH = re.compile(r"^[a-f0-9]{64}$")
_BAKES = {"position": (4, "f4"), "world_normal": (4, "f2"), "curvature": (4, "f2"),
          "projection_diagnostics": (4, "f1"),
          "ao": (4, "f2"), "thickness": (4, "f2"), "id": (4, "f1"),
          "coverage": (1, "f1"), "part": (4, "f2"), "tangent": (4, "f2"),
          "normal": (4, "f2"), "height": (4, "f2")}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      default=lambda v: v.tolist() if isinstance(v, np.ndarray) else float(v))


def _relative(path, root):
    try:
        return os.path.relpath(path, root)
    except ValueError:  # Windows paths on different drives
        return None


def resource_slots(meta):
    """Yield (container, key, role) only for known path-bearing fields."""
    def layers(nodes):
        for layer in nodes:
            if "instance" in layer:
                continue
            authored=layer.get("authored") or {}
            for key,role in (("font","font"),("alpha","alpha")):
                if authored.get(key):yield authored,key,role
            for key in list(layer.get("maps", {})):
                yield layer["maps"], key, "texture"
            for effect in layer.get("effects", []) + layer.get("mask_effects", []):
                params = effect.get("params", {})
                if effect.get("kind") == "fill" and params.get("map"):
                    yield params, "map", "texture"
            yield from layers(layer.get("children", []))
    for texset in meta.get("sets", []):
        yield from layers(texset.get("layers", []))
        high = texset.get("bake", {}).get("high_poly", [])
        for index in range(len(high)):
            yield high, index, "high_poly"
        for record in texset.get("bake", {}).get("external_maps", {}).values():
            if record.get("path"):
                yield record, "path", "mesh_map"
        if texset.get("bake", {}).get("cage_path"):
            yield texset["bake"], "cage_path", "cage"
        for operation in texset.get("tiles", {}).get("operations", []):
            yield from resource_slots({"brush": operation.get("brush", {})})
        for channels in texset.get("tiles", {}).get("sequences", {}).values():
            for paths in channels.values():
                for udim in paths:
                    yield paths, udim, "texture"
    for task in (meta.get("imports",{}).get("continuation") or {}).get("tasks",[]):
        yield from resource_slots({"brush":task.get("job",{}).get("brush",{})})
    brush = meta.get("brush", {})
    for key, role in (("alpha", "alpha"), ("stencil", "stencil")):
        if brush.get(key):
            yield brush, key, role
    for slot in ("maps", "proj_maps"):
        for key in brush.get(slot, {}):
            yield brush[slot], key, "texture"
    if meta.get("environment"):
        yield meta, "environment", "environment"
    for node in meta.get("journal", {}).get("nodes", {}).values():
        operation = node.get("operation")
        if operation:
            yield from resource_slots({"brush": operation.get("brush", {})})


def package_resources(meta, project_path, portable=False, previous=(), builtin_alphas=()):
    """Return copied metadata, embedded blobs, and live resource diagnostics."""
    out = copy.deepcopy(meta)
    previous = {r.get("resolved"): r for r in previous}
    records, blobs, diagnostics = {}, {}, []
    root = Path(project_path).resolve().parent
    for owner, key, role in resource_slots(out):
        value = owner[key]
        if role == "alpha" and value in builtin_alphas:
            continue
        if not isinstance(value, str) or not value or value.startswith(("bake:", "builtin:", "<mesh:")):
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = path.resolve() if path.is_file() else root / path
        path = path.resolve()
        prior = previous.get(str(path), {})
        if path.is_file():
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            # A path-independent ID keeps the same asset identifiable after relocation.
            rid = digest
            embedded = portable or bool(prior.get("embedded"))
            suffix = path.suffix.lower()
            suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,12}", suffix) else ".bin"
            member = f"resources/{rid}{suffix}" if embedded else None
            if embedded:
                blobs[member] = content
            record = records.setdefault(rid, {"id": rid, "sha256": digest, "size": len(content),
                "source": prior.get("source") or str(path), "relative": _relative(path, root),
                "member": member, "embedded": embedded, "roles": [], "resolved": str(path),
                "status": "embedded" if embedded else "available"})
            if role not in record["roles"]:
                record["roles"].append(role)
            owner[key] = "resource:" + rid
        else:
            # Retain unresolved references instead of silently substituting another asset.
            rid = prior.get("id") or hashlib.sha256(("missing:" + str(path)).encode()).hexdigest()
            record = records.setdefault(rid, {"id": rid, "sha256": prior.get("sha256"),
                "size": prior.get("size"), "source": prior.get("source") or str(path),
                "relative": _relative(path, root), "member": None, "embedded": False,
                "roles": [role], "resolved": str(path), "status": "missing"})
            owner[key] = "resource:" + rid
            diagnostics.append({"code": "resource_missing", "severity": "warning", "resource_id": rid,
                                "source": str(path), "message": f"Missing {role}: {path}"})
    out["resources"] = [{k: v for k, v in r.items() if k not in ("resolved", "status")}
                        for r in records.values()]
    return out, blobs, list(records.values()), diagnostics


def bake_fingerprint(meta, arrays, texset):
    """Provenance depends on mesh bytes, bake parameters and recorded source hashes."""
    h = hashlib.sha256()
    for key in sorted(k for k in arrays if k.startswith("mesh_")):
        arr = np.ascontiguousarray(arrays[key])
        h.update(key.encode()); h.update(str(arr.dtype).encode()); h.update(str(arr.shape).encode())
        h.update(arr.tobytes())
    baked = texset.get("cache", {}).get("baked_settings")
    settings = baked if baked else texset.get("bake", {})
    h.update(_json({"bake": settings, "materials": texset.get("materials", []),
                    "res": texset["res"], "xform": meta.get("mesh_extra", {}).get("xform"),
                    "source_hashes": texset.get("cache", {}).get("source_hashes", [])}).encode())
    return h.hexdigest()


def validate(meta, arrays):
    if not isinstance(meta, dict) or not isinstance(meta.get("version", 1), int):
        raise ValueError("Invalid project metadata")
    version = meta.get("version", 1)
    if version < 1 or version > VERSION:
        raise ValueError(f"Unsupported project version {version}; supported through {VERSION}")
    if "export_settings" in meta:
        from .exportsettings import validate as validate_export_settings
        if version < 14:
            raise ValueError("Project export settings require version 14")
        validate_export_settings(meta["export_settings"])
    from .userchannels import validate as validate_channels, layer_values, DEFAULT_WORKFLOW
    user_definitions = meta.get("user_channels", {})
    if ("user_channels" in meta or "shader_workflow" in meta) and version < 13:
        raise ValueError("User channels and shader workflows require version 13")
    validate_channels(user_definitions, meta.get("shader_workflow", DEFAULT_WORKFLOW))
    def check_brush(brush):
        key = brush.get("user_channel")
        if key is not None:
            if key not in user_definitions:raise ValueError("Brush references an undeclared user channel")
            from .userchannels import unit_value
            unit_value(brush.get("user_value",1.))
    check_brush(meta.get("brush", {}))
    for node in meta.get("journal", {}).get("nodes", {}).values():
        if node.get("operation"):check_brush(node["operation"]["brush"])
        if any(key.startswith("user:") and key not in user_definitions for key in node.get("pixels", {})):
            raise ValueError("Checkpoint references an undeclared user channel")
    for texture_set in meta.get("sets", []):
        for operation in texture_set.get("tiles", {}).get("operations", []):check_brush(operation["brush"])
        for channels in texture_set.get("tiles", {}).get("sequences", {}).values():
            if any(key.startswith("user:") and key not in user_definitions for key in channels):
                raise ValueError("Undeclared tile image channel")
    workflow = meta.get("shader_workflow", DEFAULT_WORKFLOW)
    if workflow["displacement_meters"]:
        from types import SimpleNamespace
        from .uvprep import meters_per_project_unit
        meters_per_project_unit(SimpleNamespace(extra=meta.get("mesh_extra", {})))
        if any(ts.get("tiles") for ts in meta.get("sets", [])):
            raise ValueError("Tiled displacement is unsupported")
    if "imports" in meta:
        if version<11 or not isinstance(meta["imports"],dict):raise ValueError("Import reports require project version 11")
        reports=meta["imports"].get("reports",[])
        if not isinstance(reports,list) or any(not isinstance(r,dict) for r in reports):raise ValueError("Invalid import reports")
        continuation=meta["imports"].get("continuation")
        if continuation is not None:
            from .substance.session import validate as validate_import
            validate_import(continuation)

    if "journal" in meta:
        from .journal import Journal
        if version < 7:
            raise ValueError("Native paint journals require version 7")
        Journal.load(meta["journal"], arrays)
    if meta.get("color"):
        from .color import ColorSettings
        color = meta["color"]
        if (version < 6 or not isinstance(color, dict) or not isinstance(color.get("settings"), dict)
                or set(color["settings"]) - set(ColorSettings.__dataclass_fields__)
                or color["settings"].get("mode") != "managed" or not isinstance(color.get("config_id"), str)):
            raise ValueError("Invalid managed-color project metadata")
    if version < 2:
        meta["sets"] = [{"name": "Default", "materials": [0], "res": meta["res"],
                         "selected": meta.get("selected", 0),
                         "layers": [dict(v, _id=f"L{i}") for i, v in enumerate(meta["layers"])]}]
    sets = meta.get("sets")
    if not isinstance(sets, list) or not sets:
        raise ValueError("Project has no texture sets")
    for key, width in (("positions", 3), ("normals", 3), ("uvs", 2), ("indices", 3),
                       ("tangents", 4)):
        a = arrays.get("mesh_" + key)
        if a is None or a.ndim != 2 or a.shape[1] != width or not np.isfinite(a).all():
            raise ValueError(f"Invalid mesh {key}")
    n = len(arrays["mesh_positions"])
    if n == 0 or any(len(arrays["mesh_" + k]) != n for k in ("normals", "uvs", "tangents")):
        raise ValueError("Mesh vertex arrays disagree")
    idx = arrays["mesh_indices"]
    if idx.dtype.kind not in "iu" or (idx.size and (idx.min() < 0 or idx.max() >= n)):
        raise ValueError("Mesh indices are out of range")
    if "mesh_curvature" not in arrays or arrays["mesh_curvature"].size != n:
        raise ValueError("Invalid mesh curvature")
    for key, width in (("parts", 2), ("colors", 4)):
        if "mesh_" + key in arrays and arrays["mesh_" + key].shape != (n, width):
            raise ValueError(f"Invalid mesh {key}")
    if "mesh_tri_material" in arrays and arrays["mesh_tri_material"].shape != (len(idx),):
        raise ValueError("Invalid triangle materials")
    known = set()
    completed = set()
    persistent = set()
    definitions = {}

    def identity(obj):
        value = obj.get("pid")
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value) or value in persistent:
                raise ValueError("Invalid or duplicate persistent identity")
            persistent.add(value)

    def raster(node):
        if "instance" in node:
            return raster(definitions[node["instance"]][0])
        return (node.get("kind") == "paint" or node.get("has_mask", False) or
                any(e.get("kind") == "paint" for e in node.get("mask_effects", [])) or
                any(raster(child) for child in node.get("children", [])))

    def nodes(layers, res, materials=None):
        if not isinstance(layers, list):
            raise ValueError("Invalid layer list")
        for layer in layers:
            if not isinstance(layer, dict):
                raise ValueError("Invalid layer")
            if "instance" in layer:
                if layer["instance"] not in completed:
                    raise ValueError("Unresolved or cyclic layer instance")
                original, original_res = definitions[layer["instance"]]
                if version < 5 and original_res != res and raster(original):
                    raise ValueError("Raster instances cannot span texture resolutions; duplicate the layer instead")
                continue
            identity(layer)
            projections=[layer.get("proj",{})]+[effect.get("params",{}).get("proj") or {} for effect in layer.get("mask_effects",[]) if effect.get("kind")=="fill"]
            for projection in projections:
                if projection.get("warp") is not None or projection.get("decal",False):
                    if version<12:raise ValueError("Warp/decal projection requires project version 12")
                    from .authored import warp_matrix
                    warp_matrix(projection.get("warp"))
                    if type(projection.get("decal",False)) is not bool:raise ValueError("Invalid decal projection")
            if layer.get("authored") is not None:
                if version<12 or layer.get("kind")!="fill":raise ValueError("Authored objects require version-12 fill layers")
                from .authored import validate as validate_authored
                from types import SimpleNamespace
                source=SimpleNamespace(indices=idx,uvs=arrays["mesh_uvs"],positions=arrays["mesh_positions"],tri_material=arrays.get("mesh_tri_material",np.zeros(len(idx),np.int32)))
                selected=np.flatnonzero(np.isin(source.tri_material,materials)) if materials is not None else None
                validate_authored(layer["authored"],source,selected)
                if layer["authored"]["kind"]=="text" and layer.get("proj",{}).get("mode",0) not in (0,2):raise ValueError("Text supports UV or planar projection")
            repeat = layer.get("proj", {}).get("repeat_meters", 0)
            if (isinstance(repeat, bool) or not isinstance(repeat, (int, float)) or not np.isfinite(repeat)
                    or repeat < 0 or (repeat and version < 8)):
                raise ValueError("Physical projection repeat requires valid version-8 metadata")
            if repeat:
                from .uvprep import meters_per_project_unit
                from types import SimpleNamespace
                meters_per_project_unit(SimpleNamespace(extra=meta.get("mesh_extra", {})))
            raster_res = layer.get("raster_res", res)
            if not isinstance(raster_res, int) or not 1 <= raster_res <= 32768 or (version < 5 and raster_res != res):
                raise ValueError("Invalid canonical raster resolution")
            for effect in layer.get("effects", []) + layer.get("mask_effects", []):
                if not isinstance(effect, dict):
                    raise ValueError("Invalid effect")
                identity(effect)
                kind, params = effect.get("kind"), effect.get("params", {})
                if kind in ("mask_anchor", "bevel") or (kind == "generator" and params.get("micro_normal")):
                    if version < 15 or effect not in layer.get("mask_effects", []):
                        raise ValueError("Mask anchors, bevel and micro normals require version-15 mask effects")
                    for key, default, lo, hi in (("radius", 4.0, 0, 32), ("micro_strength", 1.0, 0, 16)):
                        value = params.get(key, default)
                        if not isinstance(value, (int, float)) or not np.isfinite(value) or not lo <= value <= hi:
                            raise ValueError("Invalid mask effect " + key)
                    if kind == "mask_anchor" and (not isinstance(params.get("name"), str) or not params["name"].strip()):
                        raise ValueError("Mask anchor requires a name")
                if effect.get("kind") == "graph":
                    from .graphs import validate as validate_graph
                    if version < 11:raise ValueError("Native graphs require project version 11")
                    validate_graph(effect.get("params",{}).get("graph"))
                if effect.get("kind") == "paint":
                    if version < 4 or effect not in layer.get("mask_effects", []):
                        raise ValueError("Mask paint effects require project version 4")
                    key = "effect_" + str(effect.get("pid", ""))
                    if key not in arrays or arrays[key].shape != (raster_res, raster_res, 1):
                        raise ValueError("Missing or invalid paint-effect pixels")
                source = effect.get("params", {}).get("source_pid")
                if source is not None and (not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{32}", source)):
                    raise ValueError("Invalid anchor source identity")
            pid = layer.get("_id")
            if not isinstance(pid, str) or pid in known:
                raise ValueError("Invalid or duplicate layer reference")
            known.add(pid)
            definitions[pid] = (layer, raster_res)
            if layer.get("kind", "fill") not in ("fill", "paint", "group"):
                raise ValueError("Invalid layer kind")
            layer_values(layer.get("user_channels", {}), user_definitions)
            for effect in layer.get("effects", []):
                if effect.get("params", {}).get("user_channel") and effect["params"]["user_channel"] not in user_definitions:
                    raise ValueError("Undeclared effect channel")
                if effect.get("params", {}).get("user_channel") and effect.get("kind") not in ("invert","levels","blur","brightness_contrast","graph"):
                    raise ValueError("Unsupported scalar content effect")
            if layer.get("kind") == "paint":
                for channel, components in dict({"C": 4, "R": 2, "M": 2, "H": 2, "N": 4, "E": 4, "O": 2}, **{key: 2 for key in user_definitions}).items():
                    key = f"{pid}_{channel}"
                    if key in arrays and arrays[key].shape != (raster_res, raster_res, components):
                        raise ValueError(f"Invalid paint array {key}")
            if f"{pid}_mask" in arrays and arrays[f"{pid}_mask"].shape not in ((raster_res, raster_res, 1), (raster_res, raster_res)):
                raise ValueError(f"Invalid mask array {pid}")
            nodes(layer.get("children", []), res,materials)
            completed.add(pid)
    for texset in sets:
        identity(texset)
        from .bakecontrol import DEFAULTS, validate_settings
        from types import SimpleNamespace
        advanced = texset.get("bake", {})
        if any(key in advanced for key in DEFAULTS):
            if version < 10:
                raise ValueError("Advanced bake settings require project version 10")
            validate_settings(SimpleNamespace(**{key: advanced.get(key, value) for key, value in DEFAULTS.items()}))
        res = texset.get("res")
        if not isinstance(res, int) or res < 1 or res > 32768:
            raise ValueError("Invalid texture resolution")
        from .userchannels import validate_resolution
        validate_resolution(user_definitions, res)
        if texset.get("tiles") is not None:
            if version < 9:
                raise ValueError("Material tiles require project version 9")
            from .tiles import validate_material_tiles
            from types import SimpleNamespace
            source = SimpleNamespace(**{key: arrays.get("mesh_" + key) for key in
                                     ("positions", "normals", "uvs", "indices", "tangents", "curvature", "parts", "colors", "tri_material")})
            if any(value is None for value in vars(source).values()):
                raise ValueError("Tiled projects require complete source vertex arrays")
            validate_material_tiles(texset["tiles"], arrays, source, texset["pid"], texset["materials"], res)
        external = texset.get("bake", {}).get("external_maps", {})
        if not isinstance(external, dict):
            raise ValueError("Invalid external mesh-map records")
        interpretations = {"ao": "data", "curvature": "data", "thickness": "data", "id": "data",
                           "normal": "data", "height": "data", "world_normal": "encoded", "position": "object"}
        for name, record in external.items():
            if (name not in interpretations or not isinstance(record, dict) or record.get("set_pid") != texset.get("pid")
                    or record.get("interpretation") != interpretations[name] or not isinstance(record.get("path"), str)
                    or not _HASH.fullmatch(str(record.get("sha256", "")))):
                raise ValueError("Invalid external mesh-map identity or interpretation")
        nodes(texset.get("layers", []), res,texset.get("materials"))
        cache = texset.get("cache", {})
        if cache.get("maps") and not {"position", "world_normal", "curvature", "ao", "coverage"}.issubset(cache["maps"]):
            raise ValueError("Incomplete baked map cache")
        for name, info in cache.get("maps", {}).items():
            key = info.get("array")
            if name not in _BAKES or key not in arrays:
                raise ValueError("Invalid baked map cache")
            comps = _BAKES[name][0]
            if arrays[key].shape != (res, res, comps) or info.get("dtype") not in ("f1", "f2", "f4"):
                raise ValueError(f"Invalid baked map dimensions: {name}")
            if info.get("sha256") and hashlib.sha256(np.ascontiguousarray(arrays[key]).tobytes()).hexdigest() != info["sha256"]:
                raise ValueError(f"Baked map cache hash mismatch: {name}")
    for key, arr in arrays.items():
        if arr.dtype.kind not in "biuf" or not np.isfinite(arr).all():
            raise ValueError(f"Non-numeric or non-finite array: {key}")


def read_archive(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive members")
        meta = json.loads(archive.read("project.json"))
        with np.load(io.BytesIO(archive.read("data.npz")), allow_pickle=False) as values:
            arrays = {k: values[k].copy() for k in values.files}
        validate(meta, arrays)
        blobs = {}
        resource_ids = set()
        for resource in meta.get("resources", []):
            rid = resource.get("id")
            if not isinstance(rid, str) or not _HASH.fullmatch(rid) or rid in resource_ids:
                raise ValueError("Invalid resource identity")
            resource_ids.add(rid)
            member = resource.get("member")
            if member:
                if not re.fullmatch(r"resources/" + rid + r"\.[a-z0-9]{1,12}", member):
                    raise ValueError("Invalid embedded resource member")
                content = archive.read(member)
                if len(content) != resource.get("size") or hashlib.sha256(content).hexdigest() != resource.get("sha256"):
                    raise ValueError(f"Embedded resource hash mismatch: {rid}")
                blobs[member] = content
        for owner, key, _ in resource_slots(meta):
            value = owner[key]
            if isinstance(value, str) and value.startswith("resource:") and value[9:] not in resource_ids:
                raise ValueError("Unresolved project resource")
    return meta, arrays, blobs


def resolve_resources(meta, blobs, path, builtin_alphas=()):
    out = copy.deepcopy(meta)
    temp = tempfile.TemporaryDirectory(prefix="strata_project_") if blobs else None
    records, diagnostics = [], []
    root = Path(path).resolve().parent
    for item in out.get("resources", []):
        record = dict(item)
        member = item.get("member")
        if member:
            resolved = Path(temp.name) / Path(member).name
            resolved.write_bytes(blobs[member])
            record.update(resolved=str(resolved), status="embedded", embedded=True)
        else:
            relative = item.get("relative")
            candidates = ([root / relative] if relative else []) + [Path(item["source"])]
            resolved = next((p for p in candidates if p.is_file()), candidates[-1])
            status = "missing"
            if resolved.is_file():
                digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
                status = "available" if not item.get("sha256") or digest == item["sha256"] else "changed"
            record.update(resolved=str(resolved.resolve()), status=status, embedded=False)
            if status != "available":
                diagnostics.append({"code": "resource_" + status, "severity": "warning",
                    "resource_id": item["id"], "source": str(resolved),
                    "message": f"{status.title()} project resource: {resolved}"})
        records.append(record)
    by_id = {v["id"]: v["resolved"] for v in records}
    for owner, key, role in resource_slots(out):
        value = owner[key]
        if role == "alpha" and value in builtin_alphas:
            continue
        if isinstance(value, str) and value.startswith("resource:"):
            owner[key] = by_id[value[9:]]
        elif isinstance(value, str) and value and not value.startswith(("bake:", "builtin:", "<mesh:")):
            source = Path(value).expanduser()
            owner[key] = str((root / source).resolve()) if not source.is_absolute() else str(source)
            resolved = Path(owner[key])
            if not any(r["resolved"] == str(resolved) for r in records):
                digest = hashlib.sha256(resolved.read_bytes()).hexdigest() if resolved.is_file() else None
                rid = digest or hashlib.sha256(("missing:" + str(resolved)).encode()).hexdigest()
                records.append({"id": rid, "sha256": digest, "source": str(resolved),
                    "resolved": str(resolved), "status": "available" if digest else "missing",
                    "embedded": False, "member": None, "roles": [role]})
                if digest is None:
                    diagnostics.append({"code": "resource_missing", "severity": "warning", "resource_id": rid,
                        "source": str(resolved), "message": f"Missing legacy project resource: {resolved}"})
    return out, records, diagnostics, temp


def atomic_write(path, meta, arrays, blobs=(), backups=0):
    """Validate a sibling archive and replace only after complete durable write."""
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + destination.name + ".", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w+b") as output:
            buf = io.BytesIO(); np.savez_compressed(buf, **arrays)
            with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
                archive.writestr("project.json", _json(meta))
                archive.writestr("data.npz", buf.getvalue())
                for name, content in dict(blobs).items():
                    archive.writestr(name, content)
            output.flush(); os.fsync(output.fileno())
        read_archive(temporary)
        count = max(0, int(backups))
        if count and destination.is_file():
            for index in range(count, 1, -1):
                previous = Path(str(destination) + f".bak{index - 1}")
                if previous.is_file():
                    os.replace(previous, str(destination) + f".bak{index}")
            # Copy, rather than move, the valid destination before publication.
            backup_tmp = temporary + ".backup"
            try:
                shutil.copyfile(destination, backup_tmp)
                os.replace(backup_tmp, str(destination) + ".bak1")
            finally:
                if os.path.exists(backup_tmp):
                    os.unlink(backup_tmp)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
