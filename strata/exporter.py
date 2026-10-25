"""Write texture sets to disk through output templates (channel packing, naming, formats, padding).

A template is a dict:

    {"name": "Unreal Engine (Packed)", "format": "png", "depth": "8",
     "maps": [
        {"name": "T_$textureSet_BaseColor", "rgb": "basecolor"},
        {"name": "T_$textureSet_Normal", "rgb": "normal_directx"},
        {"name": "T_$textureSet_OcclusionRoughnessMetallic", "r": "ao", "g": "roughness", "b": "metallic"},
        {"name": "T_$textureSet_Height", "l": "height", "depth": "16"},
     ]}

Each map uses either "rgb"/"rgba" (a colour source) or per-channel keys "r", "g", "b", "a", "l" (a
grey source, or "<source>.<r|g|b>" to pick a component). Per-map "format"/"depth" override the
template. Name tokens: $mesh, $textureSet, $project.

Sources: basecolor, roughness, metallic, height, opacity, emissive, normal_opengl,
normal_directx, ao, curvature, thickness, position, world_normal, id, glossiness / smoothness
(1 - roughness), diffuse (base colour of non-metals), specular (F0 colour), specular_level,
and constants 0, 1, 0.5.
"""
from __future__ import annotations

import copy
import json
import os
import re

import numpy as np

from .baker import PAD
from .imageio import FORMATS, EXT, write_image

PADDING = ["none", "infinite", "dilation_transparent", "dilation_background", "dilation_diffusion"]
SIZES = [None, 128, 256, 512, 1024, 2048, 4096, 8192]

_DOC = [
    {"name": "$mesh_$textureSet_BaseColor", "rgb": "basecolor"},
    {"name": "$mesh_$textureSet_Roughness", "l": "roughness"},
    {"name": "$mesh_$textureSet_Metallic", "l": "metallic"},
    {"name": "$mesh_$textureSet_Height", "l": "height", "depth": "16"},
    {"name": "$mesh_$textureSet_Normal", "rgb": "normal_opengl"},
    {"name": "$mesh_$textureSet_Emissive", "rgb": "emissive"},
    {"name": "$mesh_$textureSet_Opacity", "l": "opacity"},
    {"name": "$mesh_$textureSet_AO", "l": "ao"},
]

OUTPUT_TEMPLATES = {
    "Document channels + Normal + AO (No Alpha)": {"maps": _DOC},
    "Document channels + Normal + AO (With Alpha)": {"maps": [
        {"name": "$mesh_$textureSet_BaseColor", "rgb": "basecolor", "a": "opacity"}] + _DOC[1:6] + [_DOC[7]]},
    "Unreal Engine (Packed)": {"maps": [
        {"name": "T_$textureSet_BaseColor", "rgb": "basecolor"},
        {"name": "T_$textureSet_Normal", "rgb": "normal_directx"},
        {"name": "T_$textureSet_OcclusionRoughnessMetallic", "r": "ao", "g": "roughness", "b": "metallic"},
        {"name": "T_$textureSet_Emissive", "rgb": "emissive"},
        {"name": "T_$textureSet_Height", "l": "height", "depth": "16"}]},
    "Unity Universal Render Pipeline (Metallic Standard)": {"maps": [
        {"name": "$textureSet_BaseMap", "rgb": "basecolor", "a": "opacity"},
        {"name": "$textureSet_MetallicSmoothness", "r": "metallic", "g": "metallic", "b": "metallic", "a": "smoothness"},
        {"name": "$textureSet_Normal", "rgb": "normal_opengl"},
        {"name": "$textureSet_Occlusion", "l": "ao"},
        {"name": "$textureSet_Emission", "rgb": "emissive"},
        {"name": "$textureSet_Height", "l": "height", "depth": "16"}]},
    "Unity HD Render Pipeline (Metallic Standard)": {"maps": [
        {"name": "$textureSet_BaseMap", "rgb": "basecolor", "a": "opacity"},
        {"name": "$textureSet_MaskMap", "r": "metallic", "g": "ao", "b": "0", "a": "smoothness"},
        {"name": "$textureSet_Normal", "rgb": "normal_opengl"},
        {"name": "$textureSet_Emissive", "rgb": "emissive"},
        {"name": "$textureSet_Height", "l": "height", "depth": "16"}]},
    "glTF PBR Metal Roughness": {"maps": [
        {"name": "$mesh_$textureSet_baseColor", "rgb": "basecolor", "a": "opacity"},
        {"name": "$mesh_$textureSet_occlusionRoughnessMetallic", "r": "ao", "g": "roughness", "b": "metallic"},
        {"name": "$mesh_$textureSet_normal", "rgb": "normal_opengl"},
        {"name": "$mesh_$textureSet_emissive", "rgb": "emissive"}]},
    "Blender (Principled BSDF)": {"maps": [
        {"name": "$mesh_$textureSet_Base Color", "rgb": "basecolor"},
        {"name": "$mesh_$textureSet_Roughness", "l": "roughness"},
        {"name": "$mesh_$textureSet_Metallic", "l": "metallic"},
        {"name": "$mesh_$textureSet_Normal", "rgb": "normal_opengl"},
        {"name": "$mesh_$textureSet_Height", "l": "height", "depth": "16"},
        {"name": "$mesh_$textureSet_Emission", "rgb": "emissive"},
        {"name": "$mesh_$textureSet_Alpha", "l": "opacity"}]},
    "Sketchfab": {"maps": [
        {"name": "$mesh_$textureSet_BaseColor", "rgb": "basecolor"},
        {"name": "$mesh_$textureSet_Roughness", "l": "roughness"},
        {"name": "$mesh_$textureSet_Metallic", "l": "metallic"},
        {"name": "$mesh_$textureSet_Normal", "rgb": "normal_opengl"},
        {"name": "$mesh_$textureSet_AO", "l": "ao"},
        {"name": "$mesh_$textureSet_Emissive", "rgb": "emissive"},
        {"name": "$mesh_$textureSet_Opacity", "l": "opacity"}]},
    "Arnold (AiStandard)": {"maps": [
        {"name": "$mesh_$textureSet_BaseColor", "rgb": "basecolor"},
        {"name": "$mesh_$textureSet_Roughness", "l": "roughness"},
        {"name": "$mesh_$textureSet_Metalness", "l": "metallic"},
        {"name": "$mesh_$textureSet_Normal", "rgb": "normal_opengl"},
        {"name": "$mesh_$textureSet_Height", "l": "height", "format": "exr", "depth": "32f"},
        {"name": "$mesh_$textureSet_Emissive", "rgb": "emissive"},
        {"name": "$mesh_$textureSet_Opacity", "l": "opacity"}]},
    "PBR Specular Glossiness": {"maps": [
        {"name": "$mesh_$textureSet_Diffuse", "rgb": "diffuse", "a": "opacity"},
        {"name": "$mesh_$textureSet_Specular", "rgb": "specular"},
        {"name": "$mesh_$textureSet_Glossiness", "l": "glossiness"},
        {"name": "$mesh_$textureSet_Normal", "rgb": "normal_opengl"},
        {"name": "$mesh_$textureSet_AO", "l": "ao"},
        {"name": "$mesh_$textureSet_Height", "l": "height", "depth": "16"}]},
    "Mesh maps": {"maps": [
        {"name": "$mesh_$textureSet_ambient_occlusion", "l": "ao"},
        {"name": "$mesh_$textureSet_curvature", "l": "curvature"},
        {"name": "$mesh_$textureSet_thickness", "l": "thickness"},
        {"name": "$mesh_$textureSet_position", "rgb": "position"},
        {"name": "$mesh_$textureSet_world_space_normals", "rgb": "world_normal"},
        {"name": "$mesh_$textureSet_id", "rgb": "id"}]},
    # the three original Strata presets, unchanged file names
    "Strata: Unreal (BC / N DirectX / ORM)": {"maps": [
        {"name": "T_$project_BC", "rgb": "basecolor"},
        {"name": "T_$project_N", "rgb": "normal_directx"},
        {"name": "T_$project_ORM", "r": "ao", "g": "roughness", "b": "metallic"},
        {"name": "T_$project_H", "l": "height", "depth": "16"}]},
    "Strata: Unity (Albedo / Normal / Metallic+Smoothness)": {"maps": [
        {"name": "$project_Albedo", "rgb": "basecolor"},
        {"name": "$project_Normal", "rgb": "normal_opengl"},
        {"name": "$project_MetallicSmoothness", "r": "metallic", "g": "metallic", "b": "metallic", "a": "smoothness"},
        {"name": "$project_AO", "l": "ao"},
        {"name": "$project_Height", "l": "height", "depth": "16"}]},
    "Strata: Separate maps (OpenGL normal)": {"maps": [
        {"name": "$project_BaseColor", "rgb": "basecolor"},
        {"name": "$project_Roughness", "l": "roughness"},
        {"name": "$project_Metallic", "l": "metallic"},
        {"name": "$project_Normal", "rgb": "normal_opengl"},
        {"name": "$project_Height", "l": "height", "depth": "16"},
        {"name": "$project_AO", "l": "ao"}]},
}
for _n, _t in OUTPUT_TEMPLATES.items():
    _t.setdefault("name", _n)
    _t.setdefault("format", "png")
    _t.setdefault("depth", "8")

# Legacy list used by the original Export dialog: index -> template
EXPORT_PRESETS = ["Unreal Engine (BC / N DirectX / ORM)", "Unity (Albedo / Normal / Metallic+Smoothness)",
                  "Separate maps (OpenGL normal)"]
_LEGACY = ["Strata: Unreal (BC / N DirectX / ORM)", "Strata: Unity (Albedo / Normal / Metallic+Smoothness)",
           "Strata: Separate maps (OpenGL normal)"]

COLOR_SOURCES = {"basecolor", "emissive", "normal_opengl", "normal_directx", "position", "world_normal",
                 "id", "diffuse", "specular"}
SOURCES = sorted(COLOR_SOURCES | {"roughness", "metallic", "height", "opacity", "ao", "curvature",
                                  "thickness", "glossiness", "smoothness", "specular_level", "0", "1", "0.5"})
BACKGROUND = {"basecolor": (0.5, 0.5, 0.5), "normal_opengl": (0.5, 0.5, 1.0), "normal_directx": (0.5, 0.5, 1.0),
              "roughness": 0.6, "metallic": 0.0, "height": 0.5, "opacity": 1.0, "emissive": (0, 0, 0),
              "ao": 1.0}


# ---------------------------------------------------------------------------------- templates I/O
def save_template(template: dict, path: str):
    with open(path, "w") as f:
        json.dump(template, f, indent=1)


def load_template(path: str) -> dict:
    with open(path) as f:
        t = json.load(f)
    t.setdefault("format", "png")
    t.setdefault("depth", "8")
    t.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    return t


# ---------------------------------------------------------------------------------- pixel work
def _srgb2lin(c):
    c = np.clip(c, 0, None)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _lin2srgb(c):
    c = np.clip(c, 0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def pull_push(values: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Fill uncovered texels from coarser averages of covered ones (smooth 'diffusion' padding)."""
    v = values * cov[..., None]
    w = cov.astype(np.float32)
    levels = []
    while min(w.shape) > 1:
        levels.append((v, w))
        h, wd = w.shape
        h2, w2 = h // 2 * 2, wd // 2 * 2
        v = v[:h2, :w2].reshape(h2 // 2, 2, w2 // 2, 2, -1).sum((1, 3))
        w = w[:h2, :w2].reshape(h2 // 2, 2, w2 // 2, 2).sum((1, 3))
    filled = v / np.maximum(w, 1e-8)[..., None]
    for lv, lw in reversed(levels):
        up = np.repeat(np.repeat(filled, 2, 0), 2, 1)
        up = np.pad(up, ((0, lw.shape[0] - up.shape[0]), (0, lw.shape[1] - up.shape[1]), (0, 0)), mode="edge")
        a = np.clip(lw, 0, 1)[..., None]
        filled = lv / np.maximum(lw, 1e-8)[..., None] * a + up * (1 - a)
    return filled.astype(np.float32)


def _resize(img: np.ndarray, size: int) -> np.ndarray:
    h, w, c = img.shape
    if size == w:
        return img
    if size < w and w % size == 0:
        f = w // size
        return img.reshape(size, f, size, f, c).mean((1, 3))
    from PIL import Image
    return np.dstack([np.asarray(Image.fromarray(img[..., i].astype(np.float32), "F").resize(
        (size, size), Image.BICUBIC), np.float32) for i in range(c)])


class _SetData:
    """Reads (and pads) the composited channels and mesh maps of one texture set on demand."""

    def __init__(self, engine, ts, padding, dilation):
        self.e, self.ts, self.padding, self.dilation = engine, ts, padding, int(dilation)
        self._cache = {}
        g = engine.gpu
        self.iters = PAD if padding == "infinite" else self.dilation
        cov_tex = g.clone(ts.bakes.cov)
        self.cov = g.read(ts.bakes.cov)[::-1, :, 0] > 0.5
        if padding != "none" and self.iters > 0:
            g.dilate(cov_tex, ts.bakes.cov, self.iters)
        self.cov_dil = g.read(cov_tex)[::-1, :, 0] > 0.5 if padding != "none" else self.cov
        cov_tex.release()

    def _tex(self, name, tex, comps=None):
        key = name
        if key in self._cache:
            return self._cache[key]
        g = self.e.gpu
        t = g.clone(tex)
        if self.padding != "none":
            g.dilate(t, self.ts.bakes.cov, self.iters)
        a = g.read(t)[::-1].copy()
        t.release()
        if comps is not None:
            a = a[..., :comps]
        if self.padding in ("infinite", "dilation_diffusion"):
            a = np.where(self.cov_dil[..., None], a, pull_push(a, self.cov_dil))
        self._cache[key] = a
        return a

    def source(self, name: str) -> np.ndarray:
        """(H, W, C) float array for a source name (C = 3 for colour sources, else 1)."""
        comp, bakes = self.ts.comp, self.ts.bakes
        if name in ("0", "1", "0.5"):
            return np.full(self.cov.shape + (1,), float(name), np.float32)
        if name == "basecolor":
            return self._tex("C", comp.color, 3)
        rmho = lambda: self._tex("R", comp.rmh, 4)
        if name == "roughness":
            return rmho()[..., 0:1]
        if name == "metallic":
            return rmho()[..., 1:2]
        if name == "height":
            return rmho()[..., 2:3]
        if name == "opacity":
            return rmho()[..., 3:4]
        if name in ("glossiness", "smoothness"):
            return 1.0 - rmho()[..., 0:1]
        if name == "emissive":
            return self._tex("E", comp.emissive, 3)
        if name == "normal_opengl":
            return self._tex("N", comp.normal, 3)
        if name == "normal_directx":
            n = self._tex("N", comp.normal, 3).copy()
            n[..., 1] = 1.0 - n[..., 1]
            return n
        if name == "ao":
            return self._tex("AO", bakes.ao, 1)
        if name == "curvature":
            return self._tex("CV", bakes.curv, 1)
        if name == "thickness":
            return self._tex("TH", bakes.thick, 1)
        if name == "id":
            return self._tex("ID", bakes.id, 3)
        if name == "world_normal":
            return self._tex("WN", bakes.nrm, 3) * 0.5 + 0.5
        if name == "position":
            lo, hi = self.e.mesh.bounds
            p = self._tex("P", bakes.pos, 3)
            return (p - lo) / np.maximum(hi - lo, 1e-6)
        if name == "diffuse":
            c, m = _srgb2lin(self.source("basecolor")), self.source("metallic")
            return _lin2srgb(c * (1 - m))
        if name == "specular":
            c, m = _srgb2lin(self.source("basecolor")), self.source("metallic")
            return _lin2srgb(0.04 * (1 - m) + c * m)
        if name == "specular_level":
            return np.full(self.cov.shape + (1,), 0.5, np.float32)
        raise ValueError(f"unknown export source '{name}'")

    def channel(self, spec: str) -> np.ndarray:
        """One output channel (H, W): 'source' (grey, or luminance of a colour source) or 'source.g'."""
        base, _, comp = spec.partition(".")
        a = self.source(base)
        if comp:
            return a[..., "rgb".index(comp)]
        if a.shape[2] == 1:
            return a[..., 0]
        return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722

    def background(self, spec):
        v = BACKGROUND.get(spec.partition(".")[0], 0.0)
        return v


def _compose(data: _SetData, m: dict) -> np.ndarray:
    chans, names = [], []
    if "rgb" in m or "rgba" in m:
        src = m.get("rgb") or m.get("rgba")
        a = data.source(src)
        a = np.repeat(a, 3, 2) if a.shape[2] == 1 else a
        chans += [a[..., i] for i in range(3)]
        names += [f"{src}.{c}" for c in "rgb"]
        if "a" in m:
            chans.append(data.channel(m["a"])); names.append(m["a"])
    elif "l" in m:
        chans.append(data.channel(m["l"])); names.append(m["l"])
        if "a" in m:
            chans.append(data.channel(m["a"])); names.append(m["a"])
    else:
        for c in "rgba":
            if c in m:
                chans.append(data.channel(m[c])); names.append(m[c])
        if len(chans) == 2:     # r + g only: pad to RGB
            chans.append(np.zeros_like(chans[0])); names.append("0")
    img = np.stack(chans, -1).astype(np.float32)
    if data.padding == "dilation_background":
        out = ~data.cov_dil
        for i, n in enumerate(names):
            bg = data.background(n)
            comp = n.partition(".")[2]
            val = bg["rgb".index(comp)] if isinstance(bg, tuple) and comp else (bg[0] if isinstance(bg, tuple) else bg)
            img[out, i] = val
    return img


def _expand(pattern: str, engine, ts, project=None) -> str:
    def clean(s):
        return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_") or "Mesh"
    name = pattern.replace("$mesh", clean(engine.mesh.name)).replace("$textureSet", clean(ts.name))
    name = name.replace("$project", clean(project or engine.mesh.name))
    return name


# ---------------------------------------------------------------------------------- export
def export_textures(engine, folder: str, template="Unreal Engine (Packed)", file_format: str | None = None,
                    depth: str | None = None, size: int | None = None, padding: str = "infinite",
                    dilation: int = PAD, texture_sets=None, project: str | None = None,
                    shader_json: bool = False, overrides: dict | None = None) -> list[str]:
    """Export texture sets through an output template.

    template: name in OUTPUT_TEMPLATES, a template dict, or a path to a template JSON.
    file_format / depth: force one format for every map (else per-map, else the template's).
    size: output resolution (None = each texture set's own). padding: one of PADDING.
    texture_sets: indices or names to export (None = all). overrides: {map name pattern: {"enabled":
    bool, "format":, "depth":}}. Returns the written paths."""
    if isinstance(template, str):
        template = OUTPUT_TEMPLATES[template] if template in OUTPUT_TEMPLATES else load_template(template)
    if padding not in PADDING:
        raise ValueError(f"padding must be one of {PADDING}")
    os.makedirs(folder, exist_ok=True)
    engine.dirty = True
    engine.update()
    out = []
    sets = list(range(len(engine.sets))) if texture_sets is None else [
        (engine.sets.index(next(t for t in engine.sets if t.name == s)) if isinstance(s, str) else int(s))
        for s in texture_sets]
    for si in sets:
        ts = engine.sets[si]
        data = _SetData(engine, ts, padding, dilation)
        for m in template["maps"]:
            ov = (overrides or {}).get(m["name"], {})
            if ov.get("enabled") is False or m.get("enabled") is False:
                continue
            fmt = (file_format or ov.get("format") or m.get("format") or template.get("format", "png")).lower()
            dep = depth or ov.get("depth") or m.get("depth") or template.get("depth", "8")
            if fmt not in FORMATS:
                raise ValueError(f"unknown format {fmt}")
            if dep not in FORMATS[fmt]:          # nearest supported depth for the format
                dep = FORMATS[fmt][-1] if dep in ("16", "32f", "16f") else FORMATS[fmt][0]
            img = _compose(data, m)
            if padding == "dilation_transparent":
                alpha = data.cov_dil.astype(np.float32)
                img = np.dstack([img, alpha]) if img.shape[2] in (1, 3) else img
            if size and size != img.shape[1]:
                img = _resize(img, int(size))
            path = os.path.join(folder, _expand(m["name"], engine, ts, project) + EXT[fmt])
            write_image(path, img, dep)
            out.append(path)
        if shader_json:
            p = os.path.join(folder, _expand("$mesh_$textureSet", engine, ts, project) + "_material.json")
            with open(p, "w") as f:
                json.dump({"texture_set": ts.name, "template": template.get("name"),
                           "normal_strength": engine.normal_strength, "resolution": ts.res,
                           "maps": [_expand(m["name"], engine, ts, project) for m in template["maps"]]}, f, indent=1)
            out.append(p)
    return out


def export(engine, folder: str, preset: int = 0, name: str | None = None) -> list[str]:
    """Original Strata entry point: preset indexes EXPORT_PRESETS."""
    return export_textures(engine, folder, _LEGACY[int(preset)], padding="infinite", project=name)


def export_mesh(engine, path: str):
    """Write the project mesh as OBJ (positions, UVs, normals; one group per texture set)."""
    m = engine.mesh
    with open(path, "w") as f:
        f.write(f"# Strata export: {m.name}\n")
        for p in m.positions:
            f.write(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
        for t in m.uvs:
            f.write(f"vt {t[0]:.6f} {t[1]:.6f}\n")
        for n in m.normals:
            f.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
        for ts in engine.sets:
            f.write(f"g {ts.name}\nusemtl {ts.name}\n")
            for tri in m.indices[ts.tri_ids] + 1:
                a, b, c = tri
                f.write(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")
    return path
