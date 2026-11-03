"""Transactional mesh revisions with explicit surface/UV/raster correspondence policies."""
import copy
import os
from pathlib import Path
from types import SimpleNamespace
import uuid
import numpy as np

from .journal import Journal, mesh_revision
from .mathutil import normalize


def correspondence(mesh, positions, triangles, max_distance):
    """Nearest points on candidate triangles and edges, bounded by a distance gate."""
    ids = np.asarray(triangles, np.int64)
    if not len(ids):
        raise ValueError("No triangles are mapped to the operation's texture set")
    a, b, c = np.moveaxis(mesh.positions[mesh.indices[ids]].astype(float), 1, 0)
    ab, ac = b - a, c - a
    d00, d01, d11 = (ab * ab).sum(1), (ab * ac).sum(1), (ac * ac).sum(1)
    denominator = d00 * d11 - d01 * d01
    valid = abs(denominator) > 1e-18
    denominator = np.where(valid, denominator, 1.)
    results = []
    for position in positions:
        position = np.asarray(position, float)
        ap = position - a
        d20, d21 = (ap * ab).sum(1), (ap * ac).sum(1)
        v = (d11 * d20 - d01 * d21) / denominator
        w = (d00 * d21 - d01 * d20) / denominator
        bary = np.stack([1 - v - w, v, w], 1)
        inside = valid & (bary.min(1) >= 0)
        points = a + v[:, None] * ab + w[:, None] * ac
        distances = np.where(inside, ((points - position) ** 2).sum(1), np.inf)
        for start, end, i, j in ((a, b, 0, 1), (b, c, 1, 2), (c, a, 2, 0)):
            edge = end - start
            t = np.clip(((position - start) * edge).sum(1) / np.maximum((edge * edge).sum(1), 1e-18), 0, 1)
            closest = start + t[:, None] * edge
            distance = ((closest - position) ** 2).sum(1)
            replace = valid & (distance < distances)
            points[replace], distances[replace] = closest[replace], distance[replace]
            bary[replace] = 0
            bary[replace, i], bary[replace, j] = 1 - t[replace], t[replace]
        index = int(distances.argmin())
        if distances[index] > max_distance ** 2:
            results.append(None)
            continue
        vertices, weights = mesh.indices[ids[index]], bary[index]
        results.append({"position": points[index], "triangle": int(ids[index]),
                        "normal": normalize(weights @ mesh.normals[vertices]),
                        "uv": weights @ mesh.uvs[vertices], "distance": float(np.sqrt(distances[index]))})
    return results


def preview(engine, source, mapping=None, max_distance=None):
    from .mesh import load_mesh
    mesh = (load_mesh(str(source), xform=engine.mesh.extra.get("xform"))
            if isinstance(source, (str, os.PathLike)) else copy.deepcopy(source))
    if (not len(mesh.indices) or not np.isfinite(mesh.positions).all() or not np.isfinite(mesh.uvs).all()
            or not np.isfinite(mesh.normals).all() or int(mesh.indices.max()) >= len(mesh.positions)):
        raise ValueError("Revision needs finite geometry and valid UVs")
    tiled = any(getattr(ts, "tiles", None) is not None for ts in engine.sets)
    if tiled:
        from .tiles import partition
        partition(mesh)
    elif np.any(mesh.uvs < -1e-6) or np.any(mesh.uvs > 1 + 1e-6):
        raise ValueError("Mesh reimport currently requires UVs in tile 0–1")
    if (engine.mesh.extra.get("tangent_basis", {}).get("name") == "MikkTSpace"
            and mesh.extra.get("tangent_basis") != engine.mesh.extra.get("tangent_basis")):
        from .tangents import mikk_mesh
        mesh = mikk_mesh(mesh)
    from .authored import validate as validate_authored
    for texture_set in engine.sets:
        for root in getattr(texture_set,"layers",[]):
            for layer in root.walk():
                if layer.authored is not None and layer.authored["kind"]!="text":validate_authored(layer.authored,mesh)
    old = engine.mesh
    if old.extra.get("physical") is not None:
        mesh.extra["physical"] = copy.deepcopy(old.extra["physical"])
    if old.extra.get("xform") is not None:
        mesh.extra["xform"] = copy.deepcopy(old.extra["xform"])
    mapping = {} if mapping is None else mapping
    if set(mapping) - {ts.pid for ts in engine.sets}:
        raise ValueError("Unknown source texture-set identity")
    sets, used = [], set()
    for ts in engine.sets:
        names = [old.material_names[index] for index in ts.materials]
        materials = list(mapping[ts.pid]) if ts.pid in mapping else [
            index for index, name in enumerate(mesh.material_names) if name in names]
        if any(type(index) is not int or not 0 <= index < len(mesh.material_names) for index in materials):
            raise ValueError("Invalid revision material mapping")
        if len(set(materials)) != len(materials) or used.intersection(materials):
            raise ValueError("Each new material can be assigned to only one texture set")
        used.update(materials)
        before = old.uvs[old.indices[ts.tri_ids]]
        ids = np.flatnonzero(np.isin(mesh.tri_material, materials))
        after = mesh.uvs[mesh.indices[ids]]
        unchanged = before.shape == after.shape and np.allclose(before, after, atol=1e-7, rtol=0)
        sets.append({"pid": ts.pid, "name": ts.name, "materials": materials, "triangles": len(ids),
                     "unmapped": not materials, "uv_unchanged": bool(unchanged)})
    distance = float(engine.mesh.radius * .1 if max_distance is None else max_distance)
    if not np.isfinite(distance) or distance <= 0:
        raise ValueError("Projection distance must be finite and positive")
    report = {"old_revision": mesh_revision(old), "new_revision": mesh_revision(mesh),
              "old_bounds": [value.tolist() for value in old.bounds], "new_bounds": [value.tolist() for value in mesh.bounds],
              "normalization": copy.deepcopy(old.extra.get("xform")),
              "scale_policy": "Preserve existing source transform; Mesh arguments use project coordinates",
              "sets": sets, "new_materials": [index for index in range(len(mesh.material_names)) if index not in used],
              "max_distance": distance, "missed_samples": 0, "reprojected_dabs": 0, "warnings": [], "checkpoint": None}
    return mesh, report


class ProjectionError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__(f"Mesh projection missed {report['missed_samples']} samples/dabs; increase distance or revise mapping")


def _project_operation(operation, mesh, materials, report):
    op = copy.deepcopy(operation)
    triangles = np.flatnonzero(np.isin(mesh.tri_material, materials))
    positions = [record["values"]["hit"] for record in op["dabs"]]
    hits = correspondence(mesh, positions, triangles, report["max_distance"])
    for record, hit in zip(op["dabs"], hits):
        if hit is None:
            report["missed_samples"] += 1
            continue
        values, normal = record["values"], hit["normal"]
        frame = np.asarray(values["frame"])
        if np.dot(normal, frame[2]) < .25:
            report["missed_samples"] += 1
            continue
        tangent = normalize(frame[0] - normal * np.dot(frame[0], normal))
        if np.linalg.norm(tangent) < .5:
            tangent = normalize(np.cross(frame[1], normal))
        values["frame"] = [tangent.tolist(), np.cross(normal, tangent).tolist(), normal.tolist()]
        values["hit"], values["hit_uv"] = hit["position"].tolist(), hit["uv"].tolist()
        view = op["views"][record["view"]]
        clip = np.asarray(view["vp"]) @ np.append(hit["position"], 1.)
        if clip[3] <= 1e-9:
            report["missed_samples"] += 1
            continue
        values["hit_px"] = ((clip[:2] / clip[3] * .5 + .5) * view["size"]).tolist()
        values["radius_uv"] = values["radius"] / max(mesh.topology.uv_scale(hit["triangle"]), 1e-9)
        report["reprojected_dabs"] += 1
    samples = [sample for sample in op["samples"] if sample["event"] != "break"]
    for sample, hit in zip(samples, correspondence(mesh, [sample["position"] for sample in samples], triangles, report["max_distance"])):
        if hit is None:
            report["missed_samples"] += 1
        else:
            sample.update(position=hit["position"].tolist(), normal=hit["normal"].tolist(),
                          uv=hit["uv"].tolist(), triangle=hit["triangle"])
    op["mesh_revision"] = report["new_revision"]
    return op


class PreparedRevision:
    def __init__(self, engine, stage, before, report):
        self.engine, self.stage, self.before, self.report = engine, stage, before, report
        self.signature, self.serial = engine._signature(), engine._edit_serial
        self.scene = None

    def cancel(self):
        if self.stage is None:
            return
        stage, self.stage = self.stage, None
        for layer in stage._loading_layers:
            stage._release_layer(layer)
        stage._release_project()
        stage.resources.release()
        if stage.renderer.env_tex is not None:
            stage.renderer.env_tex.release()
        if stage._project_tempdir is not None:
            stage._project_tempdir.cleanup()
        self.before = None

    def commit(self):
        from . import projectio
        if self.stage is None:
            raise ValueError("This mesh revision is no longer pending")
        e = self.engine
        if e._signature() != self.signature or e._edit_serial != self.serial:
            raise ValueError("The project changed after staging; prepare the revision again")
        root = Path(os.environ.get("STRATA_RESOURCE_CACHE", str(Path.home() / ".strata" / "cache"))) / "revisions"
        root.mkdir(parents=True, exist_ok=True)
        checkpoint = root / (uuid.uuid4().hex + ".strata")
        projectio.atomic_write(str(checkpoint), *self.before[:3])
        self.report["checkpoint"] = str(checkpoint)
        self.stage.mesh.extra["reimport"] = copy.deepcopy(self.report)
        e._adopt_project_stage(self.stage, self.scene, e.project_path)
        self.stage = None
        self.before = None
        e.mark_modified()
        e.reimport_checkpoint = str(checkpoint)
        e.project_diagnostics.append({"code": "mesh_reimport_checkpoint", "severity": "info",
                                      "message": "Pre-reimport project retained at " + str(checkpoint)})
        return self.report


class _StageRenderer(SimpleNamespace):
    def __getattr__(self, name):
        return getattr(self.delegate, name)


def prepare(engine, source, mapping=None, max_distance=None, progress=None):
    """Stage geometry, bakes and replay before exposing a commit action."""
    from . import projectio
    from .resources import Resources, BUILTIN_ALPHAS
    from .painter import Painter
    from .renderer import Camera
    from .layers import Brush
    from .evaluation import evaluate_raster
    from .paintstore import PaintTextures
    engine.commit_edit()
    engine.end_stroke()
    mesh, report = preview(engine, source, mapping, max_distance)
    if any(ts.tiles is not None for ts in engine.sets):
        if (not np.array_equal(mesh.uvs, engine.mesh.uvs) or not np.array_equal(mesh.indices, engine.mesh.indices)
                or not np.array_equal(mesh.tri_material, engine.mesh.tri_material)
                or any(item["unmapped"] or not item["uv_unchanged"] for item in report["sets"])):
            raise ValueError("Tiled revisions currently require unchanged UVs, topology and material assignments; original project preserved")
        for ts, item in zip(engine.sets, report["sets"]):
            if list(ts.materials) != item["materials"]:
                raise ValueError("Tiled revisions require unchanged material assignments; original project preserved")
    root = Path(os.environ.get("STRATA_RESOURCE_CACHE", str(Path.home() / ".strata" / "cache")))
    root.mkdir(parents=True, exist_ok=True)
    path = str(root / "revision-stage.strata")
    before = engine._project_snapshot(path, portable=True)
    meta, arrays, blobs = copy.deepcopy(before[0]), dict(before[1]), before[2]
    for name in ("positions", "normals", "uvs", "indices", "tangents", "curvature", "parts", "colors", "tri_material"):
        arrays["mesh_" + name] = getattr(mesh, name)
    meta.update(mesh_name=mesh.name, material_names=mesh.material_names,
                part_names=mesh.part_names, mesh_extra=copy.deepcopy(mesh.extra))
    for sd, assignment in zip(meta["sets"], report["sets"]):
        sd["materials"] = assignment["materials"]
        sd.pop("cache", None)
        if sd.get("tiles") is not None:
            tiles = sd["tiles"]
            tiles["mesh_revision"] = report["new_revision"]
            for index, operation in enumerate(tiles["operations"]):
                operation.setdefault("mesh_revisions", []).append(operation["mesh_revision"])
                if operation["coordinate_space"] == "surface":
                    tiles["operations"][index] = _project_operation(operation, mesh, assignment["materials"], report)
                else:
                    operation["mesh_revision"] = report["new_revision"]
        if assignment["unmapped"]:
            report["warnings"].append(sd["name"] + ": unmapped content retained as an unassigned texture set")
        if not assignment["uv_unchanged"]:
            report["warnings"].append(sd["name"] + ": raster bases/checkpoints retain their original UV coordinates")
        if sd.get("bake", {}).get("external_maps"):
            report["warnings"].append(sd["name"] + ": imported mesh maps retain their original raster coordinates")
    for material in report["new_materials"]:
        meta["sets"].append({"name": mesh.material_names[material], "pid": uuid.uuid4().hex,
                             "materials": [material], "res": engine.res, "selected": -1, "layers": [],
                             "bake": {"ao_samples": 4}})
    journal = Journal.load(meta.get("journal"), arrays)
    assignments = {assignment["pid"]: assignment for assignment in report["sets"]}
    for key in list(journal.heads):
        chain = journal.chain(key)
        operations = chain[1:]
        if not operations:
            continue
        selected = [assignments.get(node["operation"]["set_pid"]) for node in operations]
        if any(not assignment or assignment["unmapped"] for assignment in selected):
            journal.heads.pop(key)
            report["warnings"].append(key + ": unmapped native result retained as raster")
            continue
        if any(not assignment["uv_unchanged"] and node["operation"]["coordinate_space"] == "uv"
               for node, assignment in zip(operations, selected)):
            journal.heads.pop(key)
            report["warnings"].append(key + ": changed UV correspondence; native UV result retained as raster")
            continue
        base = copy.deepcopy(chain[0])
        base["parent"] = journal.heads.get(key)
        uid = uuid.uuid4().hex
        journal.nodes[uid] = base
        for node, assignment in zip(operations, selected):
            op = node["operation"]
            op = (_project_operation(op, mesh, assignment["materials"], report)
                  if op["coordinate_space"] == "surface" else copy.deepcopy(op))
            op["mesh_revision"] = report["new_revision"]
            next_uid = uuid.uuid4().hex
            journal.nodes[next_uid] = {"parent": uid, "key": key, "kind": "stroke", "operation": op}
            uid = next_uid
        journal.heads[key] = uid
    if report["missed_samples"]:
        raise ProjectionError(report)
    if journal.nodes:
        meta["version"], meta["journal"] = max(meta["version"], 7), journal.snapshot(arrays)
    resolved, records, diagnostics, temporary = projectio.resolve_resources(meta, blobs, path, BUILTIN_ALPHAS)
    stage = object.__new__(type(engine))
    stage.__dict__ = engine.__dict__.copy()
    stage.sets, stage.undo_stack, stage.redo_stack = [], [], []
    stage._tile_stroke = None
    stage.gm, stage.mesh, stage._stroke, stage._stroke_layer, stage._edit_transaction = None, None, None, None, None
    stage.high_meshes, stage._high_hashes, stage._loading_layers = {}, {}, []
    stage.resources = Resources(engine.gpu)
    stage.painter = Painter(engine.gpu, stage.resources)
    stage.camera, stage.brush = Camera(), Brush()
    stage.renderer = _StageRenderer(delegate=engine.renderer, gpu=engine.gpu, env_tex=None, env_path=None)
    stage.project_resources, stage.project_diagnostics, stage._project_tempdir = records, diagnostics, temporary
    prepared = PreparedRevision(engine, stage, before, report)
    allocations = []
    try:
        stage._restore_project(resolved, meta, arrays, progress)
        seen = set()
        for ts in stage.sets:
            if not len(ts.tri_ids):
                continue
            if ts.tiles is not None and any(op["coordinate_space"] == "surface" for op in ts.tiles.operations):
                original = next(source for source in engine.sets if source.pid == ts.pid)
                ts.tiles.store.limit = ts.tiles.base.limit = original.tiles.store.limit
                regenerated = ts.tiles.resized(ts.res)
                ts.tiles.close()
                ts.tiles = regenerated
            for layer in stage._walk(ts.layers):
                targets = [(layer, "layer", layer.tex), (layer, "mask", layer.mask_tex)]
                targets.extend((effect, "mask", effect.tex) for effect in layer.mask_effects)
                for owner, kind, original in targets:
                    key = stage.journal.key(owner, kind)
                    if original is None or key in seen or key not in stage.journal.heads:
                        continue
                    seen.add(key)
                    size = layer.raster_res or ts.res
                    replacement = evaluate_raster(stage, ts, owner, kind, original, size, allocations)
                    if kind == "layer":
                        stage.painter.forget(layer)
                        for texture in original.values():
                            texture.release()
                        owner.tex = PaintTextures(engine.gpu, size, replacement)
                    else:
                        stage.painter.forget_textures([original])
                        original.release()
                        if owner is layer:
                            owner.mask_tex = replacement
                        else:
                            owner.tex = replacement
        stage.update()
        for ts in stage.sets:
            if ts.tiles is not None:
                for address in ts.tile_addresses:
                    with ts.tiles.evaluate(address):
                        pass
        prepared.scene = engine.renderer.program_for(stage.color)
        report["warnings"].extend(item["message"] for item in stage.project_diagnostics)
        live = {id(texture) for layer in stage.all_layers_all_sets() for texture in
                [*(layer.tex or {}).values(), layer.mask_tex, *(effect.tex for effect in layer.mask_effects)] if texture is not None}
        for texture in {id(texture): texture for texture in allocations}.values():
            if id(texture) not in live:
                texture.release()
        return prepared
    except Exception:
        prepared.cancel()
        for texture in {id(texture): texture for texture in allocations}.values():
            texture.release()
        raise
    finally:
        if engine.renderer.pick_pos is not None:
            engine.renderer.render_pick(engine.gm, engine._vp, *engine.view_size)
        engine.gpu.release_scratch()
