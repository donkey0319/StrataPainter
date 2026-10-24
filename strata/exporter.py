"""Write the final texture set to disk in engine-ready layouts."""
from __future__ import annotations

import os
import re

import numpy as np
from PIL import Image

from .baker import PAD

EXPORT_PRESETS = ["Unreal Engine (BC / N DirectX / ORM)", "Unity (Albedo / Normal / Metallic+Smoothness)",
                  "Separate maps (OpenGL normal)"]


def _u8(a):
    return (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)


def _u16(a):
    return (np.clip(a, 0, 1) * 65535 + 0.5).astype(np.uint16)


def _save(img: np.ndarray, path: str):
    if img.dtype == np.uint16:
        Image.fromarray(img, mode="I;16").save(path)
    else:
        Image.fromarray(img).save(path)


def export(engine, folder: str, preset: int = 0, name: str | None = None) -> list[str]:
    os.makedirs(folder, exist_ok=True)
    engine.dirty = True
    engine.update()
    g, comp, bakes = engine.gpu, engine.comp, engine.bakes
    # extra padding for mip-mapping in the target engine
    tex = {k: g.clone(t) for k, t in (("C", comp.color), ("R", comp.rmh), ("N", comp.normal), ("AO", bakes.ao))}
    for t in tex.values():
        g.dilate(t, bakes.cov, PAD)
    # GL rows start at v=0 (bottom); image files start at the top
    C = g.read(tex["C"])[::-1]
    R = g.read(tex["R"])[::-1]
    N = g.read(tex["N"])[::-1]
    AO = g.read(tex["AO"])[::-1, :, 0]
    for t in tex.values():
        t.release()
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", name or engine.mesh.name).strip("_") or "Mesh"
    rough, metal, height = R[..., 0], R[..., 1], R[..., 2]
    out = []

    def put(suffix, img):
        p = os.path.join(folder, f"{base}_{suffix}.png" if preset else f"T_{base}_{suffix}.png")
        _save(img, p)
        out.append(p)

    if preset == 0:      # Unreal: DirectX normals (green down), ORM packing
        n = N[..., :3].copy(); n[..., 1] = 1.0 - n[..., 1]
        put("BC", _u8(C[..., :3]))
        put("N", _u8(n))
        put("ORM", _u8(np.dstack([AO, rough, metal])))
        put("H", _u16(height))
    elif preset == 1:    # Unity standard: metallic in R, smoothness in A, OpenGL normals
        put("Albedo", _u8(C[..., :3]))
        put("Normal", _u8(N[..., :3]))
        put("MetallicSmoothness", _u8(np.dstack([metal, metal, metal, 1.0 - rough])))
        put("AO", _u8(AO))
        put("Height", _u16(height))
    else:
        put("BaseColor", _u8(C[..., :3]))
        put("Roughness", _u8(rough))
        put("Metallic", _u8(metal))
        put("Normal", _u8(N[..., :3]))
        put("Height", _u16(height))
        put("AO", _u8(AO))
    return out
