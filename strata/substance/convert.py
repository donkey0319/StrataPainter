"""Convert Substance 3D Painter layer stacks (decoded HBO trees) into Strata layers.

Strata's layer model is close to Painter's, so most of a stack carries over one to one:

  Painter                                   Strata
  ----------------------------------------  ----------------------------------------------------
  folder (DataLayerGroup)                   folder (kind "group"), same mask and blending
  per-channel blending (mode + opacity)     chan_blend / chan_opacity, Painter's 32 blend modes
                                            map 1:1 onto layers.BLEND_MODES
  channels Base Color, Roughness (or        Color, Roughness, Metallic, Height, Normal, Emissive,
  Glossiness), Metallic, Height, Normal,    Opacity
  Emissive, Opacity
  fill layer, uniform sources               fill layer values
  fill layer, bitmap sources                fill layer image maps (embedded images are written to
                                            the cache folder) + projection (UV / tri-planar / ...)
  baked mesh maps used as sources           the project's own baked image when embedded, otherwise
                                            Strata's bake ("bake:curvature" etc.)
  several fills in one layer                a folder holding one sub-layer per fill, so each fill
                                            keeps its own blending
  paint layer (vector strokes)              paint layer; strokes are replayed with Strata's brush
  content filters: HSL, levels, blur,       content effects of the same kind
  contrast/luminosity
  mask stack                                mask effect stack in the same order: uniform fills,
                                            generators, bitmaps, mesh maps, levels, blur,
                                            invert, histogram scan (threshold), anchor references
  painted mask                              the layer's painted mask (Painter keeps it at the
                                            bottom of the mask stack, so does Strata)
  mg_mask_editor / mg_mask_builder          decomposed into their terms (AO, curvature, world-space
                                            direction, position gradient, thickness, grunge) as
                                            mesh-map / generator effects plus global levels
  anchor points + references                anchor effects (content) and anchor mask effects

What cannot be reproduced is anything that needs Adobe's Substance engine: procedural materials
(.sbsar) are recognised by name and parameters and become uniform values + noise or Strata's own
generators. Every approximation is recorded in ImportResult.notes.

Enum values: blend modes come from Painter's shader API (lib-defines.glsl: BlendingMode_*),
channel bits from Painter's channel order and verified on starter assets.
"""
from __future__ import annotations

import collections
import colorsys
import copy
import hashlib
import math
import os
import re
from dataclasses import dataclass, field

import numpy as np

from ..layers import Effect, Layer, MaskGen, Projection, BLEND, GEN, N_CH, CH_KEYS, group as _group, _uid as _uid_next


def make_group_layer(name):
    g = _group(name)
    g.enabled = [True] * N_CH
    return g
from .hbo import HObj, text, val

# ----------------------------------------------------------------------------- Painter enums
# channelTypes bits (Painter channel order: baseColor, height, specular, opacity, emissive,
# displacement, glossiness, roughness, ..., metallic, ..., normal, ambientOcclusion, diffuse)
CH_BASE, CH_HEIGHT, CH_SPECULAR, CH_OPACITY, CH_EMISSIVE = 1, 2, 4, 8, 16
CH_DISPLACEMENT, CH_GLOSS, CH_ROUGH, CH_METAL = 32, 64, 128, 8192
CH_NORMAL, CH_AO, CH_DIFFUSE = 1 << 22, 1 << 23, 1 << 24
ALL_CHANNELS = 0xFFFFFFFF

# Strata channel index for each Painter channel we keep (Glossiness lands on Roughness, inverted)
CH_TO_STRATA = ((CH_BASE, 0), (CH_ROUGH, 1), (CH_METAL, 2), (CH_HEIGHT, 3), (CH_NORMAL, 4),
                (CH_EMISSIVE, 5), (CH_OPACITY, 6))
KEPT = CH_BASE | CH_ROUGH | CH_GLOSS | CH_METAL | CH_HEIGHT | CH_NORMAL | CH_EMISSIVE | CH_OPACITY
UNSUPPORTED_CH = CH_SPECULAR | CH_DISPLACEMENT | CH_AO | CH_DIFFUSE

# Painter BlendingMode_* (shader-doc lib-defines) -> Strata layers.BLEND_MODES index
BM_DISABLE, BM_REPLACE, BM_NORMAL, BM_PASSTHRU = 0, 1, 2, 25
P_BLEND_NAMES = ["Disable", "Replace", "Normal", "Darken (Min)", "Multiply", "Color Burn", "Linear Burn",
                 "Lighten (Max)", "Screen", "Color Dodge", "Linear Dodge (Add)", "Overlay", "Soft Light",
                 "Hard Light", "Vivid Light", "Linear Light", "Pin Light", "Difference", "Exclusion",
                 "Tint", "Saturation", "Color", "Value", "Divide", "Inverse Divide", "Passthrough",
                 "Normal Map Combine", "Normal Map Detail", "Normal Map Inverse Detail", "Subtract",
                 "Inverse Subtract", "Signed Addition"]
TO_STRATA_BLEND = {i: BLEND[n] for i, n in enumerate(P_BLEND_NAMES)}
S_NORMAL, S_DISABLE = BLEND["Normal"], BLEND["Disable"]

# Painter fill projection -> Strata PROJECTIONS index (UV, Tri-planar, Planar, Spherical, Cylindrical)
PROJ_TO_STRATA = {0: 0, 1: 2, 2: 1, 3: 3, 4: 4}

# Painter height is signed around 0; Strata stores 0.5 = flat.
HEIGHT_SCALE = 0.5

# Painter mesh-map names -> (Strata bake name, layers.MESH_MAPS index for mesh_map effects)
BAKED = (("world_space_normal", "world_normal", 7), ("world space normal", "world_normal", 7),
         ("normalworldspace", "world_normal", 7), ("ambient_occlusion", "ao", 0),
         ("ambient occlusion", "ao", 0), ("ambientocclusion", "ao", 0), ("curvature", "curvature", 1),
         ("thickness", "thickness", 2), ("position", "position", 4), ("_id", "id", 9))


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def linear_to_srgb(c: float) -> float:
    """Painter stores uniform colours linear; Strata's layer colours are sRGB."""
    c = _clamp(float(c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _bits(v) -> int:
    v = val(v, 0)
    return int(v) & 0xFFFFFFFF if isinstance(v, int) else 0


def _num(v, default=0.0):
    if isinstance(v, (list, tuple)):
        return float(v[0]) if v else default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def name_of(url) -> str:
    u = re.sub(r"\?.*$", "", text(url))
    return u.rstrip("/").split("/")[-1] or u


def proc_name(proc) -> str:
    """'/mg_dirt/mg_dirt?version=..' -> 'mg_dirt' (the graph name)."""
    url = text(proc.get("urlToSbsRes")) if isinstance(proc, HObj) else ""
    url = re.sub(r"\?.*$", "", url)
    parts = [p for p in url.split("/") if p]
    return parts[-1] if parts else ""


def tweaks(proc) -> dict:
    out = {}
    for t in (proc.get("tweaks") or []) if isinstance(proc, HObj) else []:
        if isinstance(t, HObj):
            out[text(t.get("identifier"))] = val(t.get("value"))
    return out


def _tw(tw: dict, *names, default=None):
    """First tweak whose name matches one of names (case-insensitive)."""
    low = {k.lower(): v for k, v in tw.items()}
    for n in names:
        v = low.get(n.lower())
        if v is not None:
            return v
    return default


def baked_map(url: str):
    """Painter URL of a baked mesh map -> (Strata bake name, MESH_MAPS index), or None."""
    u = text(url).lower()
    name = re.sub(r"\?.*$", "", u.replace("resourcealias:", ""))
    for key, bake, idx in BAKED:
        if key.replace("_", "") in name.replace("_", "").replace(" ", "") or key in name:
            return bake, idx
    return None


# ----------------------------------------------------------------------------- results
@dataclass
class PaintJob:
    """One recorded Painter paint/eraser action, replayed by strata.substance.replay."""
    strokes: list                     # HObj DataStroke list
    brush: dict                       # size, size_space, spacing, flow, hardness, pressure flags...
    color: list = None                # sRGB base colour
    rough: float = None
    metal: float = None
    height: float = None              # Strata height (0.5 = flat)
    normal: list = None
    emissive: list = None
    opac: float = None
    mask_value: float = 1.0           # when painting a mask
    erase: bool = False
    label: str = ""

    def channels(self):
        return [self.color is not None, self.rough is not None, self.metal is not None,
                self.height is not None, self.normal is not None, self.emissive is not None,
                self.opac is not None]


@dataclass
class ImportedLayer:
    """A converted layer plus what the engine still has to do on the GPU."""
    layer: Layer                                        # children are in .children, not layer.children
    children: list = field(default_factory=list)        # ImportedLayer, bottom first (folders)
    mask_fill: float | None = None                      # painted-mask start value; None = no painted mask
    jobs: list = field(default_factory=list)            # PaintJob for a paint layer's content
    mask_jobs: list = field(default_factory=list)       # PaintJob for the painted mask
    path: str = ""

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class MaskBuild:
    """A Painter mask stack in Strata terms: a painted (or uniform) base plus mask effects."""
    base: float = 1.0                 # uniform start value of the painted mask
    painted: bool = False
    jobs: list = field(default_factory=list)
    effects: list = field(default_factory=list)

    @property
    def trivial(self):
        return not self.effects and not self.painted and self.base >= 0.999


@dataclass
class ImportResult:
    name: str
    layers: list                      # ImportedLayer, bottom first
    notes: list
    kind: str = ""
    version: str = ""

    def summary(self) -> str:
        n = sum(1 for il in self.layers for _ in il.walk())
        s = f"{self.name}: {n} layer{'s' if n != 1 else ''}"
        if self.notes:
            s += f", {len(self.notes)} approximation{'s' if len(self.notes) != 1 else ''}"
        return s


class Notes:
    """Approximation report: one line per kind of change, with a few examples."""

    def __init__(self):
        self.c = collections.Counter()
        self.ex = collections.defaultdict(list)

    def add(self, msg, example=None):
        self.c[msg] += 1
        if example and example not in self.ex[msg]:
            self.ex[msg].append(example)

    def lines(self):
        out = []
        for m, n in self.c.most_common():
            ex = self.ex.get(m)
            line = m + (f" (x{n})" if n > 1 else "")
            if ex:
                line += ": " + ", ".join(ex[:4]) + (", ..." if len(ex) > 4 else "")
            out.append(line)
        return out


# ----------------------------------------------------------------------------- image cache
def cache_dir() -> str:
    d = os.environ.get("STRATA_SUBSTANCE_CACHE") or os.path.join(os.path.expanduser("~"), ".strata",
                                                                 "substance_cache")
    os.makedirs(d, exist_ok=True)
    return d


def cached_image(spf, url) -> str | None:
    """Write an embedded .image resource to the cache folder (once) and return its path."""
    if spf is None:
        return None
    key = spf.resource_key(url)
    if not key:
        return None
    h = hashlib.sha1(f"{os.path.abspath(spf.path)}|{key}".encode()).hexdigest()[:20]
    path = os.path.join(cache_dir(), h + ".png")
    if os.path.exists(path):
        return path
    img = spf.image(key, max_size=4096)
    if img is None:
        return None
    from ..imageio import write_image
    if img.shape[2] == 2:
        img = np.dstack([img[..., :1]] * 3 + [img[..., 1:2]])
    tmp = path + ".tmp.png"
    write_image(tmp, np.clip(img, 0.0, 1.0), "16")
    os.replace(tmp, path)
    return path


# ----------------------------------------------------------------------------- blending
@dataclass
class Blending:
    modes: list = field(default_factory=lambda: [-1] * N_CH)      # Strata blend per channel, -1 = Normal
    raw_ops: list = field(default_factory=lambda: [None] * N_CH)  # Painter opacity per channel (None = 1)
    disabled: list = field(default_factory=lambda: [False] * N_CH)
    passthru: bool = False

    def apply(self, lay: Layer, relevant=None):
        """Layer opacity = the strongest channel the layer uses; channel opacities are relative to it."""
        rel = relevant if relevant is not None and any(relevant) else [True] * N_CH
        ops = [1.0 if o is None else o for o in self.raw_ops]
        used = [o for o, r in zip(ops, rel) if r]
        top = max(used) if used else 1.0
        top = top if top > 1e-4 else 1.0
        lay.opacity = top
        lay.chan_opacity = [_clamp(o / top) if r else 1.0 for o, r in zip(ops, rel)]
        lay.chan_blend = list(self.modes)
        lay.blend = self.modes[0] if self.modes[0] >= 0 else S_NORMAL


def read_blending(entries, notes: Notes | None = None) -> Blending:
    """perChannelBlending -> per-channel Strata blend modes and opacities."""
    b = Blending()
    for e in entries or []:
        if not isinstance(e, HObj):
            continue
        ch = _bits(e.get("channelTypes"))
        mode = int(val(e.get("blendingMode"), BM_NORMAL))
        o = _clamp(float(val(e.get("opacity"), 1.0)))
        sm = TO_STRATA_BLEND.get(mode, S_NORMAL)
        if mode == BM_PASSTHRU:
            b.passthru = True
        for bit, i in CH_TO_STRATA:
            if ch & bit or (i == 1 and ch & CH_GLOSS and not ch & CH_ROUGH and b.raw_ops[1] is None):
                b.modes[i] = sm
                b.raw_ops[i] = o
                if mode == BM_DISABLE or o <= 0.001:
                    b.disabled[i] = True
    return b


# ----------------------------------------------------------------------------- scalar blending
def _blend_scalar(a, b, mode, t):
    """Combine two uniform channel values (Painter mode) - used when merging uniform fills."""
    if mode in (BM_DISABLE,) or t <= 0:
        return a
    r = {3: min(a, b), 4: a * b, 7: max(a, b), 8: 1 - (1 - a) * (1 - b), 10: a + b, 29: a - b,
         30: b - a, 31: a + b - 0.5, 17: abs(a - b), 23: a / max(b, 1e-4)}.get(mode, b)
    return a + (r - a) * t


# ----------------------------------------------------------------------------- procedural masks
_EDGE_NAMES = ("edge", "wear", "damage", "bevel", "scratch_edge", "chipp", "uv_border")
_DIRT_NAMES = ("dirt", "grease", "cavity", "driping", "dripping", "leak", "rust_drip")
_UP_NAMES = ("dust", "snow", "sand", "top")
_GRAD_NAMES = ("position", "gradient", "height_blend")
_PATTERN_NAMES = ("stitch", "tile_generator", "pattern", "stripe", "lines", "weave", "fiber", "fibre",
                  "thread", "hexa", "checker", "circles", "waveform", "shape", "font", "scratches_generator")
_SPOT_NAMES = ("spot", "cell", "crystal", "voronoi", "bnw", "gaussian")
_GRUNGE_NAMES = ("grunge", "dirt", "rust", "scratch", "concrete", "leak", "crack")


def _lv_bc(balance, contrast, invert=False):
    """Painter balance / contrast as Strata levels (in_lo, in_hi, out_lo, out_hi)."""
    c = 1.0 - _clamp(float(balance))
    w = max(0.5 * (1.0 - _clamp(float(contrast), 0.0, 0.995)), 0.004)
    lo, hi = c - w, c + w
    if invert:
        lo, hi = 1.0 - hi, 1.0 - lo
        return {"in_lo": lo, "in_hi": hi, "gamma": 1.0, "out_lo": 1.0, "out_hi": 0.0}
    return {"in_lo": lo, "in_hi": hi, "gamma": 1.0, "out_lo": 0.0, "out_hi": 1.0}


def _mesh_map(idx, blend=S_NORMAL, opacity=1.0, name="", **lv):
    p = {"map": int(idx), "in_lo": 0.0, "in_hi": 1.0, "gamma": 1.0, "out_lo": 0.0, "out_hi": 1.0}
    p.update(lv)
    return Effect(kind="mesh_map", blend=blend, opacity=_clamp(opacity), params=p, name=name)


def _gen_effect(gen: MaskGen, blend=S_NORMAL, opacity=1.0, name=""):
    return Effect(kind="generator", blend=blend, opacity=_clamp(opacity), params={"gen": gen}, name=name)


def _texture_gen(name: str, tw: dict, uv_scale: float, scale_key=("scale", "Scale", "tiling", "Tiling")):
    """Grunge / noise texture -> a continuous Strata noise generator."""
    n = name.lower()
    kind = GEN["Noise"]
    if any(k in n for k in _SPOT_NAMES):
        kind = GEN["Spots (cellular)"]
    elif any(k in n for k in _GRUNGE_NAMES):
        kind = GEN["Grunge (ridged noise)"]
    balance = _num(_tw(tw, "balance", "Grunge_Balance", "histogram_position", "Balance", "position"), 0.5)
    contrast = _num(_tw(tw, "contrast", "Grunge_Contrast", "historgram_contrast", "histogram_contrast",
                        "Contrast"), 0.0)
    inv = _num(_tw(tw, "invert", "Invert"), 0) > 0.5
    sc = _num(_tw(tw, *scale_key), 1.0) * max(uv_scale, 0.05)
    if "scratch" in n or "crack" in n:
        # thin features: the ridges of Strata's ridged noise, thresholded high, read as fine lines
        return MaskGen(GEN["Grunge (ridged noise)"], level=_clamp(0.97 - 0.12 * balance, 0.75, 0.97),
                       softness=_clamp(0.03 + 0.04 * (1.0 - contrast), 0.02, 0.08), noise_amount=0.0,
                       noise_scale=_clamp(sc * 1.5, 0.5, 16.0), invert=inv)
    return MaskGen(kind, level=_clamp(1.0 - balance, 0.02, 0.98),
                   softness=_clamp(0.5 * (1.0 - contrast) + 0.01, 0.01, 0.5), noise_amount=0.0,
                   noise_scale=_clamp(sc, 0.25, 12.0), invert=inv)


def classify_mask_procedural(proc: HObj, uv_scale=1.0) -> tuple[MaskGen, str]:
    """A single mask generator / texture procedural -> one Strata MaskGen. Returns (gen, how)."""
    name = proc_name(proc)
    n = name.lower()
    tw = tweaks(proc)
    inv = _num(_tw(tw, "invert", "global_invert", "Invert"), 0) > 0.5

    if n == "mg_curvature" or n == "curvature":
        bal = _num(_tw(tw, "global_balance", "balance"), 0.5)
        con = _num(_tw(tw, "global_contrast", "contrast"), 0.0)
        g = MaskGen(GEN["Edge Wear"], level=_clamp(0.5 + 0.5 * (1 - bal), 0.5, 0.98),
                    softness=_clamp(0.25 * (1 - con) + 0.005, 0.005, 0.25), noise_amount=0.0)
        g.invert = inv ^ (_num(_tw(tw, "curvature_invert"), 0) > 0.5)
        return g, "curvature"

    if n.startswith("mg_") and any(k in n for k in _EDGE_NAMES):
        wear = _num(_tw(tw, "Wear_Level", "wear_level", "Edge_Wear", "level", "Damage_Level"), 0.6)
        contrast = _num(_tw(tw, "Wear_Contrast", "contrast", "Damage_Contrast"), 0.5)
        amt = _num(_tw(tw, "Grunge_Amount", "grunge_amount"), 0.3)
        sc = _num(_tw(tw, "grunge_scale", "Grunge_Scale"), 2.0)
        return MaskGen(GEN["Edge Wear"], level=_clamp(0.92 - 0.35 * wear, 0.5, 0.97),
                       softness=_clamp(0.12 * (1 - contrast) + 0.02, 0.01, 0.3),
                       noise_amount=_clamp(amt, 0, 1), noise_scale=_clamp(sc / 2, 0.3, 6), invert=inv), "edge wear"

    if n.startswith("mg_") and any(k in n for k in _DIRT_NAMES):
        lvl = _num(_tw(tw, "dirt_level", "Grease_Level", "level", "Dirt_Level", "Rust_Level"), 0.6)
        contrast = _num(_tw(tw, "dirt_contrast", "contrast", "Grease_Contrast"), 0.4)
        amt = _num(_tw(tw, "grunge_amount", "Grunge_Amount"), 0.3)
        sc = _num(_tw(tw, "Grunge_Scale", "grunge_scale"), 3.0)
        return MaskGen(GEN["Dirt / Cavity"], level=_clamp(0.85 - 0.7 * lvl, 0.05, 0.9),
                       softness=_clamp(0.25 * (1 - contrast) + 0.03, 0.02, 0.4),
                       noise_amount=_clamp(amt, 0, 1), noise_scale=_clamp(sc / 2.5, 0.3, 6), invert=inv), "dirt"

    if n in ("mg_ambient_occlusion", "ambient_occlusion"):
        bal = _num(_tw(tw, "global_balance", "balance"), 0.5)
        con = _num(_tw(tw, "global_contrast", "contrast"), 0.0)
        return MaskGen(GEN["Ambient Occlusion"], level=_clamp(1 - bal, 0.02, 0.98),
                       softness=_clamp(0.5 * (1 - con) + 0.01, 0.01, 0.5), noise_amount=0.0, invert=inv), "ao"

    if n.startswith("mg_") and any(k in n for k in _UP_NAMES):
        lvl = _num(_tw(tw, "Dust_Level", "dust_level", "level", "Snow_Level"), 0.5)
        contrast = _num(_tw(tw, "Dust_Contrast", "contrast"), 0.5)
        amt = _num(_tw(tw, "grunge_amount", "Grunge_Amount", "Dust_Grunge"), 0.4)
        return MaskGen(GEN["Upward Facing (dust)"], level=_clamp(0.95 - 0.4 * lvl, 0.4, 0.98),
                       softness=_clamp(0.15 * (1 - contrast) + 0.02, 0.01, 0.4),
                       noise_amount=_clamp(amt, 0, 1), noise_scale=2.0, invert=inv), "upward facing"

    if n == "light" or n.startswith("mg_light"):
        az = math.radians(_num(_tw(tw, "Light_Direction_Horizontal", "horizontal_angle", "angle"), 30.0))
        el = math.radians(_num(_tw(tw, "Light_Direction_Vertical", "vertical_angle", "elevation"), 45.0))
        bal = _num(_tw(tw, "balance", "Light_Balance"), 0.5)
        con = _num(_tw(tw, "contrast", "Light_Contrast"), 0.3)
        return MaskGen(GEN["Directional Light"], level=_clamp(1 - bal, 0.02, 0.98),
                       softness=_clamp(0.5 * (1 - con) + 0.01, 0.01, 0.5), noise_amount=0.0,
                       azimuth=az, elevation=el, invert=inv), "light"

    if n.startswith("mg_") and any(k in n for k in _GRAD_NAMES) or n.startswith("gradient_linear"):
        bal = _num(_tw(tw, "global_balance", "balance", "position"), 0.5)
        con = _num(_tw(tw, "global_contrast", "contrast"), 0.0)
        return MaskGen(GEN["Position Gradient"], level=_clamp(1 - bal, 0.02, 0.98),
                       softness=_clamp(0.5 * (1 - con) + 0.01, 0.01, 0.5), noise_amount=0.0, axis=1,
                       invert=inv), "position gradient"

    if n.startswith("mg_") or n.startswith("mask_"):
        return _texture_gen(name, tw, uv_scale), "unknown generator"

    if any(k in n for k in _PATTERN_NAMES):
        return MaskGen(GEN["Noise"], level=0.74, softness=0.04, noise_amount=0.0,
                       noise_scale=_clamp(6.0 * max(uv_scale, 0.5), 3.0, 12.0)), "pattern"

    return _texture_gen(name, tw, uv_scale), "texture"


# blend codes inside mg_mask_editor / mg_mask_builder (Substance Designer Blend node order:
# Copy, Add, Subtract, Multiply, Add Sub, Max, Min, Switch, Divide, Overlay, Screen, Soft Light)
_SD_BLEND = {0: S_NORMAL, 1: BLEND["Linear Dodge (Add)"], 2: BLEND["Subtract"], 3: BLEND["Multiply"],
             4: BLEND["Signed Addition"], 5: BLEND["Lighten (Max)"], 6: BLEND["Darken (Min)"], 7: S_NORMAL,
             8: BLEND["Divide"], 9: BLEND["Overlay"], 10: BLEND["Screen"], 11: BLEND["Soft Light"]}
_ADD = BLEND["Linear Dodge (Add)"]


def _sd_blend(v, default=1):
    return _SD_BLEND.get(int(_num(v, default)), _ADD)


# mg_mask_editor parameter names: (Painter 2018-2020 names, newer names)
_ME_KEYS = {
    "tex": (("tex", "tex_blend_mode", "scale_tex", "invert_tex", "tex_contrast", "tex_lum"),
            ("texture_opacity", "texture_blendmode", "texture_scale", "texutre_invert", "texture_contrast",
             "texture_brightness")),
    "tex2": (("tex2", "tex2_blend_mode", "tex2_scale", "invert_tex_sec", "tex2_contrast", "tex2_lum"),
             ("texture2_opacity", "texture2_blendmode", "texture2_scale", "texture2_invert", "texture2_contrast",
              "texture2_brightness")),
    "ao": (("ao", "ao_blend_mode", "ao_balance", "invert_ao", "ao_contrast", "ao_blur"),
           ("ao_opacity", "ao_blendmode", "ao_balance", "ao_invert", "ao_contrast", "ao_blur")),
    "curv": (("curv", "curv_blend_mode", "Curvature_Mode", "invert_invert", "curv_contrast", "curv_lum"),
             ("curvature_opacity", "curvature_blendmode", "curvature_mode", "curvature_invert", "curvature_contrast",
              "curvature_brightness")),
    "ws": (("ws", "ws_blend", "world_balance", "ws_invert", "ws_contrast", "Object_Space_Direction_{}"),
           ("ws_opacity", "ws_blendmode", "ws_balance", "ws_invert", "ws_contrast", "ws_direction_{}")),
    "pos": (("Position_Gradient", "grad_blend", "Gradient_Direction_Balance", "grad_invert", "grad_contrast",
             "Gradient_Direction_{}"),
            ("position_opacity", "position_blendmode", "position_balance", "position_invert", "position_contrast",
             "position_direction_{}")),
    "thick": (("thick", None, None, "thick_invert", "Thickness_thick_Contrast", None),
              ("thickness_opacity", None, None, "thickness_invert", "thickness_contrast", None)),
}
_AXES_OLD = (("Right_to_Left", "_Invert", "_Blending_Mode", ""), ("Top_To_Bottom", "_Invert", "_Blending_Mode", ""),
             ("Front_to_Back", "_Invert", "_Blending_Mode", ""))
_AXES_NEW = (("rightleft", "_invert", "_blendmode", "_opacity"), ("topbottom", "_invert", "_blendmode", "_opacity"),
             ("frontback", "_invert", "_blendmode", "_opacity"))


def mask_editor_effects(tw: dict, label="Mask editor") -> list:
    """mg_mask_editor -> mask effects that rebuild it term by term on a black start, in the editor's
    order: two grunge textures, AO, curvature (convex or concave), world-space direction, position
    gradient and thickness, each weighted and blended; then global balance / contrast / invert / blur."""
    new = "ao_opacity" in tw or "texture_opacity" in tw
    K = {k: v[1 if new else 0] for k, v in _ME_KEYS.items()}
    fx = [Effect(kind="fill", params={"value": 0.0}, name=f"{label}: start")]

    def g(name, default=0.0):
        return default if name is None else _num(_tw(tw, name), default)

    def add(e):
        if e.opacity > 0.005:
            fx.append(e)

    for key, nm, gen_kind, seed in (("tex", "texture", GEN["Grunge (ridged noise)"], 0.0),
                                    ("tex2", "texture 2", GEN["Noise"], 0.37)):
        w_, mode_, scale_, inv_, con_, bri_ = K[key]
        w = g(w_)
        if w > 0.005:
            con, bri = g(con_), g(bri_)
            gen = MaskGen(gen_kind, level=_clamp(0.5 - 0.5 * bri, 0.02, 0.98),
                          softness=_clamp(0.5 * (1.0 - _clamp(con, -1.0, 0.98)), 0.02, 0.9), noise_amount=0.0,
                          noise_scale=_clamp(g(scale_, 1.0), 0.25, 12.0),
                          invert=g(inv_) > 0.5 or (key == "tex" and g("texture_invert") > 0.5), seed=seed)
            add(_gen_effect(gen, _sd_blend(_tw(tw, mode_), 7 if key == "tex" else 1), w, f"{label}: {nm}"))
    w_, mode_, bal_, inv_, con_, _ = K["ao"]
    if g(w_) > 0.005:
        add(_mesh_map(0, _sd_blend(_tw(tw, mode_)), g(w_), f"{label}: ambient occlusion",
                      **_lv_bc(g(bal_, 0.5), g(con_), g(inv_) > 0.5)))
    w_, mode_, cmode_, inv_, con_, _ = K["curv"]
    if g(w_) > 0.005:
        span = 0.5 * max(1.0 - _clamp(g(con_), 0.0, 0.96), 0.04)
        concave = int(g(cmode_, 1)) == 2
        inv = (g(inv_) > 0.5) ^ concave
        lo, hi = (0.5 - span, 0.5) if concave else (0.5, 0.5 + span)
        add(_mesh_map(1, _sd_blend(_tw(tw, mode_)), g(w_), f"{label}: {'concave' if concave else 'convex'} curvature",
                      in_lo=lo, in_hi=hi, out_lo=1.0 if inv else 0.0, out_hi=0.0 if inv else 1.0))
    for key, base_idx, nm in (("ws", 6, "world normal"), ("pos", 3, "position")):
        w_, mode_, bal_, inv_, con_, axis_ = K[key]
        w = g(w_)
        if w <= 0.005:
            continue
        for k, (ax, inv_s, mode_s, op_s) in enumerate(_AXES_NEW if new else _AXES_OLD):
            base = axis_.format(ax)
            aw = g(base + op_s if new else base)
            if aw > 0.005:
                inv = (g(base + inv_s) > 0.5) ^ (g(inv_) > 0.5)
                add(_mesh_map(base_idx + k, _sd_blend(_tw(tw, base + mode_s, mode_)), w * aw,
                              f"{label}: {nm} {'XYZ'[k]}", **_lv_bc(g(bal_, 0.5), g(con_), inv)))
    w_, _, _, inv_, con_, _ = K["thick"]
    if g(w_) > 0.005:
        add(_mesh_map(2, _ADD, g(w_), f"{label}: thickness", **_lv_bc(0.5, g(con_), g(inv_) > 0.5)))
    if len(fx) == 1:
        return fx
    bal, con = g("global_balance", 0.5), g("global_contrast")
    if abs(bal - 0.5) > 1e-3 or con > 1e-3:
        fx.append(Effect(kind="levels", params=_lv_bc(bal, con), name=f"{label}: balance / contrast"))
    if g("global_invert") > 0.5:
        fx.append(Effect(kind="invert", name=f"{label}: invert"))
    blur = g("global_blur")
    if blur > 0.005:
        fx.append(Effect(kind="blur", params={"radius": _clamp(blur * 24.0, 0.5, 48.0)}, name=f"{label}: blur"))
    return fx


def mask_builder_effects(tw: dict, label="Mask builder") -> list:
    """mg_mask_builder: weighted AO, convex/concave curvature, top-down gradient, world-space normal
    and grunge, then Level (higher = more coverage) / Contrast / Invert."""
    fx = [Effect(kind="fill", params={"value": 0.0}, name=f"{label}: start")]
    w = _num(_tw(tw, "AO"), 0.0)
    if w > 0.005:
        r = max(_num(_tw(tw, "AO_Range"), 0.5), 0.05)
        inv = not (_num(_tw(tw, "AO_Invert"), 0) > 0.5)          # the builder's AO term marks occlusion
        fx.append(_mesh_map(0, _ADD, w, f"{label}: ambient occlusion",
                            in_lo=1.0 - r if not inv else 1.0 - r, in_hi=1.0,
                            out_lo=1.0 if inv else 0.0, out_hi=0.0 if inv else 1.0))
    w = _num(_tw(tw, "Curvature"), 0.0)
    if w > 0.005:
        cx = _num(_tw(tw, "Curvature_Convex_Range"), 0.5)
        cc = _num(_tw(tw, "Curvature_Concave_Range"), 0.0)
        if cx > 0.005:
            fx.append(_mesh_map(1, _ADD, w, f"{label}: convex curvature", in_lo=0.5, in_hi=0.5 + 0.5 * max(cx, 0.05)))
        if cc > 0.005:
            fx.append(_mesh_map(1, _ADD, w, f"{label}: concave curvature", in_lo=0.5 - 0.5 * max(cc, 0.05),
                                in_hi=0.5, out_lo=1.0, out_hi=0.0))
    w = _num(_tw(tw, "Top_Down_Gradient"), 0.0)
    if w > 0.005:
        inv = _num(_tw(tw, "Gradient_Invert"), 0) > 0.5
        fx.append(_mesh_map(4, _ADD, w, f"{label}: top-down gradient",
                            out_lo=1.0 if inv else 0.0, out_hi=0.0 if inv else 1.0))
    w = _num(_tw(tw, "World_Space_Normal"), 0.0)
    if w > 0.005:
        fx.append(_mesh_map(7, _ADD, w, f"{label}: world-space normal", in_lo=0.5, in_hi=1.0))
    w = _num(_tw(tw, "Scratches"), 0.0)
    if w > 0.005:
        g = MaskGen(GEN["Grunge (ridged noise)"], level=0.9, softness=0.04, noise_amount=0.0,
                    noise_scale=_clamp(_num(_tw(tw, "Scratches_Scale"), 0.5) * 8.0, 1.0, 16.0), seed=0.53)
        fx.append(_gen_effect(g, _ADD, w, f"{label}: scratches"))
    w = _num(_tw(tw, "Grunge"), 0.0)
    if w > 0.005:
        g = MaskGen(GEN["Grunge (ridged noise)"], level=0.5, softness=0.5, noise_amount=0.0,
                    noise_scale=_clamp(_num(_tw(tw, "Grunge_Scale"), 2.0) / 2.0, 0.25, 8.0))
        fx.append(_gen_effect(g, BLEND["Multiply"], w, f"{label}: grunge"))
    if len(fx) == 1:
        return fx
    fx.append(Effect(kind="levels", params=_lv_bc(_num(_tw(tw, "Level"), 0.5), _num(_tw(tw, "Contrast"), 0.4)),
                     name=f"{label}: level / contrast"))
    if _num(_tw(tw, "Invert"), 0) > 0.5:
        fx.append(Effect(kind="invert", name=f"{label}: invert"))
    return fx


def _strongest(fx: list):
    """Collapse a decomposed editor to its main term (used when it can't be rebuilt in place)."""
    terms = [e for e in fx if e.kind in ("mesh_map", "generator")]
    return max(terms, key=lambda e: e.opacity) if terms else None


# ----------------------------------------------------------------------------- content procedurals
_METAL_WORDS = ("metal", "steel", "iron", "gold", "copper", "bronze", "silver", "chrome", "aluminium",
                "aluminum", "brass", "cobalt")


def guess_procedural_values(proc: HObj, channels: int) -> dict:
    """Best-guess uniform values for a procedural material/texture driving `channels`."""
    tw = tweaks(proc)
    name = proc_name(proc).lower()
    out = {"textured": True}
    colors = []
    for k, v in tw.items():
        kl = k.lower()
        if isinstance(v, list) and len(v) in (3, 4) and all(isinstance(x, float) for x in v) \
                and ("color" in kl or "colour" in kl or kl in ("tint",)):
            colors.append((0 if ("base" in kl or kl in ("color", "colour")) else 1, v[:3]))
    if channels & CH_BASE and colors:
        colors.sort(key=lambda c: c[0])
        top = [c for p, c in colors if p == colors[0][0]]
        out["color"] = [_clamp(sum(c[i] for c in top) / len(top)) for i in range(3)]      # sRGB parameters
    if channels & (CH_ROUGH | CH_GLOSS):
        r = _tw(tw, "roughness", "Roughness", "rough", "base_roughness", "Roughness_Value", "roughness_value")
        if isinstance(r, (int, float)):
            out["rough"] = _clamp(float(r))
        else:
            gl = _tw(tw, "glossiness", "Glossiness", "gloss")
            if isinstance(gl, (int, float)):
                out["rough"] = 1 - _clamp(float(gl))
    if channels & CH_METAL:
        m = _tw(tw, "metallic", "Metallic", "metalness", "metal")
        if isinstance(m, (int, float)):
            out["metal"] = _clamp(float(m))
        elif any(w in name for w in _METAL_WORDS):
            out["metal"] = 1.0
    if channels & CH_HEIGHT:
        h = _tw(tw, "height_intensity", "Height_Intensity", "height", "Height")
        out["height_bump"] = _clamp(abs(_num(h, 0.3)) * 0.5, 0.05, 0.5)
    return out


def _gradient_colors(tw) -> list:
    """Colours of a Painter gradient-map filter (sRGB), in order, limited to color_quantity."""
    found = []
    for k, v in tw.items():
        m = re.fullmatch(r"colou?r_?(\d+)", k.lower())
        if m and isinstance(v, list) and len(v) >= 3:
            found.append((int(m.group(1)), [_clamp(float(x)) for x in v[:3]]))
    found.sort()
    q = int(_num(_tw(tw, "color_quantity"), len(found)) or len(found))
    return [c for _, c in found[:max(q, 1)]]


def _hsl_params(tw):
    """Painter HSL filters use 0.5 = unchanged; Strata's hsl effect uses offsets around 0."""
    return {"hue": _num(_tw(tw, "hue"), 0.5) - 0.5,
            "saturation": (_num(_tw(tw, "saturation"), 0.5) - 0.5) * 2.0,
            "lightness": (_num(_tw(tw, "luminosity", "lightness"), 0.5) - 0.5) * 2.0}


def _projection(fill: HObj) -> Projection:
    p = Projection()
    p.mode = PROJ_TO_STRATA.get(int(val(fill.get("projection"), 0)), 0)
    xf = fill.get("uvTransformation")
    if isinstance(xf, HObj):
        sc, off, rot = val(xf.get("scaleFactors")), val(xf.get("translation")), _num(val(xf.get("rotation")), 0.0)
    else:
        sc, off, rot = val(fill.get("uvScale")), val(fill.get("uvPosition")), _num(val(fill.get("uvRotation")), 0.0)
    if isinstance(sc, list) and len(sc) >= 2:
        p.scale = [float(sc[0]), float(sc[1])]
    elif isinstance(sc, (int, float)):
        p.scale = [float(sc), float(sc)]
    if isinstance(off, list) and len(off) >= 2:
        p.offset = [float(off[0]), float(off[1])]
    p.rotation = float(rot)
    p.sharpness = 1.0 + 8.0 * _num(val(fill.get("sideHardness")), 0.5)
    return p


def _uv_scale(fill: HObj) -> float:
    s = _projection(fill).scale
    return float(math.sqrt(abs(s[0] * s[1]))) if s else 1.0


# ----------------------------------------------------------------------------- content model
class _Part:
    """One Strata layer's worth of content built from one or more Painter content actions."""

    def __init__(self, kind="fill"):
        self.kind = kind
        self.set = 0                                  # Painter channel bits provided
        self.values = {}                              # strata channel index -> value
        self.maps = {}                                # CH_KEY -> image path
        self.proj = None
        self.variation, self.bump, self.var_scale = 0.0, 0.0, 1.0
        self.blending = None                          # Blending of the action (inside a folder)
        self.jobs = []
        self.effects = []
        self.base_unknown = False
        self.adjust = False                           # adjustment layer (filter of the stack below)
        self.pass_ch = 0                              # channels a filter reads from the stack below
        self.label = ""

    def enabled(self):
        en = [False] * N_CH
        for bit, i in CH_TO_STRATA:
            if self.set & bit:
                en[i] = True
        if self.set & CH_GLOSS:
            en[1] = True
        return en


_ADJUSTMENTS = ("hsl", "hsl_perceptive", "fx_hsl", "blur", "fx_blur", "blur_grayscale", "contrast_luminosity")


def _adjustment_part(ch) -> _Part:
    """A filter with no content of its own: Painter applies it to the stack below. In Strata that is a
    fill layer whose channels are Passthrough (content = the stack below), carrying the effect."""
    pt = _Part("fill")
    pt.adjust = True
    pt.set = ch & KEPT & ~CH_NORMAL
    return pt


def _uniform_into(part: _Part, ch, col, mode=BM_NORMAL, op=1.0):
    col = col if isinstance(col, list) else [float(col or 0)] * 3
    col = (list(col) + [col[-1]] * 3)[:3]
    v0 = part.values

    def put(i, v):
        if i in v0 and isinstance(v, float) and isinstance(v0[i], float):
            v0[i] = _blend_scalar(v0[i], v, mode, op)
        elif i in v0 and isinstance(v, list) and isinstance(v0[i], list) and mode != BM_NORMAL:
            v0[i] = [_blend_scalar(a, b, mode, op) for a, b in zip(v0[i], v)]
        elif i not in v0 or op >= 0.99 or mode in (BM_NORMAL, BM_REPLACE):
            if i in v0 and op < 0.99:
                if isinstance(v, float):
                    v = v0[i] + (v - v0[i]) * op
                else:
                    v = [a + (b - a) * op for a, b in zip(v0[i], v)]
            v0[i] = v

    if ch & CH_BASE:
        put(0, [linear_to_srgb(x) for x in col])
    if ch & CH_ROUGH:
        put(1, float(col[0]))
    elif ch & CH_GLOSS and not part.set & CH_ROUGH:
        put(1, 1.0 - float(col[0]))
    if ch & CH_METAL:
        put(2, float(col[0]))
    if ch & CH_HEIGHT:
        put(3, 0.5 + float(col[0]) * HEIGHT_SCALE)
    if ch & CH_NORMAL:
        put(4, [float(x) for x in col])
    if ch & CH_EMISSIVE:
        put(5, [linear_to_srgb(x) for x in col])
    if ch & CH_OPACITY:
        put(6, float(col[0]))
    part.set |= ch & KEPT


def _procedural_into(part: _Part, proc, ch, uv_scale):
    g = guess_procedural_values(proc, ch) if proc is not None else {"textured": True}
    if ch & CH_BASE:
        if "color" in g:
            part.values[0] = g["color"]
        elif 0 not in part.values:
            part.values[0] = [0.5, 0.5, 0.5]
            part.base_unknown = True
        part.variation = max(part.variation, 0.3)
    if ch & (CH_ROUGH | CH_GLOSS):
        if "rough" in g:
            part.values[1] = g["rough"]
        elif 1 not in part.values:
            part.values[1] = 0.5
        part.variation = max(part.variation, 0.25)
    if ch & CH_METAL:
        if "metal" in g:
            part.values[2] = g["metal"]
        elif 2 not in part.values:
            part.values[2] = 0.0
    if ch & CH_HEIGHT:
        part.values.setdefault(3, 0.5)
        part.bump = max(part.bump, g.get("height_bump", 0.15))
    part.var_scale = _clamp(math.sqrt(max(uv_scale, 0.05)) * 1.5, 0.3, 8.0)
    part.set |= ch & (CH_BASE | CH_ROUGH | CH_GLOSS | CH_METAL | CH_HEIGHT)


# ----------------------------------------------------------------------------- converter
class Converter:
    def __init__(self, spf=None, notes: Notes | None = None, mesh_names=None):
        self.spf = spf
        self.notes = notes or Notes()
        self.mesh_names = list(mesh_names or [])
        self.anchors = {}             # content anchor uid -> Strata anchor name
        self.mask_anchors = {}        # mask anchor uid -> (effects so far, base, painted, layer seed)

    # --------------------------------------------------------------- stacks
    def stack(self, stack, path="") -> list:
        """DataStackLayers -> list[ImportedLayer], bottom first."""
        items = stack.get("items") if isinstance(stack, HObj) else None
        items = [i for i in items or [] if isinstance(i, HObj)]
        self._collect_anchors(items)
        out = []
        for item in items:
            if item.type == "DataLayerGroup":
                r = self.group(item, path)
            elif item.type in ("DataLayerColor", "DataLayerInstance"):
                r = self.layer(item, path)
            else:
                self.notes.add("Skipped unsupported layer types", item.type)
                r = None
            if r is not None:
                out.append(r)
        return out

    def _collect_anchors(self, items):
        """Content anchors anywhere below this stack, so references can be resolved in any order."""
        def acts(st):
            for a in (st.get("items") if isinstance(st, HObj) else None) or []:
                if not isinstance(a, HObj):
                    continue
                if a.type == "DataActionAnchor":
                    uid = val(a.get("uid"))
                    if uid is not None and uid not in self.anchors:
                        self.anchors[uid] = text(a.get("label")) or f"Anchor {len(self.anchors) + 1}"
                elif a.type == "DataActionGroup":
                    acts(a.get("subStack"))

        def layers(lst):
            for L in lst:
                if not isinstance(L, HObj):
                    continue
                acts(L.get("actions"))
                sub = L.get("subStack")
                if isinstance(sub, HObj):
                    layers(sub.get("items") or [])
        layers(items)

    def _geometry(self, L: HObj, lay: Layer):
        """Painter geometry mask (enabled meshes) -> Strata part mask."""
        if not self.mesh_names or not bool(val(L.get("enabledGeometryMask"), True)):
            return
        names = [text(x.get("value")) for x in (L.get("enabledMeshList") or []) if isinstance(x, HObj)]
        if not names:
            if not bool(val(L.get("enabledMeshDefault"), True)):
                lay.part_mask = []
            return
        listed = {i for i, n in enumerate(self.mesh_names) if n in set(names)}
        if bool(val(L.get("enabledMeshDefault"), True)):
            keep = [i for i in range(len(self.mesh_names)) if i not in listed]     # all but the listed
        else:
            keep = sorted(listed)                                                 # only the listed
        if len(keep) < len(self.mesh_names):
            lay.part_mask = keep

    def group(self, g: HObj, path) -> ImportedLayer | None:
        name = text(g.get("label")) or "Folder"
        p = f"{path}/{name}"
        children = self.stack(g.get("subStack"), p)
        lay = make_group_layer(name)
        lay.visible = bool(val(g.get("enabled"), True))
        bl = read_blending(g.get("perChannelBlending"), self.notes)
        bl.apply(lay)
        had = any(isinstance(i, HObj) for i in ((g.get("subStack").get("items") or [])
                                                 if isinstance(g.get("subStack"), HObj) else []))
        if had and not children:
            self.notes.add("Folders whose layers Strata can't show were left out", name)
            return None
        il = ImportedLayer(layer=lay, children=children, path=p)
        self._geometry(g, lay)
        self._apply_mask(il, g, p)
        return il

    # --------------------------------------------------------------- one layer
    def layer(self, L: HObj, path) -> ImportedLayer | None:
        name = text(L.get("label")) or "Layer"
        p = f"{path}/{name}"
        visible = bool(val(L.get("enabled"), True))
        bl = read_blending(L.get("perChannelBlending"), self.notes)
        parts = self._content(L.get("actions"), name, p)
        parts = [pt for pt in parts if (pt.set or pt.jobs or pt.maps) and (not pt.adjust or pt.effects)]
        if not parts:
            return None
        if len(parts) == 1:
            il = self._part_layer(parts[0], name, bl, visible, p)
            self._geometry(L, il.layer)
            self._apply_mask(il, L, p)
            return il
        # several fills / paint passes in one Painter layer: a folder keeps each pass's blending
        folder = make_group_layer(name)
        folder.visible = visible
        used = [any(pt.enabled()[i] or (pt.kind == "paint" and i < 4) for pt in parts) for i in range(N_CH)]
        bl.apply(folder, used)
        kids = []
        for i, pt in enumerate(parts):
            sub_bl = pt.blending or Blending()
            label = pt.label or ("Paint" if pt.kind == "paint" else f"Fill {i + 1}")
            kids.append(self._part_layer(pt, f"{name} - {label}", sub_bl, True, f"{p}/{label}"))
        il = ImportedLayer(layer=folder, children=kids, path=p)
        self._geometry(L, folder)
        self._apply_mask(il, L, p)
        self.notes.add("Layers with several fills or paint passes became a folder of sub-layers", name)
        return il

    def _part_layer(self, pt: _Part, name, bl: Blending, visible, path) -> ImportedLayer:
        en = pt.enabled()
        if pt.kind == "paint":
            lay = Layer(name=name, kind="paint", visible=visible)
            en = [False] * N_CH
            for j in pt.jobs:
                en = [a or b for a, b in zip(en, j.channels())]
            if not any(en):
                en = [True, True, True, True, False, False, False]
        else:
            lay = Layer(name=name, kind="fill", visible=visible, color=[0.5, 0.5, 0.5], rough=0.5, metal=0.0,
                        height=0.5)
            v = pt.values
            if 0 in v:
                lay.color = [_clamp(c) for c in v[0]]
            if 1 in v:
                lay.rough = _clamp(v[1])
            if 2 in v:
                lay.metal = _clamp(v[2])
            if 3 in v:
                lay.height = _clamp(v[3])
            if 4 in v:
                lay.normal = [_clamp(c) for c in v[4]]
            if 5 in v:
                lay.emissive = [_clamp(c) for c in v[5]]
            if 6 in v:
                lay.opac = _clamp(v[6])
            lay.variation, lay.bump, lay.var_scale = pt.variation, pt.bump, pt.var_scale
            lay.maps = dict(pt.maps)
            if pt.proj is not None:
                lay.proj = pt.proj
            if pt.base_unknown and en[0] and 0 not in pt.maps:
                en[0] = False
                self.notes.add("Base Color from untinted procedural textures was left out", name)
        if pt.adjust or pt.pass_ch:
            for bit, i in CH_TO_STRATA:
                if (pt.adjust and en[i]) or (pt.pass_ch & bit and not en[i]):
                    en[i] = True
                    bl.modes[i] = BLEND["Passthrough"]
            if pt.effects:
                self.notes.add("Filter layers became Passthrough layers with the same effect", name)
        bl.apply(lay, en)
        lay.enabled = [e and not d for e, d in zip(en, bl.disabled)]
        lay.effects = list(pt.effects)
        return ImportedLayer(layer=lay, jobs=list(pt.jobs), path=path)

    # --------------------------------------------------------------- content
    def _content(self, stack, name, path) -> list:
        parts: list[_Part] = []

        def cur(kind="fill"):
            if not parts or parts[-1].kind != kind:
                parts.append(_Part(kind))
            return parts[-1]

        def visit(st):
            for a in (st.get("items") if isinstance(st, HObj) else None) or []:
                if not isinstance(a, HObj) or not bool(val(a.get("enabled"), True)):
                    continue
                t = a.type
                if t == "DataActionFill":
                    self._fill(a, parts, name)
                elif t in ("DataActionPaint", "DataActionEraser"):
                    job = self._paint_job(a, erase=(t == "DataActionEraser"))
                    if job is not None:
                        cur("paint").jobs.append(job)
                elif t == "DataActionGroup":
                    visit(a.get("subStack"))
                elif t == "DataActionFilterProcedural":
                    self._content_filter(a, parts, name)
                elif t == "DataActionFilterLevels":
                    self._content_levels(a, parts, name)
                elif t == "DataActionAnchor":
                    if parts:
                        nm = self.anchors.get(val(a.get("uid"))) or text(a.get("label")) or "Anchor"
                        parts[-1].effects.append(Effect(kind="anchor", params={"name": nm}, name=f"Anchor: {nm}"))
                elif t == "DataActionSmudge":
                    self.notes.add("Smudge strokes were skipped", name)
                elif t == "DataActionDecal":
                    self.notes.add("Projected decals were skipped", name)
                else:
                    self.notes.add("Skipped unsupported content effects", t)
        visit(stack)
        return parts

    def _fill(self, a: HObj, parts: list, name):
        fill_ch = _bits(a.get("channelTypes")) or ALL_CHANNELS
        bl_entries = a.get("perChannelBlending") or []
        modes = {}
        for e in bl_entries:
            if isinstance(e, HObj):
                modes[_bits(e.get("channelTypes"))] = (int(val(e.get("blendingMode"), BM_NORMAL)),
                                                       float(val(e.get("opacity"), 1.0)))

        def mode_for(ch):
            for bits, mo in modes.items():
                if bits & ch:
                    return mo
            return BM_NORMAL, 1.0

        srcs = [s for s in a.get("sources") or [] if isinstance(s, HObj)]
        has_bitmap = any(s.type == "DataSourceBitmap" for s in srcs)
        uniform_normal = all(s.type == "DataSourceUniform" for s in srcs) and \
            all(m[0] in (BM_NORMAL, BM_REPLACE) and m[1] >= 0.99 for m in modes.values())
        proc_only = all(s.type == "DataSourceProcedural" for s in srcs)
        # start a new sub-layer unless this fill can be merged exactly (uniform values) or as noise
        new_part = not parts or parts[-1].kind != "fill" or has_bitmap or \
            (not uniform_normal and not proc_only and bool(modes))
        if parts and parts[-1].kind == "fill" and proc_only and not has_bitmap:
            new_part = False
        if parts and parts[-1].kind == "fill" and parts[-1].maps and not has_bitmap:
            new_part = not proc_only
        if new_part:
            pt = _Part("fill")
            if parts and modes:
                pt.blending = read_blending(bl_entries)
            parts.append(pt)
        pt = parts[-1]
        pt.proj = pt.proj or _projection(a)
        uvs = _uv_scale(a)
        for s in srcs:
            ch = _bits(s.get("channelTypes"))
            if s.type == "DataSourceProcedural" and isinstance(s.get("procedural"), HObj):
                for o in s["procedural"].get("outputs") or []:
                    if isinstance(o, HObj):
                        ch |= _bits(o.get("channelTypes"))
            ch &= fill_ch
            if ch & UNSUPPORTED_CH and not ch & KEPT:
                continue
            if not ch & KEPT:
                continue
            mode, op = mode_for(ch)
            if s.type == "DataSourceUniform":
                if mode == BM_DISABLE:
                    continue
                _uniform_into(pt, ch, val(s.get("color")), mode if not new_part else BM_NORMAL,
                              op if not new_part else 1.0)
            elif s.type == "DataSourceProcedural":
                proc = s.get("procedural")
                had = pt.set
                _procedural_into(pt, proc, ch, uvs)
                if had and not new_part:
                    self.notes.add("Procedural textures over other fills became noise variation",
                                   proc_name(proc) or "substance")
                else:
                    self.notes.add("Procedural textures approximated as uniform values + noise",
                                   proc_name(proc) or "substance")
            elif s.type == "DataSourceBitmap":
                self._bitmap_into(pt, s, ch, name)
            elif s.type == "DataSourceReference":
                self.notes.add("Fills that reference anchor points were left out", name)
            else:
                self.notes.add("Skipped unsupported fill sources", s.type)

    def _bitmap_into(self, pt: _Part, s: HObj, ch, name):
        bmp = s.get("bitmap")
        url = text(bmp.get("urlToBitmapRes")) if isinstance(bmp, HObj) else ""
        path = None
        try:
            path = cached_image(self.spf, url)
        except Exception as e:
            self.notes.add("Embedded images that couldn't be decoded were left out", f"{name_of(url)} ({e})")
        if path is None:
            bk = baked_map(url)
            if bk is not None:
                path = "bake:" + bk[0]
                self.notes.add("Baked mesh maps used as layer content use Strata's own bake", name_of(url))
            else:
                self.notes.add("Bitmaps that aren't embedded in the file were left out", name_of(url))
                return
        for bit, i in CH_TO_STRATA:
            if ch & bit:
                pt.maps[CH_KEYS[i]] = path
        if ch & CH_GLOSS and not ch & CH_ROUGH:
            pt.maps["R"] = path
            pt.effects.append(Effect(kind="invert", params={"channel": 1}, name="Glossiness to roughness"))
        pt.set |= ch & KEPT
        # a map replaces the uniform value of its channel
        for bit, i in CH_TO_STRATA:
            if ch & bit and i in (1, 2, 3, 6):
                pt.values.pop(i, None)

    def _content_filter(self, a: HObj, parts: list, name):
        proc = a.get("procedural")
        n = proc_name(proc).lower()
        tw = tweaks(proc) if proc is not None else {}
        ch = _bits(a.get("channelTypes")) or ALL_CHANNELS
        empty = not parts or (parts[-1].kind == "fill" and not parts[-1].set and not parts[-1].maps)
        if empty:
            if n not in _ADJUSTMENTS:
                self.notes.add("Filter layers Strata has no equivalent for were skipped", f"{name} ({n})")
                return
            if parts:
                parts.pop()
            parts.append(_adjustment_part(ch))
        pt = parts[-1]
        if n in _ADJUSTMENTS:
            pt.pass_ch |= ch & KEPT & ~CH_NORMAL & ~pt.set
        if n in ("hsl", "hsl_perceptive", "fx_hsl"):
            pt.effects.append(Effect(kind="hsl", params=_hsl_params(tw), name="HSL"))
        elif n in ("blur", "fx_blur", "blur_grayscale"):
            r = _num(_tw(tw, "blur_intensity", "intensity", "Intensity"), 0.2)
            pt.effects.append(Effect(kind="blur", params={"radius": _clamp(r * 24.0, 0.5, 48.0), "channel": -1},
                                     name="Blur"))
        elif n == "contrast_luminosity":
            pt.effects.append(Effect(kind="brightness_contrast",
                                     params={"brightness": _num(_tw(tw, "Luminosity", "luminosity"), 0.0),
                                             "contrast": _num(_tw(tw, "Contrast", "contrast"), 0.0),
                                             "channel": 0 if ch & CH_BASE else 1}, name="Contrast / luminosity"))
        elif n in ("gradient", "fx_gradient", "gradient_map") and ch & CH_BASE:
            cols = _gradient_colors(tw)
            if cols:
                pt.values[0] = [sum(c[i] for c in cols) / len(cols) for i in range(3)]
                pt.variation = max(pt.variation, 0.25)
                pt.base_unknown = False
                pt.set |= CH_BASE
                self.notes.add("Gradient maps became their average colour + variation", name)
        elif n.startswith("finish_") or n.startswith("matfinish"):
            pt.variation = max(pt.variation, 0.15)
            self.notes.add("Material finish filters became roughness variation", n)
        elif n in ("sharpen", "fx_sharpen", "warp", "fx_warp"):
            pass                      # detail filters: harmless to leave out
        else:
            self.notes.add("Filters on layer content were ignored", proc_name(proc) or "filter")

    def _content_levels(self, a: HObj, parts: list, name):
        ch = _bits(a.get("channelTypes"))
        if not parts or (parts[-1].kind == "fill" and not parts[-1].set and not parts[-1].maps):
            if parts:
                parts.pop()
            parts.append(_adjustment_part(ch or ALL_CHANNELS))
        else:
            parts[-1].pass_ch |= (ch or 0) & KEPT & ~CH_NORMAL & ~parts[-1].set
        lv = _levels_params(a.get("levels"))
        targets = [i for bit, i in CH_TO_STRATA if ch & bit] or \
                  [i for i, e in enumerate(parts[-1].enabled()) if e] or [0]
        for i in targets[:3]:
            parts[-1].effects.append(Effect(kind="levels", params=dict(lv, channel=i), name="Levels"))

    def _paint_job(self, a: HObj, erase=False):
        strokes = [s for s in (a.get("strokes") or []) if isinstance(s, HObj)]
        if not strokes:
            return None
        br = a.get("brush")
        em = br.get("stampsEmitter") if isinstance(br, HObj) else None
        hard = 0.8
        for s in a.get("sourceTransparent") or []:
            if isinstance(s, HObj) and s.get("procedural") is not None:
                hard = _num(_tw(tweaks(s["procedural"]), "hardness"), hard)
        brush = {
            "size": _num(val(br.get("brushSize")) if br else None, 0.1),
            "size_space": int(val(br.get("brushSizeSpace"), 1)) if br else 1,
            "flow": _num(val(br.get("flow")) if br else None, 1.0),
            "spacing": _num(val(em.get("spacing")) if em else None, 0.15),
            "pressure_size": bool(val(em.get("pressureSizeEnabled"), False)) if em else False,
            "pressure_size_min": _num(val(em.get("pressureSizeMinimum")) if em else None, 0.0),
            "pressure_flow": bool(val(em.get("pressureFlowEnabled"), False)) if em else False,
            "pressure_flow_min": _num(val(em.get("pressureFlowMinimum")) if em else None, 0.0),
            "hardness": _clamp(hard),
        }
        job = PaintJob(strokes=strokes, brush=brush, erase=erase, label=text(a.get("label")))
        pt = _Part()
        mask_val = False
        for s in a.get("sourceColor") or []:
            if isinstance(s, HObj) and s.type == "DataSourceUniform":
                col = val(s.get("color"))
                col = col if isinstance(col, list) else [float(col or 0)] * 3
                ch = _bits(s.get("channelTypes"))
                if ch == 0:                                   # mask painting value
                    job.mask_value, mask_val = float(col[0]), True
                else:
                    _uniform_into(pt, ch, col)
            elif isinstance(s, HObj) and s.type == "DataSourceProcedural":
                _procedural_into(pt, s.get("procedural"), _bits(s.get("channelTypes")), 1.0)
        v = pt.values
        job.color, job.rough, job.metal, job.height = v.get(0), v.get(1), v.get(2), v.get(3)
        job.normal, job.emissive, job.opac = v.get(4), v.get(5), v.get(6)
        if not erase and not any(job.channels()) and not mask_val:
            return None
        return job

    # --------------------------------------------------------------- masks
    def _apply_mask(self, il: ImportedLayer, L: HObj, path):
        mb = self.mask(L, path, il.layer.seed)
        if mb is None or mb.trivial:
            return
        lay = il.layer
        if mb.painted or mb.base < 0.999:
            lay.has_mask = True
            il.mask_fill = float(mb.base)
            il.mask_jobs = list(mb.jobs)
        lay.mask_effects = list(mb.effects)

    def mask(self, L: HObj, path, seed=0.0) -> MaskBuild | None:
        acts = L.get("maskActions")
        if not isinstance(acts, HObj) or not bool(val(L.get("maskEnabled"), True)):
            return None
        mb = MaskBuild(base=1.0 if int(val(L.get("maskInitial"), 1)) == 1 else 0.0)
        self.mask_actions(acts, mb, path, seed)
        return mb

    def mask_actions(self, acts: HObj, mb: MaskBuild, path, seed=0.0):
        for a in acts.get("items") or []:
            if not isinstance(a, HObj) or not bool(val(a.get("enabled"), True)):
                continue
            t = a.type
            mode, op = self._mask_blend(a)
            if t == "DataActionGroup":
                if mode not in (BM_PASSTHRU, BM_NORMAL) or op < 0.99:
                    self.notes.add("Blended effect groups inside masks were flattened", path.split("/")[-1])
                self.mask_actions(a.get("subStack"), mb, path, seed)
            elif t == "DataActionFill":
                self._mask_fill(a, mb, mode, op, path, seed)
            elif t == "DataActionFilterLevels":
                mb.effects.append(Effect(kind="levels", params=_levels_params(a.get("levels")), name="Levels"))
            elif t in ("DataActionPaint", "DataActionEraser"):
                job = self._paint_job(a, erase=(t == "DataActionEraser"))
                if job is not None:
                    if mb.effects:
                        self.notes.add("Mask paint above other mask effects was placed under them",
                                       path.split("/")[-1])
                    mb.painted = True
                    mb.jobs.append(job)
            elif t == "DataActionFilterProcedural":
                self._mask_filter(a, mb, mode, op, path)
            elif t == "DataActionAnchor":
                uid = val(a.get("uid"))
                if uid is not None:
                    self.mask_anchors[uid] = (copy.deepcopy(mb.effects), mb.base, mb.painted, seed,
                                              text(a.get("label")) or "mask")
            elif t == "DataActionSmudge":
                self.notes.add("Smudge strokes were skipped", path.split("/")[-1])
            elif t == "DataActionDecal":
                self.notes.add("Projected decals were skipped", path.split("/")[-1])
            else:
                self.notes.add("Skipped unsupported mask effects", t)

    def _mask_blend(self, a: HObj):
        mode, op = BM_NORMAL, 1.0
        for b in a.get("perChannelBlending") or []:
            if isinstance(b, HObj):
                mode = int(val(b.get("blendingMode"), BM_NORMAL))
                op = _clamp(float(val(b.get("opacity"), 1.0)))
                break
        return mode, op

    def _mask_fill(self, a: HObj, mb: MaskBuild, mode, op, path, seed=0.0):
        if mode == BM_DISABLE or op <= 0.001:
            return
        blend = TO_STRATA_BLEND.get(mode, S_NORMAL)
        replaces = mode in (BM_NORMAL, BM_REPLACE, BM_PASSTHRU) and op >= 0.99
        uvs = _uv_scale(a)
        proj = _projection(a)
        label = path.split("/")[-1]
        for s in a.get("sources") or []:
            if not isinstance(s, HObj):
                continue
            if s.type == "DataSourceUniform":
                v = val(s.get("color"))
                v = float(v[0]) if isinstance(v, list) else float(v or 0)
                if not mb.effects and not mb.painted and replaces:
                    mb.base = v
                else:
                    mb.effects.append(Effect(kind="fill", blend=blend, opacity=op, params={"value": v},
                                             name="Uniform"))
            elif s.type == "DataSourceProcedural" and isinstance(s.get("procedural"), HObj):
                proc = s["procedural"]
                n = proc_name(proc).lower()
                if n in ("mg_mask_editor", "maskeditor", "mg_mask_builder", "mask_builder"):
                    editor = mask_editor_effects if "editor" in n else mask_builder_effects
                    fx = editor(tweaks(proc), "Mask editor" if "editor" in n else "Mask builder")
                    if len(fx) == 1:
                        continue                           # all terms off: contributes black
                    if replaces:
                        if not mb.effects and not mb.painted and mb.base <= 0.001:
                            fx = fx[1:]                    # already black: no need to reset
                        mb.effects += fx
                    else:
                        main = _strongest(fx)
                        if main is not None:
                            main.blend, main.opacity = blend, op * main.opacity
                            mb.effects.append(main)
                        self.notes.add("Blended mask editors were reduced to their main term", label)
                    continue
                g, how = classify_mask_procedural(proc, uvs)
                if how in ("texture", "pattern", "unknown generator"):
                    self.notes.add("Mask textures shown with Strata's noise generators", proc_name(proc))
                mb.effects.append(_gen_effect(g, blend, op, proc_name(proc) or "Generator"))
            elif s.type == "DataSourceBitmap":
                bmp = s.get("bitmap")
                url = text(bmp.get("urlToBitmapRes")) if isinstance(bmp, HObj) else ""
                path_img = None
                try:
                    path_img = cached_image(self.spf, url)
                except Exception:
                    path_img = None
                if path_img is not None:
                    mb.effects.append(Effect(kind="fill", blend=blend, opacity=op,
                                             params={"value": 1.0, "map": path_img, "proj": proj},
                                             name=name_of(url) or "Bitmap"))
                    continue
                bk = baked_map(url)
                if bk is not None:
                    mb.effects.append(_mesh_map(bk[1], blend, op, name_of(url)))
                else:
                    self.notes.add("Mask bitmaps that aren't embedded in the file were left out", name_of(url))
            elif s.type == "DataSourceReference":
                self._mask_reference(s, mb, blend, op, label, replaces, seed)
            else:
                self.notes.add("Skipped unsupported mask sources", s.type)

    def _mask_reference(self, s: HObj, mb: MaskBuild, blend, op, label, replaces=True, seed=0.0):
        ref = s.get("reference")
        src = val(ref.get("source")) if isinstance(ref, HObj) else None
        lv = _levels_params(s.get("levels"))
        has_lv = lv["in_lo"] > 0.001 or lv["in_hi"] < 0.999 or lv["out_lo"] > 0.001 or lv["out_hi"] < 0.999
        if src in self.mask_anchors:
            # an anchor inside another mask: Strata rebuilds that mask here, same effects and noise
            fx, base, painted, src_seed, nm = self.mask_anchors[src]
            fx = copy.deepcopy(fx)
            for e in fx:
                e.uid = _uid_next()
                if e.kind == "generator":
                    e.params["gen"].seed += src_seed - seed
            if painted:
                self.notes.add("Painted masks referenced through anchors were left out", nm)
            if replaces:
                mb.effects.append(Effect(kind="fill", params={"value": base}, name=f"{nm}: start"))
                mb.effects += fx
            else:
                main = _strongest(fx)
                if main is None:
                    main = Effect(kind="fill", params={"value": base})
                main.blend, main.opacity = blend, op * main.opacity
                mb.effects.append(main)
                self.notes.add("Blended references to mask anchors were reduced to their main term", label)
            if has_lv:
                mb.effects.append(Effect(kind="levels", params=lv, name=f"Anchor levels: {nm}"))
            return
        nm = self.anchors.get(src)
        if nm is None:
            self.notes.add("References to anchors Strata couldn't find were left out", label)
            return
        ch = 3
        for b in (ref.get("bindings") or []) if isinstance(ref, HObj) else []:
            if isinstance(b, HObj):
                bits = _bits(b.get("source"))
                ch = next((i for bit, i in CH_TO_STRATA if bits & bit), 3)
                break
        mb.effects.append(Effect(kind="anchor", blend=blend, opacity=op, params={"source": nm, "channel": ch},
                                 name=f"Anchor: {nm}"))
        if has_lv:
            mb.effects.append(Effect(kind="levels", params=lv, name=f"Anchor levels: {nm}"))

    def _mask_filter(self, a: HObj, mb: MaskBuild, mode, op, path):
        proc = a.get("procedural")
        n = proc_name(proc).lower()
        tw = tweaks(proc)
        if n in ("blur", "fx_blur", "blur_grayscale"):
            r = _num(_tw(tw, "blur_intensity", "Intensity", "intensity"), 0.2)
            mb.effects.append(Effect(kind="blur", opacity=op, params={"radius": _clamp(r * 24.0, 0.5, 48.0)},
                                     name="Blur"))
        elif n == "histogram_scan":
            pos = _num(_tw(tw, "Position", "position"), 0.5)
            con = _num(_tw(tw, "Contrast", "contrast"), 0.5)
            mb.effects.append(Effect(kind="threshold", opacity=op,
                                     params={"level": _clamp(1.0 - pos), "softness": _clamp(0.5 * (1 - con), 0.005, 0.5)},
                                     name="Histogram scan"))
        elif n in ("invert", "fx_invert"):
            mb.effects.append(Effect(kind="invert", opacity=op, name="Invert"))
        elif n in ("sharpen", "fx_sharpen", "warp", "fx_warp", "mirror"):
            self.notes.add("Mask warp / sharpen / mirror filters were left out", n)
        else:
            self.notes.add("Mask filters were left out", proc_name(proc) or "filter")


def _levels_params(lv) -> dict:
    p = {"in_lo": 0.0, "in_hi": 1.0, "gamma": 1.0, "out_lo": 0.0, "out_hi": 1.0}
    if isinstance(lv, HObj):
        p["in_lo"] = _num(val(lv.get("inputMinimum")), 0.0)
        p["in_hi"] = _num(val(lv.get("inputMaximum")), 1.0)
        p["gamma"] = _num(val(lv.get("gamma")), 1.0) or 1.0
        p["out_lo"] = _num(val(lv.get("outputMinimum")), 0.0)
        p["out_hi"] = _num(val(lv.get("outputMaximum")), 1.0)
    return p


# ----------------------------------------------------------------------------- entry points
def convert_preset(root: HObj, spf=None, name: str = "") -> ImportResult:
    """DataLayersPreset (smart material) -> ImportResult with one folder, like Painter."""
    conv = Converter(spf)
    group = root.get("layerGroup") if isinstance(root, HObj) else None
    layers = []
    if isinstance(group, HObj):
        g = conv.group(group, "")
        if g is not None:
            layers = [g]
        name = name or text(group.get("label"))
    return ImportResult(name=name or "Smart material", layers=layers, notes=conv.notes.lines())


def convert_mask_preset(root: HObj, spf=None, name: str = ""):
    """Smart mask (.spmsk): returns (MaskBuild or None, notes)."""
    conv = Converter(spf)
    if isinstance(root, HObj) and isinstance(root.get("actionsStack"), HObj):     # DataSmartMask
        mb = MaskBuild(base=0.0)            # Painter drops smart masks onto a black mask
        conv.mask_actions(root["actionsStack"], mb, name)
        return mb, conv.notes.lines()
    target = root
    for key in ("mask", "layerGroup", "smartMask"):
        if isinstance(root, HObj) and isinstance(root.get(key), HObj):
            target = root.get(key)
            break
    mb = None
    if isinstance(target, HObj):
        if target.get("maskActions") is not None:
            mb = conv.mask(target, name)
        elif target.get("items") is not None:
            mb = MaskBuild(base=0.0)
            conv.mask_actions(target, mb, name)
    return mb, conv.notes.lines()


def fresh_copy(layers: list) -> list:
    """Deep copies of ImportedLayers with new uids (every drop of a smart material is independent)."""
    from ..layers import _uid
    out = copy.deepcopy(layers)
    for il in out:
        for x in il.walk():
            x.layer.uid = _uid()
            for e in x.layer.effects + x.layer.mask_effects:
                e.uid = _uid()
    return out


_ = colorsys          # kept for API compatibility of older callers
