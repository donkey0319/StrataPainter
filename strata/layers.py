"""Layer stack data model."""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field, asdict
from typing import Optional

BLEND_MODES = ["Normal", "Multiply", "Screen", "Overlay", "Add"]
HEIGHT_BLEND = ["Normal", "Add"]
GENERATORS = ["None", "Edge Wear", "Dirt / Cavity", "Ambient Occlusion",
              "Upward Facing (dust)", "Height Gradient", "Noise"]
CHANNELS = ["Color", "Rough", "Metal", "Height"]

_ids = itertools.count(1)


@dataclass
class MaskGen:
    kind: int = 0
    level: float = 0.5
    softness: float = 0.08
    noise_amount: float = 0.3
    noise_scale: float = 1.0
    invert: bool = False


@dataclass
class Layer:
    name: str
    kind: str = "fill"                 # "fill" | "paint"
    visible: bool = True
    opacity: float = 1.0
    blend: int = 0
    hblend: int = 0
    color: list = field(default_factory=lambda: [0.5, 0.5, 0.5])
    rough: float = 0.5
    metal: float = 0.0
    height: float = 0.5
    enabled: list = field(default_factory=lambda: [True, True, True, True])
    variation: float = 0.0             # fill: colour/roughness noise
    bump: float = 0.0                  # fill: height noise
    var_scale: float = 1.0
    seed: float = field(default_factory=lambda: random.random())
    has_mask: bool = False
    gen: MaskGen = field(default_factory=MaskGen)
    uid: int = field(default_factory=lambda: next(_ids))
    # GPU resources (not serialised)
    tex: Optional[dict] = field(default=None, repr=False, compare=False)   # paint: C,R,M,H
    mask_tex: object = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k not in ("tex", "mask_tex", "uid")}
        d["gen"] = asdict(self.gen)
        d["color"] = [float(c) for c in self.color]
        d["enabled"] = [bool(e) for e in self.enabled]
        return d

    @staticmethod
    def from_dict(d: dict) -> "Layer":
        d = dict(d)
        gen = MaskGen(**d.pop("gen", {}))
        known = Layer.__dataclass_fields__.keys()
        lay = Layer(**{k: v for k, v in d.items() if k in known and k not in ("tex", "mask_tex", "uid")})
        lay.gen = gen
        return lay


@dataclass
class Brush:
    size_px: float = 60.0
    hardness: float = 0.5
    flow: float = 0.6
    spacing: float = 0.15
    grain: float = 0.0
    grain_scale: float = 40.0
    color: list = field(default_factory=lambda: [0.75, 0.2, 0.12])
    rough: float = 0.45
    metal: float = 0.0
    height: float = 0.65
    enabled: list = field(default_factory=lambda: [True, True, True, False])
    mode: int = 0          # 0 paint 1 erase
    target: int = 0        # 0 layer 1 mask
    mask_value: float = 1.0
