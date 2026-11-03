"""CPU validation for fill-material edits; no document or GPU side effects."""
from __future__ import annotations

import math
import numbers

from .layers import PROJECTIONS, BLEND_MODES


def projection_changes(changes):
    """Return validated, detached values for the existing Projection fields."""
    allowed = {"mode", "scale", "offset", "rotation", "sharpness", "axis", "repeat_meters", "warp", "decal"}
    if set(changes) - allowed:
        raise ValueError("Unknown projection properties: " + ", ".join(sorted(set(changes) - allowed)))
    result = {}
    for key, value in changes.items():
        if key=="warp":
            from .authored import warp_matrix
            warp_matrix(value)
            result[key]=None if value is None else [[float(x) for x in row] for row in value]
        elif key=="decal":
            if type(value) is not bool:raise ValueError("Decal clipping must be boolean")
            result[key]=value
        elif key in ("mode", "axis"):
            limit = len(PROJECTIONS) if key == "mode" else 3
            if isinstance(value, bool) or not isinstance(value, numbers.Integral) or not 0 <= value < limit:
                raise ValueError(f"Invalid projection {key}")
            result[key] = int(value)
        elif key in ("scale", "offset"):
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError(f"Projection {key} needs two finite values")
            values = [finite_number(item, f"projection {key}") for item in value]
            if key == "scale" and any(abs(item) < 1e-6 for item in values):
                raise ValueError("Projection scale must be nonzero")
            result[key] = values
        else:
            result[key] = finite_number(value, "projection " + key)
            if key == "sharpness" and result[key] <= 0:
                raise ValueError("Tri-planar sharpness must be positive")
            if key == "repeat_meters" and result[key] < 0:
                raise ValueError("Physical repeat must be nonnegative")
    return result


def finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)


def channel_settings(blend=None, opacity=None):
    """Validate a channel override; -1 uses the layer's inherited blend rule."""
    result = {}
    if blend is not None:
        if (isinstance(blend, bool) or not isinstance(blend, numbers.Integral) or
                not -1 <= blend < len(BLEND_MODES)):
            raise ValueError("Invalid channel blend mode")
        result["blend"] = int(blend)
    if opacity is not None:
        value = finite_number(opacity, "Channel opacity")
        if not 0 <= value <= 1:
            raise ValueError("Channel opacity must be between zero and one")
        result["opacity"] = value
    return result
