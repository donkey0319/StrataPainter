"""Read access to Substance 3D Painter files: projects (.spp), smart materials (.spsm), smart masks
(.spmsk) and other HDF5-based shelf presets.

All of them are HDF5 containers. What lives inside (observed in Painter 2018 - 12):

  projectsettings.ini        QVariantMap: versionAtCreation/*, versionAtLastSave/*   (.spp)
  paint/document.bin         HBO stream: texture sets ("materials"), channels, layer stacks (.spp)
  paint/scene.assbin         the imported mesh, Assimp binary dump                     (.spp)
  preset.bin [_1, _2]        HBO stream: DataLayersPreset (smart material / mask)      (.spsm/.spmsk)
  resources/<sha>[.ext]      embedded resources: .sbsar (7z), .image (tiled JPEG 2000), .shader ...
  resources.toc              QVariantMap
  .alg_meta/preset.bin       QVariantMap with shelf metadata; "previews" holds a WebP thumbnail

Resources are referenced from HBO data by URL, e.g.
  '/grunge_rust_fine/grunge_rust_fine?version=13c7e7...e1e.sbsar'  -> resources/13c7e7...e1e.sbsar
  '/Toad_curvature?version=1d38f177e0b4...'                        -> resources/1d38f177e0b4...
"""
from __future__ import annotations

import io
import os
import re
import struct

import numpy as np

from . import hbo, qt

HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
EXT_KINDS = {".spp": "project", ".spsm": "smart_material", ".spmsk": "smart_mask",
             ".spfilt": "filter", ".spgen": "generator", ".sppr": "preset"}


class SPFileError(ValueError):
    pass


def _h5py():
    try:
        import h5py
    except ImportError as e:      # keep the message actionable for users of Strata.bat
        raise SPFileError("Reading Substance files needs the 'h5py' package: pip install h5py") from e
    return h5py


def is_substance_file(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(8) == HDF5_MAGIC
    except OSError:
        return False


class SPFile:
    """An open Painter HDF5 file. Use as a context manager or call close()."""

    def __init__(self, path: str):
        if not os.path.isfile(path):
            raise SPFileError(f"File not found: {path}")
        if not is_substance_file(path):
            raise SPFileError(f"{os.path.basename(path)} is not a Substance Painter file (no HDF5 header)")
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.h5 = _h5py().File(path, "r")
        ext = os.path.splitext(path)[1].lower()
        if "paint/document.bin" in self.h5:
            self.kind = "project"
        elif "preset.bin" in self.h5:
            self.kind = EXT_KINDS.get(ext, "smart_material")
        else:
            self.kind = EXT_KINDS.get(ext, "unknown")
        self._decoded = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            self.h5.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ raw access
    def has(self, name: str) -> bool:
        return name in self.h5

    def raw(self, name: str) -> bytes:
        d = self.h5[name][()]
        return d.tobytes() if hasattr(d, "tobytes") else bytes(d)

    def datasets(self):
        out = []
        self.h5.visititems(lambda n, o: out.append(n) if hasattr(o, "shape") else None)
        return out

    def hbo(self, name: str):
        """Decode an HBO dataset -> root HObj (cached)."""
        if name not in self._decoded:
            if name not in self.h5:
                raise SPFileError(f"{self.name}: missing {name}")
            root, enc, dv = hbo.decode(self.raw(name))
            self._decoded[name] = (root, enc, dv)
        return self._decoded[name][0]

    def encoding(self, name: str):
        self.hbo(name)
        return self._decoded[name][1:]

    # ------------------------------------------------------------------ metadata
    def settings(self) -> dict:
        if "projectsettings.ini" not in self.h5:
            return {}
        try:
            return qt.read_map(self.raw("projectsettings.ini"))
        except qt.QtStreamError:
            return {}

    def painter_version(self) -> str:
        s = self.settings()
        for key in ("versionAtLastSave", "versionAtCreation"):
            if f"{key}/major" in s:
                return f"{s[f'{key}/major']}.{s.get(f'{key}/minor', 0)}.{s.get(f'{key}/patch', 0)}"
        return ""

    def shelf_meta(self) -> dict:
        if ".alg_meta/preset.bin" not in self.h5:
            return {}
        try:
            return qt.read_map(self.raw(".alg_meta/preset.bin"))
        except qt.QtStreamError:
            return {}

    def thumbnail(self):
        """The shelf preview as an RGBA uint8 array, or None."""
        return decode_previews(self.shelf_meta().get("previews"))

    def presets(self):
        """Names of the layer-preset datasets (preset.bin first)."""
        names = [n for n in self.h5 if re.fullmatch(r"preset(_\d+)?\.bin", n)]
        return sorted(names, key=lambda n: (n != "preset.bin", n))

    # ------------------------------------------------------------------ resources
    def resource_key(self, url) -> str | None:
        """Map a resource URL from the HBO data to a dataset name inside this file."""
        url = hbo.text(url)
        m = re.search(r"[?&]version=([0-9a-fA-F]{16,64}(?:\.[A-Za-z0-9]+)?)", url)
        if not m:
            return None
        key = "resources/" + m.group(1)
        if key in self.h5:
            return key
        sha = m.group(1).split(".")[0]
        for cand in (f"resources/{sha}", f"resources/{sha}.image"):
            if cand in self.h5:
                return cand
        return None

    def image(self, url_or_key, max_size: int | None = None):
        """Decode an embedded .image resource -> float32 (H, W, C) array in 0..1, or None."""
        key = url_or_key if str(url_or_key).startswith("resources/") else self.resource_key(url_or_key)
        if not key or key not in self.h5:
            return None
        return decode_image(self.raw(key), max_size=max_size)


# ---------------------------------------------------------------------------------- images
_FORMATS = {"LUM8": (1, 8), "LUM16": (1, 16), "LUM32F": (1, 32), "RGB8": (3, 8), "RGB16": (3, 16),
            "RGBA8": (4, 8), "RGBA16": (4, 16), "RGBA32F": (4, 32), "LA8": (2, 8), "LA16": (2, 16)}


def image_header(data: bytes):
    meta, end = qt.read_map_with_end(data)
    return meta, end


def decode_image(data: bytes, max_size: int | None = None):
    """Painter .image resource: QVariantMap header, then per tile
    [u32 x0, y0, x1, y1][u64 size][size bytes, JPEG 2000 or raw], padded to 8 bytes."""
    from PIL import Image
    meta, p = image_header(data)
    w, h = int(meta.get("width", 0)), int(meta.get("height", 0))
    fmt = str(meta.get("format", "LUM8"))
    comps = _FORMATS.get(fmt, (1, 8))[0]
    if w <= 0 or h <= 0 or w > 16384 or h > 16384:
        raise SPFileError(f"bad image size {w}x{h}")
    out = np.zeros((h, w, comps), np.float32)
    compression = str(meta.get("compression", "jp2"))
    for _ in range(int(meta.get("tilesCount", 0))):
        if p + 24 > len(data):
            break
        x0, y0, x1, y1, size = struct.unpack_from("<IIIIQ", data, p)
        p += 24
        blob = data[p:p + size]
        p = (p + size + 7) & ~7
        tw, th = x1 - x0, y1 - y0
        if tw <= 0 or th <= 0 or x1 > w or y1 > h:
            continue
        if compression == "jp2":
            im = Image.open(io.BytesIO(blob))
            im.load()
            a = _pil_to_float(im)
        else:
            bits = _FORMATS.get(fmt, (1, 8))[1]
            dt = {8: np.uint8, 16: np.uint16, 32: np.float32}[bits]
            a = np.frombuffer(blob, dt, tw * th * comps).reshape(th, tw, comps).astype(np.float32)
            if bits != 32:
                a /= float(2 ** bits - 1)
        a = a[:th, :tw]
        if a.shape[2] != comps:
            a = _match_comps(a, comps)
        out[y0:y0 + a.shape[0], x0:x0 + a.shape[1]] = a
    if max_size and max(w, h) > max_size:
        step = int(np.ceil(max(w, h) / max_size))
        out = out[::step, ::step]
    return out


def _pil_to_float(im):
    if im.mode in ("I;16", "I;16B", "I;16L", "I"):
        a = np.asarray(im, np.float32) / 65535.0
        return a[..., None]
    if im.mode == "F":
        return np.asarray(im, np.float32)[..., None]
    if im.mode not in ("L", "LA", "RGB", "RGBA"):
        im = im.convert("RGBA")
    a = np.asarray(im, np.float32) / 255.0
    return a[..., None] if a.ndim == 2 else a


def _match_comps(a, comps):
    c = a.shape[2]
    if comps == 1:
        return a[..., :1]
    if c == 1:
        a = np.repeat(a, 3, axis=2)
        c = 3
    if comps == 4 and c == 3:
        return np.concatenate([a, np.ones_like(a[..., :1])], 2)
    if comps == 3:
        return a[..., :3]
    return a


def decode_previews(blob):
    """'previews' QByteArray from .alg_meta: QMap<QString, QByteArray> of encoded images."""
    if not blob:
        return None
    from PIL import Image
    try:
        r = qt.QReader(blob)
        for _ in range(min(r.u32(), 8)):
            r.qstring()
            img = r.qbytearray()
            if img:
                im = Image.open(io.BytesIO(img)).convert("RGBA")
                return np.asarray(im, np.uint8)
    except Exception:
        return None
    return None
