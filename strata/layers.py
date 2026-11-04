"""Layer stack data model: layers, groups, effect stacks, projections and the brush.

Everything here is plain data (serialisable with to_dict/from_dict). GPU resources hang off
`tex` / `mask_tex` and are owned by the engine.
"""
from __future__ import annotations

import copy
import itertools
import random
import uuid
from dataclasses import dataclass, field, asdict, fields
from typing import Optional

# ---------------------------------------------------------------------------------- channels
# Display names (index-aligned with Layer.enabled / Brush.enabled / chan_blend / chan_opacity)
from .channels import (CHANNELS, CH_KEYS, CH_COMPONENTS, N_CH, channel_default,
                       enabled_defaults)
DEFAULT_ENABLED = enabled_defaults("layer")

# ---------------------------------------------------------------------------------- blend modes
# The first five keep their old indices so existing projects load unchanged.
BLEND_MODES = [
    "Normal", "Multiply", "Screen", "Overlay", "Linear Dodge (Add)",           # 0-4
    "Replace", "Passthrough", "Disable", "Subtract", "Divide",                # 5-9
    "Inverse Divide", "Inverse Subtract", "Darken (Min)", "Lighten (Max)",    # 10-13
    "Difference", "Exclusion", "Signed Addition", "Linear Burn", "Color Burn",  # 14-18
    "Color Dodge", "Soft Light", "Hard Light", "Vivid Light", "Linear Light",  # 19-23
    "Pin Light", "Tint", "Saturation", "Color", "Value",                      # 24-28
    "Normal Map Combine", "Normal Map Detail", "Normal Map Inverse Detail",   # 29-31
]
BLEND = {n: i for i, n in enumerate(BLEND_MODES)}
B_NORMAL, B_ADD, B_REPLACE, B_PASSTHROUGH, B_DISABLE = 0, 4, 5, 6, 7
NORMAL_MAP_BLENDS = (29, 30, 31)
HEIGHT_BLEND = ["Normal", "Add"]                        # legacy per-layer height blend

# ---------------------------------------------------------------------------------- generators
# Legacy indices 0-6 unchanged; new generators are appended.
GENERATORS = ["None", "Edge Wear", "Dirt / Cavity", "Ambient Occlusion",
              "Upward Facing (dust)", "Height Gradient", "Noise",
              "Thickness", "Position Gradient", "Directional Light", "Cavities (curvature)",
              "World Normal Axis", "Grunge (ridged noise)", "Spots (cellular)"]
GEN = {n: i for i, n in enumerate(GENERATORS)}

PROJECTIONS = ["UV", "Tri-planar", "Planar", "Spherical", "Cylindrical"]
MESH_MAPS = ["Ambient Occlusion", "Curvature", "Thickness", "Position X", "Position Y",
             "Position Z", "World Normal X", "World Normal Y", "World Normal Z", "ID (luminance)",
             "Height (baked from high poly)"]

_ids = itertools.count(1)


def _uid():
    return next(_ids)


def _pad(lst, n, fill):
    lst = list(lst) if lst is not None else []
    return (lst + [fill] * n)[:n] if len(lst) < n else lst[:n]


# ---------------------------------------------------------------------------------- pieces
@dataclass
class MaskGen:
    """A procedural mask generator. Used directly as Layer.gen (legacy slot) and inside
    'generator' effects."""
    kind: int = 0
    level: float = 0.5
    softness: float = 0.08
    noise_amount: float = 0.3
    noise_scale: float = 1.0
    invert: bool = False
    axis: int = 1                 # Position Gradient / World Normal Axis: 0 X, 1 Y, 2 Z
    azimuth: float = 0.6          # Directional Light, radians
    elevation: float = 0.8
    seed: float = 0.0             # extra offset on top of the layer seed


@dataclass
class Projection:
    """How a fill layer / fill effect maps its images onto the mesh."""
    mode: int = 0                 # PROJECTIONS index
    scale: list = field(default_factory=lambda: [1.0, 1.0])
    offset: list = field(default_factory=lambda: [0.0, 0.0])
    rotation: float = 0.0         # degrees
    sharpness: float = 4.0        # tri-planar blend sharpness
    axis: int = 1                 # planar / cylindrical axis
    repeat_meters: float = 0.0     # planar/tri-planar physical period; zero uses ordinary scale
    warp: list | None = None      # four destination UV corners
    decal: bool = False           # clip the projection outside its unit square


# effect kinds: mask-side and content-side
MASK_EFFECTS = ["fill", "generator", "levels", "invert", "blur", "color_select", "anchor",
                "mesh_map", "threshold", "paint", "graph"]
CONTENT_EFFECTS = ["hsl", "levels", "invert", "blur", "brightness_contrast", "anchor", "graph"]

EFFECT_DEFAULTS = {
    "paint":      {"initial": 0.0},
    "fill":       {"value": 1.0, "map": None, "proj": None},
    "generator":  {"gen": None},
    "levels":     {"in_lo": 0.0, "in_hi": 1.0, "gamma": 1.0, "out_lo": 0.0, "out_hi": 1.0, "channel": 0},
    "invert":     {"channel": 0},
    "blur":       {"radius": 4.0, "channel": -1},
    "color_select": {"colors": [], "tolerance": 0.1, "hardness": 0.8},
    "anchor":     {"name": "", "source": "", "channel": 3},   # content: name=anchor to create; mask: source=anchor to read
    "mesh_map":   {"map": 0},
    "threshold":  {"level": 0.5, "softness": 0.02},
    "hsl":        {"hue": 0.0, "saturation": 0.0, "lightness": 0.0, "target": 0},  # target 0 color 1 emissive
    "brightness_contrast": {"brightness": 0.0, "contrast": 0.0, "channel": 0},
}


@dataclass
class Effect:
    """One entry of a layer's content or mask effect stack.

    Mask effects combine their value with the mask below using `blend` / `opacity`
    (generator, fill, color_select, anchor, mesh_map) or transform it (levels, invert, blur,
    threshold). Content effects transform the layer's channel values before it is blended
    into the stack. `channel` indexes CHANNELS (-1 = all, for blur)."""
    kind: str
    enabled: bool = True
    blend: int = 0
    opacity: float = 1.0
    params: dict = field(default_factory=dict)
    name: str = ""
    uid: int = field(default_factory=_uid)
    pid: str = field(default_factory=lambda: uuid.uuid4().hex)
    tex: object = field(default=None, repr=False, compare=False)   # optional GPU resource

    def __post_init__(self):
        base = copy.deepcopy(EFFECT_DEFAULTS.get(self.kind, {}))
        base.update(self.params or {})
        if self.kind == "generator":
            g = base.get("gen")
            if g is None:
                g = MaskGen(kind=1)
            elif isinstance(g, dict):
                g = MaskGen(**{k: v for k, v in g.items() if k in MaskGen.__dataclass_fields__})
            base["gen"] = g
        if self.kind == "fill":
            p = base.get("proj")
            if isinstance(p, dict):
                base["proj"] = Projection(**{k: v for k, v in p.items() if k in Projection.__dataclass_fields__})
        if self.kind == "graph":
            from .graphs import preset, validate
            base.setdefault("graph", preset())
            base.setdefault("channel", 0)
            validate(base["graph"])
            if type(base["channel"]) is not int or not 0<=base["channel"]<N_CH:raise ValueError("Native graph requires one channel")
        self.params = base
        if not self.name:
            self.name = self.kind.replace("_", " ").title()

    def to_dict(self) -> dict:
        p = {}
        for k, v in self.params.items():
            p[k] = asdict(v) if isinstance(v, (MaskGen, Projection)) else copy.deepcopy(v)
            if isinstance(v,Projection):
                if v.warp is None:p[k].pop("warp",None)
                if not v.decal:p[k].pop("decal",None)
        return {"kind": self.kind, "enabled": self.enabled, "blend": self.blend,
                "opacity": self.opacity, "params": p, "name": self.name, "pid": self.pid}

    @staticmethod
    def from_dict(d: dict) -> "Effect":
        return Effect(kind=d["kind"], enabled=d.get("enabled", True), blend=d.get("blend", 0),
                      opacity=d.get("opacity", 1.0), params=d.get("params", {}), name=d.get("name", ""),
                      pid=d.get("pid") or uuid.uuid4().hex)


# ---------------------------------------------------------------------------------- layer
_PADDED = {"enabled": False, "chan_blend": -1, "chan_opacity": 1.0}
_SKIP = ("tex", "mask_tex", "uid", "children", "effects", "mask_effects", "gen", "proj")


@dataclass
class Layer:
    name: str
    kind: str = "fill"                 # "fill" | "paint" | "group"
    visible: bool = True
    opacity: float = 1.0
    blend: int = 0                     # colour-style channels (Color, Emissive) unless chan_blend overrides
    hblend: int = 0                    # legacy height blend: 0 Normal, 1 Add
    color: list = field(default_factory=lambda: channel_default("C", "layer"))
    rough: float = channel_default("R", "layer")
    metal: float = channel_default("M", "layer")
    height: float = channel_default("H", "layer")
    normal: list = field(default_factory=lambda: channel_default("N", "layer"))
    emissive: list = field(default_factory=lambda: channel_default("E", "layer"))
    opac: float = channel_default("O", "layer")
    enabled: list = field(default_factory=lambda: enabled_defaults("layer"))
    chan_blend: list = field(default_factory=lambda: [-1] * N_CH)     # -1 = default for that channel
    chan_opacity: list = field(default_factory=lambda: [1.0] * N_CH)
    variation: float = 0.0             # fill: colour/roughness noise
    bump: float = 0.0                  # fill: height noise
    var_scale: float = 1.0
    seed: float = field(default_factory=lambda: random.random())
    maps: dict = field(default_factory=dict)          # fill: channel key -> image path
    user_channels: dict = field(default_factory=dict)
    authored: dict | None = None  # persistent surface path/ribbon/region or font text
    proj: Projection = field(default_factory=Projection)
    has_mask: bool = False
    mask_enabled: bool = True          # Shift+click on the mask thumbnail: bypass the whole mask stack
    gen: MaskGen = field(default_factory=MaskGen)    # legacy single generator (multiplies the mask)
    effects: list = field(default_factory=list)       # content effects (Effect)
    mask_effects: list = field(default_factory=list)  # mask effects (Effect)
    part_mask: Optional[list] = None                  # geometry mask: mesh part ids to keep (None = all)
    children: list = field(default_factory=list)      # group layers, bottom first
    expanded: bool = True
    raster_res: Optional[int] = None  # canonical shared raster; each set owns evaluated outputs
    uid: int = field(default_factory=_uid)
    pid: str = field(default_factory=lambda: uuid.uuid4().hex)
    # GPU resources (not serialised)
    tex: Optional[dict] = field(default=None, repr=False, compare=False)   # paint: C,R,M,H,N,E,O
    mask_tex: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        self.enabled = _pad(self.enabled, N_CH, False)
        self.chan_blend = _pad(self.chan_blend, N_CH, -1)
        self.chan_opacity = _pad(self.chan_opacity, N_CH, 1.0)

    def __setattr__(self, name, value):
        # older code (and the UI) assigns 4-entry channel lists; keep them N_CH long
        if name in _PADDED and value is not None and len(value) != N_CH:
            value = _pad(value, N_CH, _PADDED[name])
        object.__setattr__(self, name, value)

    # -- semantics
    @property
    def is_group(self) -> bool:
        return self.kind == "group"

    def blend_for(self, ch: int) -> int:
        """Effective blend mode index for channel ch."""
        b = self.chan_blend[ch] if ch < len(self.chan_blend) else -1
        if b is not None and b >= 0:
            return int(b)
        if ch in (0, 5):                       # Color, Emissive follow the layer blend
            return int(self.blend)
        if ch == 3:                            # Height follows the legacy height blend
            return B_ADD if self.hblend == 1 else B_NORMAL
        return B_NORMAL

    def has_mask_stack(self) -> bool:
        if not self.mask_enabled:
            return False
        return (self.has_mask and self.mask_tex is not None) or self.gen.kind != 0 \
            or any(e.enabled for e in self.mask_effects) or self.part_mask is not None

    def walk(self):
        """Yield this layer and all descendants (depth first, bottom first)."""
        yield self
        for c in self.children:
            yield from c.walk()

    # -- serialisation
    def to_dict(self) -> dict:
        d = {k: copy.deepcopy(getattr(self, k)) for k in self.__dataclass_fields__ if k not in _SKIP}
        if not d.get("user_channels"):d.pop("user_channels", None)
        if d.get("authored") is None:d.pop("authored",None)
        if d.get("raster_res") is None:
            d.pop("raster_res", None)
        d["gen"] = asdict(self.gen)
        d["proj"] = asdict(self.proj)
        if self.proj.warp is None:d["proj"].pop("warp",None)
        if not self.proj.decal:d["proj"].pop("decal",None)
        if not self.proj.repeat_meters:
            d["proj"].pop("repeat_meters", None)
        d["color"] = [float(c) for c in self.color]
        d["enabled"] = [bool(e) for e in self.enabled]
        d["effects"] = [e.to_dict() for e in self.effects]
        d["mask_effects"] = [e.to_dict() for e in self.mask_effects]
        d["children"] = [c.to_dict() for c in self.children]
        return d

    @staticmethod
    def from_dict(d: dict) -> "Layer":
        d = dict(d)
        if not d.get("pid"):
            d.pop("pid", None)
        gen = MaskGen(**{k: v for k, v in d.pop("gen", {}).items() if k in MaskGen.__dataclass_fields__})
        proj = Projection(**{k: v for k, v in d.pop("proj", {}).items() if k in Projection.__dataclass_fields__})
        effects = [Effect.from_dict(e) for e in d.pop("effects", [])]
        meffects = [Effect.from_dict(e) for e in d.pop("mask_effects", [])]
        children = [Layer.from_dict(c) for c in d.pop("children", [])]
        known = Layer.__dataclass_fields__.keys()
        lay = Layer(**{k: v for k, v in d.items() if k in known and k not in _SKIP})
        lay.gen, lay.proj = gen, proj
        lay.effects, lay.mask_effects, lay.children = effects, meffects, children
        return lay


def group(name="Group", children=None, **kw) -> Layer:
    lay = Layer(name=name, kind="group", children=list(children or []), **kw)
    return lay


def _evaluation_layers(layers):
    """Yield in compositor order: children before their group's anchor capture."""
    for layer in ([layers] if isinstance(layers, Layer) else layers):
        yield from _evaluation_layers(layer.children)
        yield layer


def bind_anchor_references(layers):
    """Migrate unique legacy anchor names; report unresolved evaluation dependencies.

    Once bound, a reference uses its source effect's persistent ID exclusively. Names
    remain editable labels and never silently redirect an existing reference.
    """
    ordered = list(_evaluation_layers(layers))
    definitions, names, diagnostics = {}, {}, []
    for index, layer in enumerate(ordered):
        for effect in layer.effects:
            if effect.kind == "anchor" and effect.params.get("name"):
                definitions.setdefault(effect.pid, (index, effect))
                names.setdefault(effect.params["name"], []).append(effect.pid)
    for index, layer in enumerate(ordered):
        for effect in layer.mask_effects:
            if effect.kind != "anchor":
                continue
            source = effect.params.get("source_pid")
            label = effect.params.get("source") or effect.params.get("name") or "(unnamed)"
            if not source:
                matches = list(dict.fromkeys(names.get(label, [])))
                if len(matches) == 1:
                    source = effect.params["source_pid"] = matches[0]
                else:
                    diagnostics.append(f"Anchor {label!r}: {'ambiguous' if matches else 'missing'} source")
                    continue
            definition = definitions.get(source)
            if definition is None:
                diagnostics.append(f"Anchor {label!r}: missing source {source}")
            elif definition[0] >= index:
                diagnostics.append(f"Anchor {label!r}: forward or cyclic source")
    return diagnostics


def renew_persistent_ids(layers):
    """Assign a copied forest new identities, remapping references within that forest."""
    ordered = list(_evaluation_layers(layers))
    objects, seen = [], set()
    for layer in ordered:
        for obj in [layer] + layer.effects + layer.mask_effects:
            if id(obj) not in seen:
                seen.add(id(obj))
                objects.append(obj)
    mapping = {}
    for obj in objects:
        old = obj.pid
        obj.pid = uuid.uuid4().hex
        mapping.setdefault(old, obj.pid)
    for layer in ordered:
        for effect in layer.effects + layer.mask_effects:
            source = effect.params.get("source_pid")
            if source in mapping:
                effect.params["source_pid"] = mapping[source]
    return layers


# ---------------------------------------------------------------------------------- brush
TOOLS = ["Paint", "Smudge", "Clone", "Projection"]     # Erase = Paint with mode 1
ALIGNMENTS = ["Camera", "Tangent | Wrap", "Tangent | Planar", "UV"]
SIZE_SPACES = ["Viewport (px)", "Object", "UV / Texture"]
SYMMETRY = ["Off", "Mirror", "Radial"]
STENCIL_TILING = ["None", "Horizontal", "Vertical", "Both"]


@dataclass
class Brush:
    user_channel: str | None = None
    user_value: float = 1.0
    size_px: float = 60.0
    hardness: float = 0.5
    flow: float = 0.6
    spacing: float = 0.15              # fraction of the brush diameter between dabs
    grain: float = 0.0
    grain_scale: float = 40.0
    color: list = field(default_factory=lambda: channel_default("C", "brush"))
    rough: float = channel_default("R", "brush")
    metal: float = channel_default("M", "brush")
    height: float = channel_default("H", "brush")
    normal: list = field(default_factory=lambda: channel_default("N", "brush"))
    emissive: list = field(default_factory=lambda: channel_default("E", "brush"))
    opac: float = channel_default("O", "brush")
    enabled: list = field(default_factory=lambda: enabled_defaults("brush"))
    mode: int = 0          # 0 paint 1 erase
    target: int = 0        # 0 layer 1 mask 2 quick mask
    mask_value: float = 1.0
    # --- extended brush engine
    tool: int = 0                      # TOOLS index
    stroke_opacity: float = 1.0
    angle: float = 0.0                 # degrees
    follow_path: bool = False
    seed: int = 17                    # deterministic jitter, independent of undo-history length
    size_jitter: float = 0.0
    flow_jitter: float = 0.0
    angle_jitter: float = 0.0
    pos_jitter: float = 0.0
    alignment: int = 1                 # ALIGNMENTS index (Tangent | Wrap)
    backface: float = 80.0             # degrees: surfaces turned further than this from the view are skipped
    size_space: int = 0                # SIZE_SPACES index
    size_obj: float = 0.06             # brush diameter as a fraction of the mesh size (Object space)
    size_uv: float = 0.03              # brush diameter in UV units (UV space)
    alpha: Optional[str] = None        # built-in alpha name or image path; None = round
    alpha_invert: bool = False
    stencil: Optional[str] = None      # image path
    stencil_enabled: bool = True
    stencil_xform: list = field(default_factory=lambda: [0.5, 0.5, 1.0, 0.0])  # cx, cy (viewport 0-1), scale, rotation deg
    stencil_tiling: int = 0
    maps: dict = field(default_factory=dict)           # brush stamp: channel key -> image path
    proj_maps: dict = field(default_factory=dict)       # projection tool: channel key -> image path
    proj_xform: list = field(default_factory=lambda: [0.5, 0.5, 1.0, 0.0])
    proj_tiling: int = 3
    symmetry: int = 0                  # SYMMETRY index
    sym_axis: int = 0                  # 0 X, 1 Y, 2 Z
    sym_center: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    radial_count: int = 4
    lazy: float = 0.0                  # lazy-mouse distance in pixels (0 = off)
    pressure_size: bool = False
    pressure_flow: bool = True
    min_size: float = 0.2              # fraction of size at zero pressure
    min_flow: float = 0.0
    smudge_strength: float = 0.7
    use_quick_mask: bool = True

    def __post_init__(self):
        self.enabled = _pad(self.enabled, N_CH, False)

    def __setattr__(self, name, value):
        if name == "enabled" and value is not None and len(value) != N_CH:
            value = _pad(value, N_CH, False)
        object.__setattr__(self, name, value)

    def to_dict(self) -> dict:
        return {f.name: copy.deepcopy(getattr(self, f.name)) for f in fields(self)}

    def load_dict(self, d: dict):
        for k, v in d.items():
            if hasattr(self, k):
                setattr(self, k, copy.deepcopy(v))
        self.enabled = _pad(self.enabled, N_CH, False)
