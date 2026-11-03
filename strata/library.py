"""On-disk library: smart materials, smart masks, brush presets, export templates and imported
resources (alphas, textures, environments).

Smart materials and masks are .zip files holding a JSON description plus any painted data (paint
and mask textures) as float16 arrays; they are resampled to the target texture set on load.
"""
from __future__ import annotations

import io
import base64
import copy
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
import uuid

import numpy as np

from .layers import (Layer, Effect, MaskGen, Brush, CH_KEYS, group as make_group, N_CH,
                     bind_anchor_references, renew_persistent_ids)

KINDS = {
    "smart_materials": ".ssmat",
    "smart_masks": ".ssmask",
    "brushes": ".sbrush",
    "templates": ".json",
    "alphas": None,
    "textures": None,
    "environments": None,
}


def library_root() -> str:
    root = os.environ.get("STRATA_LIBRARY") or os.path.join(os.path.expanduser("~"), ".strata", "library")
    os.makedirs(root, exist_ok=True)
    return root


def library_dir(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown library kind {kind}")
    d = os.path.join(library_root(), kind)
    os.makedirs(d, exist_ok=True)
    return d


def list_library(kind: str) -> list[tuple[str, str]]:
    """[(display name, path)] for one kind, sorted by name."""
    d = library_dir(kind)
    ext = KINDS[kind]
    out = []
    for f in sorted(os.listdir(d)):
        if ext is None or f.lower().endswith(ext):
            out.append((os.path.splitext(f)[0], os.path.join(d, f)))
    return out


def import_resource(path: str, kind: str) -> str:
    """Copy a file (alpha, texture, environment, ...) into the library; returns the new path."""
    dst = os.path.join(library_dir(kind), os.path.basename(path))
    if os.path.abspath(dst) != os.path.abspath(path):
        shutil.copy2(path, dst)
    return dst


def import_native(path, kind):
    if kind in ("smart_materials", "smart_masks"):
        meta, _ = _read_native(path)
        expected = "smart_material" if kind == "smart_materials" else "smart_mask"
        if meta.get("type") != expected:
            raise ValueError("Native asset type does not match the selected category")
    elif kind == "brushes":
        load_brush_preset(Brush(), path)
    elif kind == "templates":
        from .exporter import load_template
        load_template(path)
    else:
        raise ValueError("Unknown native asset category")
    source = Path(path)
    destination = Path(library_dir(kind)) / source.name
    if destination.is_file() and source.read_bytes() != destination.read_bytes():
        destination = destination.with_name(source.stem + "-" + hashlib.sha256(source.read_bytes()).hexdigest()[:8] + source.suffix)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
        if Path(str(source) + ".png").is_file():
            shutil.copy2(str(source) + ".png", str(destination) + ".png")
    return str(destination)


def _default_path(kind, name):
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip() or "Untitled"
    return os.path.join(library_dir(kind), safe + (KINDS[kind] or ""))


def _refs(meta):
    layers = meta.get("layers", [{"mask_effects": meta.get("mask_effects", [])}])
    return {"sets": [{"layers": layers}], "brush": meta.get("brush", {})}


def _pack(meta, path):
    from .projectio import package_resources
    from .alphas import BUILTIN_ALPHAS
    refs, blobs, records, diagnostics = package_resources(_refs(meta), path, True, builtin_alphas=BUILTIN_ALPHAS)
    if diagnostics:
        raise ValueError("Native asset has missing dependencies; relink before saving")
    out = copy.deepcopy(meta)
    if "layers" in out:
        out["layers"] = refs["sets"][0]["layers"]
    elif "mask_effects" in out:
        out["mask_effects"] = refs["sets"][0]["layers"][0]["mask_effects"]
    if "brush" in out:
        out["brush"] = refs["brush"]
    out["resources"] = records
    return out, blobs


def _unpack(meta, blobs):
    from .projectio import resource_slots
    out = copy.deepcopy(meta)
    root = Path(os.environ.get("STRATA_RESOURCE_CACHE", str(Path.home() / ".strata" / "cache"))) / "native-assets"
    resolved = {}
    for record in out.get("resources", []):
        member = record["member"]
        content = blobs[member]
        digest = hashlib.sha256(content).hexdigest()
        if digest != record["sha256"] or digest != record["id"]:
            raise ValueError("Native asset dependency hash mismatch")
        suffix = Path(member).suffix
        if len(suffix) > 12 or not suffix[1:].isalnum():
            suffix = ".bin"
        path = root / (digest + suffix)
        root.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            path.write_bytes(content)
        resolved[digest] = str(path)
    refs = _refs(out)
    for owner, key, _ in resource_slots(refs):
        value = owner[key]
        if isinstance(value, str) and value.startswith("resource:"):
            owner[key] = resolved[value[9:]]
    return out


def _archive(path, meta, arrays):
    meta, blobs = _pack(meta, path)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    temporary = str(path) + ".tmp-" + uuid.uuid4().hex
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("smart.json", json.dumps(meta, indent=1))
            archive.writestr("data.npz", buffer.getvalue())
            for member, content in blobs.items():
                archive.writestr(member, content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _read_native(path):
    with zipfile.ZipFile(path) as archive:
        meta = json.loads(archive.read("smart.json"))
        blobs = {r["member"]: archive.read(r["member"]) for r in meta.get("resources", [])}
        data = np.load(io.BytesIO(archive.read("data.npz")), allow_pickle=False)
    return _unpack(meta, blobs), data


def _thumbnail(engine, path):
    from PIL import Image
    engine.update()
    values = engine.gpu.read(engine.comp.color)[::-1, :, :3]
    if engine.color.managed:
        values = engine.color.display_values(values)
    Image.fromarray(np.uint8(np.clip(values, 0, 1) * 255 + .5)).resize((128, 128)).save(str(path) + ".png")


# ---------------------------------------------------------------------------------- smart materials
def save_smart_material(engine, layers, path: str | None = None, name: str | None = None) -> str:
    """Save a layer, a group, or a list of layers (with their painted data) as a smart material."""
    if isinstance(layers, Layer):
        layers = [layers]
    if any(getattr(engine, "_material_tiles_for", lambda _: None)(layer) is not None for layer in layers):
        raise ValueError("Tile-aware native material assets are not integrated yet; save the portable project to retain all tile data.")
    bind_anchor_references(engine.layers)
    name = name or (layers[0].name if len(layers) == 1 else "Smart material")
    path = path or _default_path("smart_materials", name)
    arrays, dicts = {}, []

    def ser(lay, pid):
        d = lay.to_dict()
        d["_id"] = pid
        if lay.tex:
            for k, t in lay.tex.items():
                arrays[f"{pid}_{k}"] = engine.gpu.read(t).astype(np.float16)
        if lay.mask_tex is not None:
            arrays[f"{pid}_mask"] = engine.gpu.read(lay.mask_tex).astype(np.float16)
        for effect in lay.mask_effects:
            if effect.tex is not None:
                arrays[f"effect_{effect.pid}"] = engine.gpu.read(effect.tex).astype(np.float16)
        d["children"] = [ser(c, f"{pid}c{i}") for i, c in enumerate(lay.children)]
        return d

    dicts = [ser(l, f"L{i}") for i, l in enumerate(layers)]
    meta = {"type": "smart_material", "name": name, "res": engine.res, "layers": dicts,
            "color_mode": engine.color.settings.mode,
            "color_resources": dict(engine.color.settings.resource_spaces)}
    _archive(path, meta, arrays)
    _thumbnail(engine, path)
    return path


def _upload(engine, arr: np.ndarray, res: int, comps: int):
    g = engine.gpu
    h, w = arr.shape[:2]
    src = g.texture((w, h), comps)
    src.write(np.ascontiguousarray(arr.reshape(h, w, -1)[..., :comps], np.float16).tobytes())
    if (w, h) == (res, res):
        return src
    out = g.resample(src, (res, res))
    src.release()
    return out


def load_smart_material(engine, path: str, index: int | None = None, parent: Layer | None = None,
                        as_group: bool = True) -> Layer:
    """Insert a smart material into the active texture set. Returns the inserted group (or the
    first layer when as_group=False and it holds several)."""
    meta, data = _read_native(path)
    if engine.ts.tiles is not None and len(data.files):
        raise ValueError("Tile-aware native raster material imports are not integrated yet; use a portable project to retain painted data.")
    def physical(nodes):
        return any(node.get("proj", {}).get("repeat_meters", 0) or physical(node.get("children", [])) for node in nodes)
    if physical(meta.get("layers", [])):
        from .uvprep import meters_per_project_unit
        meters_per_project_unit(engine.mesh)
    if engine.color.managed:
        # A reusable asset must not inherit a conflicting project interpretation.
        # Reject before allocating/inserting; the source profile remains portable.
        expected = meta.get("color_resources", {})
        actual = engine.color.settings.resource_spaces
        for resource in meta.get("resources", []):
            digest = resource["sha256"]
            if expected.get(digest) != actual.get(digest):
                raise ValueError("Native asset image interpretation differs; match its saved color profile before importing")
    if meta.get("color_mode", "legacy") != engine.color.settings.mode:
        def raster_colors(nodes):
            for node in nodes:
                if node.get("kind") == "paint" and any(str(node.get("_id")) + "_" + key in data for key in ("C", "E")):
                    return True
                if raster_colors(node.get("children", [])):
                    return True
            return False
        if raster_colors(meta.get("layers", [])):
            raise ValueError("Raster asset color mode differs; use a matching project to preserve its painted colors")
    res = engine.res

    def build(d):
        lay = Layer.from_dict({k: v for k, v in d.items() if k != "children"})
        lay.children = [build(c) for c in d.get("children", [])]
        pid = d.get("_id")
        if lay.kind == "paint":
            engine._alloc_paint(lay, res)
            for k in CH_KEYS:
                key = f"{pid}_{k}"
                comps = 4 if k in ("C", "N", "E") else 2
                if key in data:
                    lay.tex[k] = _upload(engine, data[key], res, comps)
        if f"{pid}_mask" in data:
            lay.mask_tex = _upload(engine, data[f"{pid}_mask"], res, 1)
        for effect in lay.mask_effects:
            if effect.kind == "paint":
                key = f"effect_{effect.pid}"
                if key not in data:
                    raise ValueError("Smart material is missing paint-effect pixels")
                effect.tex = _upload(engine, data[key], res, 1)
        if lay.tex or lay.mask_tex is not None or any(effect.tex is not None for effect in lay.mask_effects):
            lay.raster_res = res
        return lay

    layers = [build(d) for d in meta["layers"]]
    bind_anchor_references(layers)
    renew_persistent_ids(layers)
    if as_group and not (len(layers) == 1 and layers[0].is_group):
        grp = make_group(meta.get("name", "Smart material"), children=layers)
        grp.enabled = [True] * N_CH
        layers = [grp]
    engine._push_undo(engine._snapshot_stack())
    first = None
    for i, lay in enumerate(layers):
        ins = engine.add_layer(layer=lay, index=None if index is None else index + i, parent=parent, record=False)
        first = first or ins
    return first


# ---------------------------------------------------------------------------------- smart masks
def smart_mask_dict(layer: Layer) -> dict:
    from dataclasses import asdict
    return {"type": "smart_mask", "name": layer.name + " mask", "gen": asdict(layer.gen),
            "mask_effects": [e.to_dict() for e in layer.mask_effects], "part_mask": layer.part_mask}


def save_smart_mask(engine, layer: Layer, path: str | None = None, name: str | None = None,
                    include_paint=True) -> str:
    """Save a layer's mask stack (generator, mask effects and optionally its painted mask)."""
    if getattr(engine, "_material_tiles_for", lambda _: None)(layer) is not None:
        raise ValueError("Tile-aware native mask assets are not integrated yet; save the portable project to retain all tile data.")
    bind_anchor_references(engine.layers)
    d = smart_mask_dict(layer)
    d["name"] = name or d["name"]
    path = path or _default_path("smart_masks", d["name"])
    buf = io.BytesIO()
    arrays = {}
    if include_paint and layer.has_mask and layer.mask_tex is not None:
        arrays["mask"] = engine.gpu.read(layer.mask_tex).astype(np.float16)
    for effect in layer.mask_effects:
        if effect.tex is not None:
            arrays[f"effect_{effect.pid}"] = engine.gpu.read(effect.tex).astype(np.float16)
    _archive(path, d, arrays)
    _thumbnail(engine, path)
    return path


def apply_smart_mask(engine, layer: Layer, source, replace: bool = False):
    """Apply a smart mask (path, dict, or a built-in name from presets.SMART_MASKS) to a layer.
    Effects are appended (like dropping several smart masks); replace=True swaps the whole stack."""
    from .presets import SMART_MASKS
    data = None
    if isinstance(source, str) and source in SMART_MASKS:
        d = {"mask_effects": [e.to_dict() for e in SMART_MASKS[source]()]}
    elif isinstance(source, dict):
        d = source
    else:
        d, data = _read_native(source)
    if (data is not None and len(data.files) and
            getattr(engine, "_material_tiles_for", lambda _: None)(layer) is not None):
        raise ValueError("Tile-aware native raster mask imports are not integrated yet; use a portable project to retain painted data.")
    effects = [Effect.from_dict(e) for e in d.get("mask_effects", [])]
    resolution = layer.raster_res or engine.res
    for effect in effects:
        if effect.kind == "paint" and (data is None or f"effect_{effect.pid}" not in data):
            raise ValueError("Smart mask is missing paint-effect pixels")
    for effect in effects:
        if effect.kind == "paint":
            key = f"effect_{effect.pid}"
            if data is None or key not in data:
                raise ValueError("Smart mask is missing paint-effect pixels")
            effect.tex = _upload(engine, data[key], resolution, 1)
    renew_persistent_ids(Layer("Imported mask", mask_effects=effects))
    engine._push_undo(engine._snapshot_stack())
    if replace:
        layer.mask_effects = effects
        layer.gen = MaskGen(**{k: v for k, v in d.get("gen", {}).items() if k in MaskGen.__dataclass_fields__})
    else:
        layer.mask_effects = list(layer.mask_effects) + effects
        if d.get("gen") and d["gen"].get("kind", 0) and layer.gen.kind == 0:
            layer.gen = MaskGen(**{k: v for k, v in d["gen"].items() if k in MaskGen.__dataclass_fields__})
    if d.get("part_mask") is not None and (replace or layer.part_mask is None):
        layer.part_mask = list(d["part_mask"])
    if data is not None and "mask" in data:
        if layer.mask_tex is not None:
            layer.mask_tex.release()
        layer.mask_tex = _upload(engine, data["mask"], resolution, 1)
        layer.has_mask = True
    if layer.mask_tex is not None or any(effect.tex is not None for effect in layer.mask_effects):
        layer.raster_res = resolution
    engine.dirty = True
    return layer


# ---------------------------------------------------------------------------------- brush presets
def save_brush_preset(brush: Brush, path: str | None = None, name: str = "Brush") -> str:
    path = path or _default_path("brushes", name)
    meta, blobs = _pack({"type": "brush", "name": name, "brush": brush.to_dict()}, path)
    meta["embedded"] = {member: base64.b64encode(content).decode("ascii") for member, content in blobs.items()}
    temporary = str(path) + ".tmp-" + uuid.uuid4().hex
    try:
        Path(temporary).write_text(json.dumps(meta, indent=1), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    from PIL import Image
    from .alphas import BUILTIN_ALPHAS, make_alpha
    from .imageio import read_image
    alpha = (brush.alpha or "Round").removeprefix("builtin:")
    values = make_alpha(alpha) if alpha in BUILTIN_ALPHAS or not brush.alpha else read_image(brush.alpha)[::-1].mean(axis=2)
    if brush.alpha_invert:
        values = 1 - values
    Image.fromarray(np.uint8(np.clip(values, 0, 1) * 255 + .5)).resize((128, 128)).save(str(path) + ".png")
    return path


def load_brush_preset(brush: Brush, path: str) -> Brush:
    with open(path) as f:
        d = json.load(f)
    if "resources" in d:
        d = _unpack(d, {member: base64.b64decode(content) for member, content in d.get("embedded", {}).items()})
    brush.load_dict(d.get("brush", d))
    return brush
