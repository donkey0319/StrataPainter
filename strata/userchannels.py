"""Project-local scalar channels and shared shader/export semantics (native v13)."""
import copy
import math
import re
from dataclasses import replace
from .channels import BY_KEY, CHANNEL_DESCRIPTORS

KEY = re.compile(r"user:[a-z][a-z0-9_]{0,31}\Z")
MAX_CHANNELS = 16
DEFAULT_WORKFLOW = {"model": "metal_rough", "bindings": {}, "displacement_meters": 0., "height_midlevel": .5}
BINDINGS = {"specular_r", "specular_g", "specular_b", "glossiness", "coat", "coat_roughness"}


def is_user(key):
    return isinstance(key, str) and KEY.fullmatch(key) is not None


def descriptor(key):
    if is_user(key):
        return replace(BY_KEY["H"], key=key, label=key[5:], semantic="data")
    return BY_KEY[key]


def paint_channels(brush):
    if brush.user_channel and brush.target == 0:
        return [descriptor(brush.user_channel)]
    return [c for c in CHANNEL_DESCRIPTORS if brush.enabled[c.index]]


def validate(definitions, workflow=None):
    if not isinstance(definitions, dict) or len(definitions) > MAX_CHANNELS:
        raise ValueError("At most 16 user channels are supported")
    for key, value in definitions.items():
        if not is_user(key) or not isinstance(value, dict) or set(value) != {"label", "default"}:
            raise ValueError("User channel requires a user:name key, label and default")
        if not isinstance(value["label"], str) or not 1 <= len(value["label"]) <= 80:
            raise ValueError("Invalid user channel label")
        unit_value(value["default"])
    if workflow is None:
        return
    if not isinstance(workflow, dict) or set(workflow) != set(DEFAULT_WORKFLOW):
        raise ValueError("Invalid shader workflow")
    if workflow["model"] not in ("metal_rough", "spec_gloss"):
        raise ValueError("Unknown shading model")
    bindings = workflow["bindings"]
    if not isinstance(bindings, dict) or set(bindings) - BINDINGS or any(v not in definitions for v in bindings.values()):
        raise ValueError("Shader binding requires a declared user channel")
    if workflow["model"] == "spec_gloss" and not {"specular_r", "specular_g", "specular_b", "glossiness"} <= bindings.keys():
        raise ValueError("Specular/glossiness requires independent RGB F0 and glossiness channels")
    if not isinstance(workflow["displacement_meters"], (float, int)) or not math.isfinite(workflow["displacement_meters"]) or abs(workflow["displacement_meters"]) > 1:
        raise ValueError("Displacement must be finite and within +/-1 meter")
    unit_value(workflow["height_midlevel"])


def unit_value(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Channel values must be finite in [0, 1]")
    return float(value)


def layer_values(values, definitions):
    if not isinstance(values, dict) or set(values) - definitions.keys():
        raise ValueError("Layer references an undeclared user channel")
    for value in values.values():
        if not isinstance(value, dict) or set(value) != {"value", "enabled", "blend", "opacity"}:
            raise ValueError("Invalid user channel layer settings")
        unit_value(value["value"]); unit_value(value["opacity"])
        if type(value["enabled"]) is not bool or type(value["blend"]) is not int or not -1 <= value["blend"] <= 28:
            raise ValueError("Invalid scalar channel blend/enable")


def mapped_layers(layers, key, default):
    """Use the established scalar passes; retain original masks and resource identities."""
    originals = {}
    def mapped(source):
        layer = copy.copy(source)
        originals[id(layer)] = source
        setting = source.user_channels.get(key, {})
        active = setting.get("enabled", source.is_group)
        layer.enabled = [False, False, False, active, False, False, False]
        layer.chan_blend = [-1] * 7
        layer.chan_blend[3] = setting.get("blend", -1)
        layer.chan_opacity = [1.] * 7
        layer.chan_opacity[3] = setting.get("opacity", 1.)
        layer.height = setting.get("value", default)
        layer.hblend = 0; layer.bump = 0.
        layer.maps = {"H": source.maps[key]} if key in source.maps else {}
        layer.tex = {"H": source.tex.get(key)} if source.tex is not None else None
        layer.children = [mapped(child) for child in source.children]
        layer.effects = []
        for effect in source.effects:
            if effect.params.get("user_channel") == key:
                result = copy.copy(effect)
                result.params = dict(effect.params, channel=3)
                result.params.pop("user_channel", None)
                layer.effects.append(result)
        return layer
    return [mapped(layer) for layer in layers], originals


def validate_resolution(definitions, resolution):
    if len(definitions) * int(resolution)**2 * 2 > 256 * 1024**2:
        raise MemoryError("User channel outputs exceed the 256 MiB evaluation budget; reduce channels or resolution")
