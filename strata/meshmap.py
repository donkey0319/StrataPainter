"""External mesh-map semantics and validation, independent of UI and OpenGL."""
from pathlib import Path
import hashlib
import numpy as np
from .imageio import read_image

# Public keys use BakeSet.maps(), so generators and previews consume one interface.
SLOTS = {"ao": ("Ambient occlusion", "ao", "f2"), "curvature": ("Curvature", "curv", "f2"),
         "thickness": ("Thickness", "thick", "f2"), "id": ("ID", "id", "f1"),
         "normal": ("Tangent normal", "normal_hp", "f2"), "height": ("Height", "height_hp", "f2"),
         "world_normal": ("World normal", "nrm", "f2"), "position": ("Object position", "pos", "f4")}


def read_map(path, key, resolution, interpretation="data"):
    if key not in SLOTS:
        raise ValueError("Unknown external mesh-map channel")
    expected = "object" if key == "position" else ("encoded" if key == "world_normal" else "data")
    if interpretation != expected:
        raise ValueError(f"{key} requires {expected} interpretation; mesh maps bypass color transforms")
    path = str(Path(path).expanduser().resolve())
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    values = read_image(path)
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
        raise ValueError("Mesh-map source changed while reading; retry assignment")
    if values.shape[:2] != (resolution, resolution):
        raise ValueError(f"Mesh map must match this texture set: {resolution} x {resolution}")
    if not np.isfinite(values).all():
        raise ValueError("Mesh map contains nonfinite values")
    rgb = key in ("id", "normal", "world_normal", "position")
    if rgb and values.shape[2] < 3:
        raise ValueError(f"{key} requires at least three components")
    result = np.ones((resolution, resolution, 4), np.float32)
    if rgb:
        result[..., :3] = values[..., :3]
    else:
        result[..., :3] = values[..., :1]
    if key == "world_normal":
        normal = result[..., :3] * 2 - 1
        length = np.linalg.norm(normal, axis=2, keepdims=True)
        if np.any(length < 1e-6):
            raise ValueError("World-normal map contains zero-length normals")
        result[..., :3] = normal / length
    return result, {"path": path, "sha256": digest,
                    "interpretation": interpretation}


def settings_provenance(settings):
    result = settings.to_dict()
    result.pop("high_poly", None)
    if result.get("cage_hash"):
        result.pop("cage_path", None)
    for record in result.get("external_maps", {}).values():
        record.pop("path", None)  # content identity survives portable extraction/relinking
    if not result.get("external_maps"):
        result.pop("external_maps", None)
    return result
