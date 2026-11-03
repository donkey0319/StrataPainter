"""CPU-only channel semantics and adapters for the existing seven-channel GPU layout.

Descriptors describe current storage; they do not make the shaders dynamically
extensible or apply color transforms. RGB defaults are immutable tuples here and
become independent mutable lists only at the data-model boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ChannelDescriptor:
    index: int
    key: str
    label: str
    attribute: str
    value_components: int
    paint_components: int
    paint_dtype: str
    resource_kind: str
    layer_default: float | tuple[float, ...]
    brush_default: float | tuple[float, ...]
    composite_default: float | tuple[float, ...]
    accumulator_index: int
    accumulator_components: tuple[int, ...]
    composite_dtype: str
    export_sources: tuple[str, ...]
    value_label: str = ""
    semantic: str = ""


CHANNEL_DESCRIPTORS = (
    ChannelDescriptor(0, "C", "Color", "color", 3, 4, "f2", "color",
                      (.5, .5, .5), (.75, .2, .12), (.5, .5, .5), 0, (0, 1, 2), "f1", ("basecolor",), "Color", "color"),
    ChannelDescriptor(1, "R", "Rough", "rough", 1, 2, "f2", "data",
                      .5, .45, .6, 1, (0,), "f2", ("roughness",), "Roughness", "data"),
    ChannelDescriptor(2, "M", "Metal", "metal", 1, 2, "f2", "data",
                      0., 0., 0., 1, (1,), "f2", ("metallic",), "Metallic", "data"),
    ChannelDescriptor(3, "H", "Height", "height", 1, 2, "f2", "data",
                      .5, .65, .5, 1, (2,), "f2", ("height",), "Height", "height"),
    ChannelDescriptor(4, "N", "Normal", "normal", 3, 4, "f2", "data",
                      (.5, .5, 1.), (.5, .5, 1.), (.5, .5, 1.), 3, (0, 1, 2), "f1",
                      ("normal_opengl", "normal_directx"), "Normal", "encoded tangent normal"),
    ChannelDescriptor(5, "E", "Emissive", "emissive", 3, 4, "f2", "color",
                      (0., 0., 0.), (1., .6, .2), (0., 0., 0.), 2, (0, 1, 2), "f1", ("emissive",), "Emissive", "color"),
    ChannelDescriptor(6, "O", "Opacity", "opac", 1, 2, "f2", "data",
                      1., 1., 1., 1, (3,), "f2", ("opacity",), "Opacity", "data"),
)
BY_KEY = MappingProxyType({channel.key: channel for channel in CHANNEL_DESCRIPTORS})
N_CH = len(CHANNEL_DESCRIPTORS)
# Historical container types remain available to existing callers.
CHANNELS = [channel.label for channel in CHANNEL_DESCRIPTORS]
CH_KEYS = [channel.key for channel in CHANNEL_DESCRIPTORS]
CH_COMPONENTS = {channel.key: channel.paint_components for channel in CHANNEL_DESCRIPTORS}
_ENABLED = {"layer": frozenset(("C", "R", "M", "H")), "brush": frozenset(("C", "R", "M"))}


def channel_default(key: str, role: str):
    """Return a channel's role default, copying vector values for each caller."""
    if role not in ("layer", "brush", "composite"):
        raise ValueError(f"Unknown channel default role: {role}")
    value = getattr(BY_KEY[key], role + "_default")
    return list(value) if isinstance(value, tuple) else value


def enabled_defaults(role: str) -> list[bool]:
    """Return independent enable flags for a newly created layer or brush."""
    if role not in _ENABLED:
        raise ValueError(f"Unknown channel enable role: {role}")
    return [channel.key in _ENABLED[role] for channel in CHANNEL_DESCRIPTORS]


def _accumulator_layout():
    slots = max(channel.accumulator_index for channel in CHANNEL_DESCRIPTORS) + 1
    clear = [[1.] * 4 for _ in range(slots)]
    dtypes = [None] * slots
    for channel in CHANNEL_DESCRIPTORS:
        index = channel.accumulator_index
        if dtypes[index] is not None and dtypes[index] != channel.composite_dtype:
            raise ValueError("Channels sharing an accumulator must agree on its dtype")
        dtypes[index] = channel.composite_dtype
        values = channel.composite_default
        values = values if isinstance(values, tuple) else (values,)
        for component, value in zip(channel.accumulator_components, values):
            clear[index][component] = value
    return tuple(dtypes), tuple(tuple(slot) for slot in clear)


ACC_DTYPES, ACC_CLEAR = _accumulator_layout()
