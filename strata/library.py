"""On-disk library: smart materials, smart masks, brush presets, export templates and imported
resources (alphas, textures, environments).

Smart materials and masks are .zip files holding a JSON description plus any painted data (paint
and mask textures) as float16 arrays; they are resampled to the target texture set on load.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import zipfile

import numpy as np

from .layers import Layer, Effect, MaskGen, Brush, CH_KEYS, group as make_group, N_CH

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


def _default_path(kind, name):
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip() or "Untitled"
    return os.path.join(library_dir(kind), safe + (KINDS[kind] or ""))


# ---------------------------------------------------------------------------------- smart materials
def save_smart_material(engine, layers, path: str | None = None, name: str | None = None) -> str:
    """Save a layer, a group, or a list of layers (with their painted data) as a smart material."""
    if isinstance(layers, Layer):
        layers = [layers]
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
        d["children"] = [ser(c, f"{pid}c{i}") for i, c in enumerate(lay.children)]
        return d

    dicts = [ser(l, f"L{i}") for i, l in enumerate(layers)]
    meta = {"type": "smart_material", "name": name, "res": engine.res, "layers": dicts}
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("smart.json", json.dumps(meta, indent=1))
        z.writestr("data.npz", buf.getvalue())
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
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read("smart.json"))
        data = np.load(io.BytesIO(z.read("data.npz")))
    res = engine.res

    def build(d):
        lay = Layer.from_dict({k: v for k, v in d.items() if k != "children"})
        lay.children = [build(c) for c in d.get("children", [])]
        pid = d.get("_id")
        if lay.kind == "paint":
            lay.tex = {}
            for k in CH_KEYS:
                key = f"{pid}_{k}"
                comps = 4 if k in ("C", "N", "E") else 2
                if key in data:
                    lay.tex[k] = _upload(engine, data[key], res, comps)
                else:
                    t = engine.gpu.texture((res, res), comps)
                    engine.gpu.fill(t, (0, 0, 0, 0))
                    lay.tex[k] = t
        if f"{pid}_mask" in data:
            lay.mask_tex = _upload(engine, data[f"{pid}_mask"], res, 1)
        return lay

    layers = [build(d) for d in meta["layers"]]
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
    d = smart_mask_dict(layer)
    d["name"] = name or d["name"]
    path = path or _default_path("smart_masks", d["name"])
    buf = io.BytesIO()
    arrays = {}
    if include_paint and layer.has_mask and layer.mask_tex is not None:
        arrays["mask"] = engine.gpu.read(layer.mask_tex).astype(np.float16)
    np.savez_compressed(buf, **arrays)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("smart.json", json.dumps(d, indent=1))
        z.writestr("data.npz", buf.getvalue())
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
        with zipfile.ZipFile(source) as z:
            d = json.loads(z.read("smart.json"))
            data = np.load(io.BytesIO(z.read("data.npz")))
    engine._push_undo(engine._snapshot_stack())
    effects = [Effect.from_dict(e) for e in d.get("mask_effects", [])]
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
        layer.mask_tex = _upload(engine, data["mask"], engine.res, 1)
        layer.has_mask = True
    engine.dirty = True
    return layer


# ---------------------------------------------------------------------------------- brush presets
def save_brush_preset(brush: Brush, path: str | None = None, name: str = "Brush") -> str:
    path = path or _default_path("brushes", name)
    with open(path, "w") as f:
        json.dump({"type": "brush", "name": name, "brush": brush.to_dict()}, f, indent=1)
    return path


def load_brush_preset(brush: Brush, path: str) -> Brush:
    with open(path) as f:
        d = json.load(f)
    brush.load_dict(d.get("brush", d))
    return brush
