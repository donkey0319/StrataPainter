"""GPU resource cache: user images (fill maps, stencils, projections, alphas, environments) and
built-in procedural brush alphas.

Resources are addressed by a string: a file path, or "builtin:<Alpha Name>" for built-in alphas.
"""
from __future__ import annotations

import os

import moderngl
import numpy as np

from .imageio import read_image
from .color import ColorPipeline

from .alphas import BUILTIN_ALPHAS, ALPHA_RES, make_alpha, _grid, _smooth


class Resources:
    def __init__(self, gpu, pipeline=None):
        self.gpu = gpu
        self.pipeline = pipeline or ColorPipeline()
        self.user_channels = {}
        from .userchannels import DEFAULT_WORKFLOW
        import copy
        self.shader_workflow = copy.deepcopy(DEFAULT_WORKFLOW)
        self._cache = {}

    def _key(self, path, kind):
        try:
            mt = os.path.getmtime(path)
        except OSError:
            mt = 0
        return (path, kind, mt, self.pipeline.cache_id)

    def texture(self, path: str | None, kind: str = "color", repeat=True):
        """Load an image as a GPU texture (cached). kind: 'color' | 'data' | 'gray' | 'hdr'.
        Returns None for an empty path; raises on unreadable files."""
        if not path:
            return None
        if path.startswith("builtin:"):
            return self.alpha(path[8:])
        key = self._key(path, kind)
        tex = self._cache.get(key)
        if tex is not None:
            return tex
        arr = read_image(path)[::-1]              # GL rows start at the bottom
        if arr.shape[2] == 2:
            arr = np.dstack([arr[..., :1]] * 3 + [arr[..., 1:2]])
        if arr.shape[2] == 1:
            arr = np.dstack([arr] * 3 + [np.ones_like(arr)])
        if arr.shape[2] == 3:
            arr = np.dstack([arr, np.ones(arr.shape[:2] + (1,), np.float32)])
        arr = self.pipeline.image(path, arr, "color" if kind == "preview" else kind)
        if kind == "preview" and self.pipeline.managed:
            arr[..., :3] = self.pipeline.display_values(arr[..., :3])
        hdr = kind == "hdr" or arr.max() > 1.0
        dtype = "f4" if self.pipeline.managed and kind == "color" else ("f2" if hdr or kind in ("data", "gray") else "f1")
        h, w = arr.shape[:2]
        tex = self.gpu.texture((w, h), 4, arr, dtype=dtype, repeat=repeat)
        tex.build_mipmaps()
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.anisotropy = 8.0
        self._cache[key] = tex
        return tex

    def alpha(self, name: str):
        """Brush alpha texture. name: built-in alpha name, 'builtin:<name>' or an image path."""
        if not name:
            return None
        if name.startswith("builtin:"):
            name = name[8:]
        if name not in BUILTIN_ALPHAS:
            key = ("alpha", name, self._key(name, "a")[2])
            tex = self._cache.get(key)
            if tex is None:
                arr = read_image(name)[::-1]
                if arr.shape[2] in (2, 4):
                    v = arr[..., -1] * (arr[..., :3].mean(-1) if arr.shape[2] == 4 else arr[..., 0])
                    if np.allclose(arr[..., -1], 1):
                        v = arr[..., :min(3, arr.shape[2] - 1)].mean(-1)
                else:
                    v = arr.mean(-1)
                tex = self._make_alpha_tex(v)
                self._cache[key] = tex
            return tex
        key = ("alpha", name)
        tex = self._cache.get(key)
        if tex is None:
            tex = self._cache[key] = self._make_alpha_tex(make_alpha(name))
        return tex

    def _make_alpha_tex(self, v):
        h, w = v.shape
        tex = self.gpu.texture((w, h), 1, v.astype(np.float32), dtype="f1")
        tex.build_mipmaps()
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.repeat_x = tex.repeat_y = False
        return tex

    def lut(self, values, n=1024):
        """1D lookup texture (n x 1, R8) used for per-part geometry masks. Not cached."""
        arr = np.zeros(n, np.float32)
        arr[:len(values)] = values[:n]
        t = self.gpu.texture((n, 1), 1, arr, dtype="f1", filt=False)
        return t

    def image_size(self, path):
        t = self.texture(path)
        return t.size if t is not None else (1, 1)

    def release(self):
        for t in self._cache.values():
            t.release()
        self._cache.clear()
