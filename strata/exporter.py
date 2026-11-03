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
template. Name tokens: $mesh, $textureSet, $project, $udim.

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
import shutil
import tempfile
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass

import numpy as np

from .imageio import FORMATS, EXT, write_image
from .channels import CHANNEL_DESCRIPTORS
from .userchannels import is_user

# Keep manifest planning usable without importing the OpenGL baker. This is the
# default export dilation, matching the baker's default rather than its state.
PAD = 16

PADDING = ["none", "infinite", "dilation_transparent", "dilation_background", "dilation_diffusion"]
SIZES = [None, 128, 256, 512, 1024, 2048, 4096, 8192]

_DOCUMENT_SUFFIXES = {"C": "BaseColor", "R": "Roughness", "M": "Metallic", "H": "Height",
                      "N": "Normal", "E": "Emissive", "O": "Opacity"}
_DOC = [{"name": "$mesh_$textureSet_" + _DOCUMENT_SUFFIXES[channel.key],
         "rgb" if channel.value_components == 3 else "l": channel.export_sources[0],
         **({"depth": "16"} if channel.key == "H" else {})}
        for channel in CHANNEL_DESCRIPTORS]
_DOC.append({"name": "$mesh_$textureSet_AO", "l": "ao"})

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

SOURCE_CHANNELS = {source: channel for channel in CHANNEL_DESCRIPTORS for source in channel.export_sources}
COLOR_SOURCES = {source for source, channel in SOURCE_CHANNELS.items() if channel.value_components == 3}
COLOR_SOURCES |= {"position", "world_normal", "id", "diffuse", "specular"}
SOURCES = sorted(set(SOURCE_CHANNELS) | COLOR_SOURCES | {"ao", "curvature", "thickness", "glossiness",
                                                       "smoothness", "specular_level", "coat", "coat_roughness", "displacement_meters", "0", "1", "0.5"})
BACKGROUND = {source: channel.composite_default for source, channel in SOURCE_CHANNELS.items()}
BACKGROUND["ao"] = 1.0
BACKGROUND["coat_roughness"] = .1


# ---------------------------------------------------------------------------------- templates I/O
def workflow_template(engine):
    """Derive outputs from the exact semantics consumed by viewport shaders."""
    workflow = engine.shader_workflow
    name = "PBR Specular Glossiness" if workflow["model"] == "spec_gloss" else "Blender (Principled BSDF)"
    template = copy.deepcopy(OUTPUT_TEMPLATES[name])
    template["name"] = "Active shader workflow"
    for semantic in ("coat", "coat_roughness"):
        if semantic in workflow["bindings"] or (semantic == "coat_roughness" and "coat" in workflow["bindings"]):
            template["maps"].append({"name": "$mesh_$textureSet_" + semantic, "l": semantic, "depth": "16"})
    if workflow["displacement_meters"]:
        template["maps"].append({"name": "$mesh_$textureSet_DisplacementMeters", "l": "displacement_meters", "format": "exr", "depth": "32f"})
    return template


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
        if is_user(name):
            if name not in comp.user_outputs:
                raise ValueError("Undeclared or unevaluated user channel: " + name)
            return self._tex(name, comp.user_outputs[name], 1)
        workflow = getattr(self.e, "shader_workflow", {"model": "metal_rough", "bindings": {}})
        bindings = workflow["bindings"]
        if workflow["model"] == "spec_gloss":
            if name in ("glossiness", "smoothness"):
                return np.clip(self.source(bindings["glossiness"]),0.,1.)
            if name == "roughness":
                return 1.0 - np.clip(self.source(bindings["glossiness"]),0.,1.)
            if name == "metallic":
                return np.zeros(self.cov.shape + (1,), np.float32)
            if name == "specular":
                # F0 channels are linear reflectance, including in LDR outputs.
                return np.clip(np.concatenate([self.source(bindings["specular_" + c]) for c in "rgb"], axis=2),0.,1.)
            if name == "diffuse":
                return self.source("basecolor")
        if name in ("coat", "coat_roughness"):
            return np.clip(self.source(bindings[name]),0.,1.) if name in bindings else np.full(self.cov.shape + (1,), 0. if name == "coat" else .1, np.float32)
        if name == "displacement_meters":
            return (self.source("height") - workflow.get("height_midlevel", .5)) * workflow.get("displacement_meters", 0.)
        channel = SOURCE_CHANNELS.get(name)
        if channel is not None:
            # Normal exports use the finished tangent normal (painted normal +
            # height + baked input), rather than its raw accumulator attachment.
            textures = (comp.color, comp.rmh, comp.emissive, comp.normal)
            buffer_keys = ("C", "R", "E", "N")
            data = self._tex(buffer_keys[channel.accumulator_index], textures[channel.accumulator_index], 4)
            values = data[..., channel.accumulator_components]
            if name == "normal_directx":
                values = values.copy()
                values[..., 1] = 1.0 - values[..., 1]
            pipeline = getattr(self.e, "color", None)
            if pipeline is not None and pipeline.managed and getattr(self, "encode_color", False) and channel.key in ("C", "E"):
                values = pipeline.encoded(values)
            return values
        rmho = lambda: self._tex("R", comp.rmh, 4)
        if name in ("glossiness", "smoothness"):
            return 1.0 - rmho()[..., 0:1]
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
            pipeline = getattr(self.e, "color", None)
            if pipeline is not None and pipeline.managed:
                result = self._tex("C", comp.color, 4)[..., :3] * (1 - self.source("metallic"))
                return pipeline.encoded(result) if getattr(self, "encode_color", False) else result
            c, m = _srgb2lin(self.source("basecolor")), self.source("metallic")
            return _lin2srgb(c * (1 - m))
        if name == "specular":
            pipeline = getattr(self.e, "color", None)
            if pipeline is not None and pipeline.managed:
                metal = self.source("metallic")
                result = .04 * (1 - metal) + self._tex("C", comp.color, 4)[..., :3] * metal
                return pipeline.encoded(result) if getattr(self, "encode_color", False) else result
            c, m = _srgb2lin(self.source("basecolor")), self.source("metallic")
            return _lin2srgb(0.04 * (1 - m) + c * m)
        if name == "specular_level":
            return np.full(self.cov.shape + (1,), 0.5, np.float32)
        raise ValueError(f"unknown export source '{name}'")

    def channel(self, spec: str) -> np.ndarray:
        """One output channel (H, W): 'source' (grey, or luminance of a colour source) or 'source.g'."""
        base, _, comp = spec.partition(".")
        if spec in SOURCES:
            base, comp = spec, ""
        a = self.source(base)
        if comp:
            return a[..., "rgb".index(comp)]
        if a.shape[2] == 1:
            return a[..., 0]
        return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722

    def background(self, spec):
        source = spec.partition(".")[0]
        v = self.e.user_channels[source]["default"] if is_user(source) and source in getattr(self.e,"user_channels",{}) else BACKGROUND.get(source, 0.0)
        pipeline = getattr(self.e, "color", None)
        if pipeline is not None and pipeline.managed and source in ("basecolor", "emissive") and not getattr(self, "encode_color", False):
            v = tuple(pipeline.working(v[:3]))
        return v


def _compose(data: _SetData, m: dict, file_format=None) -> np.ndarray:
    previous = getattr(data, "encode_color", False)
    data.encode_color = file_format is not None and file_format not in ("exr", "hdr", "pfm")
    try:
        return _compose_raw(data, m)
    finally:
        data.encode_color = previous


def _compose_raw(data: _SetData, m: dict) -> np.ndarray:
    chans, names = [], []
    if "rgb" in m or "rgba" in m:
        src = m.get("rgb") or m.get("rgba")
        a = data.source(src)
        a = np.repeat(a, 3, 2) if a.shape[2] == 1 else a
        chans += [a[..., i] for i in range(3)]
        names += [f"{src}.{c}" for c in "rgb"]
        if "a" in m:
            chans.append(data.channel(m["a"])); names.append(m["a"])
        elif "rgba" in m:
            chans.append(data.channel("opacity")); names.append("opacity")
    elif "l" in m:
        chans.append(data.channel(m["l"])); names.append(m["l"])
        if "a" in m:
            chans.append(data.channel(m["a"])); names.append(m["a"])
    else:
        # Preserve the requested positions for sparse packing (e.g. r+a or
        # g+b). Unspecified color components are zero, rather than compacting
        # provided components into the wrong positions.
        layout = "rgba" if "a" in m else ("rgb" if "g" in m or "b" in m else "r")
        for c in layout:
            spec = m.get(c, "0")
            chans.append(data.channel(spec)); names.append(spec)
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


@dataclass(frozen=True)
class ExportEntry:
    set_index: int
    set_key: str
    set_name: str
    source_resolution: int
    resolution: int
    path: str
    format: str
    depth: str
    mapping: dict
    kind: str = "texture"
    tile: tuple[int, int] | None = None


@dataclass(frozen=True)
class ExportManifest:
    folder: str
    template: str
    padding: str
    dilation: int
    entries: tuple[ExportEntry, ...]
    mesh_identity: int
    color_identity: str | None = None
    semantics_identity: str | None = None


def _semantics_identity(engine):
    from .userchannels import DEFAULT_WORKFLOW
    definitions = getattr(engine, "user_channels", {})
    workflow = getattr(engine, "shader_workflow", DEFAULT_WORKFLOW)
    return json.dumps([definitions, workflow],sort_keys=True) if definitions or workflow != DEFAULT_WORKFLOW else None


def _template(template):
    if isinstance(template, str):
        return copy.deepcopy(OUTPUT_TEMPLATES[template] if template in OUTPUT_TEMPLATES else load_template(template))
    if not isinstance(template, dict):
        raise ValueError("An export template must be a template name, JSON path or dictionary")
    return copy.deepcopy(template)


def _mapping_check(mapping):
    if not isinstance(mapping, dict) or not isinstance(mapping.get("name"), str) or not mapping["name"]:
        raise ValueError("Every output map needs a nonempty name")
    specs = {k: mapping[k] for k in ("rgb", "rgba", "r", "g", "b", "a", "l") if k in mapping}
    if not specs:
        raise ValueError(f"Output {mapping['name']} has no channel sources")
    if sum(k in specs for k in ("rgb", "rgba", "l")) > 1 or \
            (any(k in specs for k in ("rgb", "rgba", "l")) and any(k in specs for k in ("r", "g", "b"))):
        raise ValueError(f"Output {mapping['name']} mixes incompatible channel layouts")
    for key, spec in specs.items():
        if not isinstance(spec, str):
            raise ValueError(f"Invalid source in {mapping['name']}")
        base, dot, component = spec.partition(".")
        # Numeric constants contain a decimal point and are themselves sources.
        if spec in SOURCES:
            base, component, dot = spec, "", ""
        if (base not in SOURCES and not is_user(base)) or (dot and component not in ("r", "g", "b")):
            raise ValueError(f"Unknown export source {spec!r}")
        if dot and (key in ("rgb", "rgba") or (base not in COLOR_SOURCES and component != "r")):
            raise ValueError(f"Source {spec!r} is not valid for {key}")


def _filename(name):
    if not name or name in (".", "..") or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith((".", " ")):
        raise ValueError(f"Invalid output filename {name!r}; use a filename without directories")
    if "$" in name:
        raise ValueError(f"Unknown filename token in {name!r}")
    stem = name.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL", "CLOCK$"} or re.fullmatch(r"(?:COM|LPT)[1-9]", stem):
        raise ValueError(f"Reserved output filename {name!r}")


def build_export_manifest(engine, folder: str, template="Unreal Engine (Packed)", file_format=None,
                          depth=None, size=None, padding="infinite", dilation=PAD,
                          texture_sets=None, project=None, shader_json=False, overrides=None) -> ExportManifest:
    """Resolve and validate all outputs without GL calls, writes or project mutation.

    Names are portable leaf filenames. Collisions are rejected case-insensitively
    even on case-sensitive hosts, so a project can be delivered to Windows safely.
    Built-in legacy templates append the set name when exporting several sets.
    """
    if not getattr(engine, "mesh", None) or not engine.sets:
        raise ValueError("No project to export")
    if not isinstance(folder, (str, os.PathLike)) or not os.fspath(folder).strip():
        raise ValueError("Choose an export folder")
    folder = os.path.abspath(os.fspath(folder))
    if "\x00" in folder or (os.path.exists(folder) and not os.path.isdir(folder)):
        raise ValueError("Export folder is invalid or is a file")
    if os.name == "nt" and re.search(r'[<>:"|?*\x00-\x1f]', os.path.splitdrive(folder)[1]):
        raise ValueError("Export folder contains invalid characters")
    parent = folder
    while not os.path.exists(parent):
        ancestor = os.path.dirname(parent)
        if ancestor == parent:
            break
        parent = ancestor
    if os.path.exists(parent) and not os.path.isdir(parent):
        raise ValueError("An export folder parent is a file")
    if padding not in PADDING:
        raise ValueError(f"padding must be one of {PADDING}")
    if isinstance(dilation, bool) or not isinstance(dilation, int) or dilation < 0:
        raise ValueError("Dilation must be a nonnegative integer")
    if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size <= 0):
        raise ValueError("Export size must be a positive integer")
    original = template
    template = _template(template)
    if not isinstance(template.get("maps"), list) or not template["maps"]:
        raise ValueError("An export template needs a nonempty maps list")
    selected = list(range(len(engine.sets))) if texture_sets is None else list(texture_sets)
    if not selected:
        raise ValueError("Select at least one texture set")
    indices = []
    for s in selected:
        if isinstance(s, str):
            matches = [i for i, ts in enumerate(engine.sets) if ts.name == s]
            if len(matches) != 1:
                raise ValueError(f"Texture set name {s!r} is missing or ambiguous; use its index")
            s = matches[0]
        if isinstance(s, bool) or not isinstance(s, (int, np.integer)) or not 0 <= int(s) < len(engine.sets):
            raise ValueError(f"Invalid texture set index {s!r}")
        if int(s) in indices:
            raise ValueError("A texture set was selected more than once")
        indices.append(int(s))
    entries, paths = [], set()
    legacy_multi = isinstance(original, str) and original in _LEGACY and len(indices) > 1

    def add(entry):
        _filename(os.path.basename(entry.path))
        canonical = os.path.normpath(os.path.abspath(entry.path)).casefold()
        if canonical in paths:
            raise ValueError(f"Duplicate export path: {entry.path}. Include $textureSet and use distinct set names.")
        if os.path.isdir(entry.path):
            raise ValueError(f"Output path is an existing directory: {entry.path}")
        paths.add(canonical)
        entries.append(entry)

    for si in indices:
        ts = engine.sets[si]
        key = str(getattr(ts, "key", si))
        for m in template["maps"]:
            _mapping_check(m)
            for slot in ("rgb", "rgba", "r", "g", "b", "a", "l"):
                source = m.get(slot, "").partition(".")[0]
                if is_user(source) and source not in getattr(engine, "user_channels", {}):
                    raise ValueError("Undeclared user export source: " + source)
            ov = (overrides or {}).get(m["name"], {})
            if not ov.get("enabled", m.get("enabled", True)):
                continue
            fmt = str(file_format or ov.get("format") or m.get("format") or template.get("format", "png")).lower()
            dep = str(depth or ov.get("depth") or m.get("depth") or template.get("depth", "8"))
            if fmt not in FORMATS:
                raise ValueError(f"Unknown format {fmt}")
            if dep not in {d for ds in FORMATS.values() for d in ds}:
                raise ValueError(f"Unknown bit depth {dep}")
            if dep not in FORMATS[fmt]:
                dep = FORMATS[fmt][-1] if dep in ("16", "32f", "16f") else FORMATS[fmt][0]
            name = _expand(m["name"], engine, ts, project)
            if legacy_multi:
                name += "_" + _expand("$textureSet", engine, ts)
            tiled = getattr(ts, "tiles", None)
            addresses = ts.tile_addresses if tiled is not None else (None,)
            for address in addresses:
                udim = str(address.udim if address is not None else 1001)
                tile_name = name.replace("$udim", udim)
                if tiled is not None and "$udim" not in name:
                    tile_name += "_" + udim
                _filename(tile_name)
                add(ExportEntry(si, key, ts.name, int(ts.res), size or int(ts.res),
                                os.path.join(folder, tile_name + EXT[fmt]), fmt, dep, copy.deepcopy(m),
                                tile=tuple(address.to_list()) if address is not None else None))
        if shader_json:
            name = _expand("$mesh_$textureSet", engine, ts, project) + "_material.json"
            _filename(name)
            add(ExportEntry(si, key, ts.name, int(ts.res), size or int(ts.res),
                            os.path.join(folder, name), "json", "", {}, "material"))
    if not entries or not any(e.kind == "texture" for e in entries):
        raise ValueError("Enable at least one output map")
    pipeline = getattr(engine, "color", None)
    identity = pipeline.cache_id if pipeline is not None and pipeline.managed else None
    # Group maps by tile so only one detached tile evaluation is resident at a time.
    if any(entry.tile is not None for entry in entries):
        entries.sort(key=lambda entry: (indices.index(entry.set_index), entry.kind == "material",
                                        1001 + entry.tile[0] + 10 * entry.tile[1] if entry.tile else 0))
    return ExportManifest(folder, str(template.get("name", "Custom")), padding, dilation, tuple(entries), id(engine.mesh), identity, _semantics_identity(engine))


class _RollbackFailure(RuntimeError):
    pass


@contextmanager
def _export_stage(folder):
    stage = tempfile.mkdtemp(prefix=".strata-export-", dir=folder)
    preserve = False
    try:
        yield stage
    except _RollbackFailure as ex:
        preserve = True
        raise RuntimeError(f"{ex}. Recovery files retained in {stage}") from ex
    finally:
        if not preserve:
            # Only remove the exact temporary child that this operation created.
            if os.path.dirname(os.path.abspath(stage)) != os.path.abspath(folder) or not os.path.basename(stage).startswith(".strata-export-"):
                raise RuntimeError("Unexpected export staging path")
            shutil.rmtree(stage)


def _publish(staged):
    """Publish a fully staged batch, restoring previous outputs if promotion fails."""
    moved = []
    try:
        for source, destination, backup in staged:
            if os.path.isdir(destination):
                raise OSError(f"Output path became a directory: {destination}")
            previous = os.path.lexists(destination)
            if previous:
                os.replace(destination, backup)
            state = [destination, backup, previous, False]
            moved.append(state)
            os.replace(source, destination)
            state[3] = True
    except Exception:
        errors = []
        for destination, backup, previous, published in reversed(moved):
            try:
                if published:
                    os.remove(destination)
                if previous:
                    os.replace(backup, destination)
            except OSError as ex:
                errors.append(str(ex))
        if errors:
            raise _RollbackFailure("Export publication and rollback failed: " + "; ".join(errors))
        raise


def write_export_manifest(engine, manifest: ExportManifest) -> list[str]:
    """Evaluate and stage every output before replacing any destination file."""
    # Refuse stale previews after a project/set change, before creating a folder.
    if id(engine.mesh) != manifest.mesh_identity:
        raise ValueError("The project changed; refresh the export preview")
    pipeline = getattr(engine, "color", None)
    identity = pipeline.cache_id if pipeline is not None and pipeline.managed else None
    if identity != manifest.color_identity:
        raise ValueError("Color interpretation changed; refresh the export preview")
    if _semantics_identity(engine) != manifest.semantics_identity:
        raise ValueError("Shader/channel interpretation changed; refresh the export preview")
    for e in manifest.entries:
        if e.set_index >= len(engine.sets):
            raise ValueError("The project changed; refresh the export preview")
        ts = engine.sets[e.set_index]
        if ts.name != e.set_name or str(getattr(ts, "key", e.set_index)) != e.set_key or ts.res != e.source_resolution:
            raise ValueError("The texture sets changed; refresh the export preview")
        if e.kind == "texture":
            tiled = getattr(ts, "tiles", None)
            addresses = {tuple(address.to_list()) for address in ts.tile_addresses} if tiled is not None else {None}
            if e.tile not in addresses:
                raise ValueError("The material tiles changed; refresh the export preview")
    engine.dirty = True
    if hasattr(engine, "end_stroke"):
        engine.end_stroke()
    engine.update()
    os.makedirs(manifest.folder, exist_ok=True)
    with _export_stage(manifest.folder) as stage, ExitStack() as evaluation:
        pending, data, active_set = [], None, None
        engine.evaluation_report = []
        for i, e in enumerate(manifest.entries):
            staged = os.path.join(stage, f"out-{i}" + (".json" if e.kind == "material" else EXT[e.format]))
            if e.kind == "material":
                maps = [os.path.basename(m.path) for m in manifest.entries
                        if m.set_index == e.set_index and m.kind == "texture"]
                with open(staged, "w", encoding="utf-8") as f:
                    json.dump({"texture_set": e.set_name, "template": manifest.template,
                               "normal_strength": engine.normal_strength, "resolution": e.resolution,
                               "maps": maps}, f, indent=1)
            else:
                evaluation_key = (e.set_index, e.resolution, e.tile)
                if active_set != evaluation_key:
                    evaluation.close()
                    ts = engine.sets[e.set_index]
                    if e.tile is not None:
                        ts = evaluation.enter_context(engine.evaluate_tile(e.tile, e.set_index, e.resolution))
                    elif e.resolution != ts.res and hasattr(engine, "journal"):
                        from .evaluation import evaluate_set
                        ts, report = evaluation.enter_context(evaluate_set(engine, ts, e.resolution))
                        engine.evaluation_report.extend(report)
                    data = _SetData(engine, ts, manifest.padding, manifest.dilation)
                    active_set = evaluation_key
                img = _compose(data, e.mapping, e.format)
                if manifest.padding == "dilation_transparent":
                    alpha = data.cov_dil.astype(np.float32)
                    img = np.dstack([img, alpha]) if img.shape[2] in (1, 3) else img
                if e.resolution != img.shape[1]:
                    img = _resize(img, e.resolution)
                write_image(staged, img, e.depth)
            pending.append((staged, e.path, os.path.join(stage, f"backup-{i}")))
        _publish(pending)
    return [e.path for e in manifest.entries]


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
    manifest = build_export_manifest(engine, folder, template, file_format, depth, size, padding,
                                     dilation, texture_sets, project, shader_json, overrides)
    return write_export_manifest(engine, manifest)


def export(engine, folder: str, preset: int = 0, name: str | None = None) -> list[str]:
    """Original Strata entry point: preset indexes EXPORT_PRESETS."""
    return export_textures(engine, folder, _LEGACY[int(preset)], padding="infinite", project=name)


def export_mesh(engine, path: str, coordinates="normalized"):
    """Write the project mesh as OBJ (positions, UVs, normals; one group per texture set)."""
    m = engine.mesh
    if coordinates not in ("normalized", "source", "meters"):
        raise ValueError("Mesh coordinates must be normalized, source or meters")
    positions = m.positions
    if coordinates != "normalized":
        center, scale = m.extra.get("xform", ([0, 0, 0], 1.))
        if not np.isfinite(scale) or scale <= 0 or np.asarray(center).shape != (3,) or not np.isfinite(center).all():
            raise ValueError("Invalid source coordinate transform")
        positions = positions / float(scale) + np.asarray(center)
        if coordinates == "meters":
            from .uvprep import meters_per_project_unit
            positions = positions * meters_per_project_unit(m) * float(scale)
    with open(path, "w") as f:
        f.write(f"# Strata export: {m.name}\n")
        f.write(f"# coordinates: {coordinates}; source unit: {m.extra.get('physical', {}).get('unit', 'unspecified')}\n")
        for p in positions:
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
