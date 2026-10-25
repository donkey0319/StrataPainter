"""Image reading/writing for textures, alphas, environments and exports.

Arrays are float32 (H, W, C), row 0 = top (file order), values 0-1 for LDR data.
Pillow handles the common 8-bit formats; 16-bit colour PNG, 16/32-bit TIFF, OpenEXR,
Radiance HDR and PFM are written (and HDR/EXR read) by the small codecs below.
"""
from __future__ import annotations

import os
import struct
import zlib

import numpy as np

LDR_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp", ".gif", ".psd"}
HDR_EXTS = {".hdr", ".exr", ".pfm"}

# export formats -> supported bit depths ("8d" = 8 bit with dithering, "32f" float)
FORMATS = {
    "png": ["8", "8d", "16"],
    "tga": ["8", "8d"],
    "tiff": ["8", "8d", "16", "32f"],
    "jpeg": ["8", "8d"],
    "bmp": ["8", "8d"],
    "webp": ["8", "8d"],
    "exr": ["16f", "32f"],
    "hdr": ["32f"],
    "pfm": ["32f"],
}
EXT = {"png": ".png", "tga": ".tga", "tiff": ".tif", "jpeg": ".jpg", "bmp": ".bmp", "webp": ".webp",
       "exr": ".exr", "hdr": ".hdr", "pfm": ".pfm"}


# ---------------------------------------------------------------------------------- reading
def read_image(path: str) -> np.ndarray:
    a = _read_image(path)
    return a[..., None] if a.ndim == 2 else a


def _read_image(path: str) -> np.ndarray:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".hdr":
        return read_hdr(path)
    if ext == ".exr":
        return read_exr(path)
    if ext == ".pfm":
        return read_pfm(path)
    if ext in (".tif", ".tiff"):
        try:
            return _read_tiff(path)
        except Exception:
            pass
    from PIL import Image
    im = Image.open(path)
    if im.mode in ("I;16", "I;16B", "I;16L", "I"):
        a = np.asarray(im, np.float32) / (65535.0 if im.mode.startswith("I;16") else max(np.asarray(im).max(), 1))
        return a[..., None]
    if im.mode == "F":
        return np.asarray(im, np.float32)[..., None]
    if im.mode not in ("L", "LA", "RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    return np.asarray(im, np.float32) / 255.0


def _read_tiff(path: str) -> np.ndarray:
    """Uncompressed, chunky, little-endian TIFF (8/16-bit uint or 32-bit float)."""
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] != b"II*\0":
        raise ValueError("not a little-endian TIFF")
    off = struct.unpack_from("<I", d, 4)[0]
    n = struct.unpack_from("<H", d, off)[0]
    tags = {}
    for i in range(n):
        tag, typ, count = struct.unpack_from("<HHI", d, off + 2 + i * 12)
        vo = off + 2 + i * 12 + 8
        size = {3: 2, 4: 4}.get(typ, 4) * count
        src = vo if size <= 4 else struct.unpack_from("<I", d, vo)[0]
        fmt = {3: "H", 4: "I"}.get(typ, "I")
        tags[tag] = struct.unpack_from(f"<{count}{fmt}", d, src)
    if tags.get(259, (1,))[0] != 1 or tags.get(284, (1,))[0] != 1:
        raise ValueError("compressed or planar TIFF")
    w, h, c = tags[256][0], tags[257][0], tags.get(277, (1,))[0]
    bps = tags[258][0]
    sfmt = tags.get(339, (1,))[0]
    dt = {(8, 1): "u1", (16, 1): "<u2", (32, 3): "<f4"}[(bps, sfmt)]
    raw = b"".join(d[o:o + b] for o, b in zip(tags[273], tags[279]))
    a = np.frombuffer(raw, dt, w * h * c).reshape(h, w, c).astype(np.float32)
    if sfmt == 1:
        a /= float((1 << bps) - 1)
    return a


def read_hdr(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        data = f.read()
    pos = 0
    while True:                           # header lines until a blank line
        end = data.index(b"\n", pos)
        line = data[pos:end].strip()
        pos = end + 1
        if not line:
            break
    end = data.index(b"\n", pos)
    res = data[pos:end].split()
    pos = end + 1
    h, w = int(res[1]), int(res[3])
    flip_y = res[0] == b"+Y"
    out = np.zeros((h, w, 4), np.uint8)
    buf = np.frombuffer(data, np.uint8)
    for y in range(h):
        if w >= 8 and w < 32768 and buf[pos] == 2 and buf[pos + 1] == 2 and (buf[pos + 2] & 0x80) == 0:
            pos += 4
            for ch in range(4):              # new-style RLE: one channel at a time
                x = 0
                while x < w:
                    c = int(buf[pos]); pos += 1
                    if c > 128:
                        c -= 128
                        out[y, x:x + c, ch] = buf[pos]; pos += 1
                    else:
                        out[y, x:x + c, ch] = buf[pos:pos + c]; pos += c
                    x += c
        else:
            out[y] = buf[pos:pos + w * 4].reshape(w, 4)
            pos += w * 4
    e = out[..., 3].astype(np.int32)
    scale = np.where(e > 0, np.ldexp(1.0, e - 136), 0.0).astype(np.float32)
    rgb = out[..., :3].astype(np.float32) * scale[..., None]
    return rgb[::-1] if flip_y else rgb


def read_pfm(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        kind = f.readline().strip()
        w, h = map(int, f.readline().split())
        scale = float(f.readline())
        n = 3 if kind == b"PF" else 1
        a = np.frombuffer(f.read(), "<f4" if scale < 0 else ">f4", w * h * n).reshape(h, w, n)
    return a[::-1].astype(np.float32)


def read_exr(path: str) -> np.ndarray:
    """Scanline OpenEXR with no / ZIPS / ZIP compression, half, float or uint channels."""
    with open(path, "rb") as f:
        data = f.read()
    if struct.unpack_from("<I", data, 0)[0] != 20000630:
        raise ValueError("not an OpenEXR file")
    pos = 8
    attrs = {}
    while data[pos] != 0:
        e = data.index(b"\0", pos); name = data[pos:e].decode(); pos = e + 1
        e = data.index(b"\0", pos); typ = data[pos:e].decode(); pos = e + 1
        size = struct.unpack_from("<i", data, pos)[0]; pos += 4
        attrs[name] = (typ, data[pos:pos + size]); pos += size
    pos += 1
    chl = attrs["channels"][1]
    chans, p = [], 0
    while chl[p] != 0:
        e = chl.index(b"\0", p); nm = chl[p:e].decode(); p = e + 1
        ptype = struct.unpack_from("<i", chl, p)[0]; p += 16
        chans.append((nm, ptype))
    comp = attrs["compression"][1][0]
    x0, y0, x1, y1 = struct.unpack("<4i", attrs["dataWindow"][1])
    w, h = x1 - x0 + 1, y1 - y0 + 1
    lines = {0: 1, 2: 1, 3: 16}.get(comp)
    if lines is None:
        raise ValueError(f"unsupported EXR compression {comp}")
    nblocks = (h + lines - 1) // lines
    offsets = struct.unpack_from(f"<{nblocks}Q", data, pos)
    sizes = {0: 4, 1: 2, 2: 4}
    out = {nm: np.zeros((h, w), np.float32) for nm, _ in chans}
    for off in offsets:
        y = struct.unpack_from("<i", data, off)[0] - y0
        n = struct.unpack_from("<i", data, off + 4)[0]
        raw = data[off + 8:off + 8 + n]
        nl = min(lines, h - y)
        expect = sum(sizes[t] for _, t in chans) * w * nl
        if comp != 0 and len(raw) < expect:
            b = np.frombuffer(zlib.decompress(raw), np.uint8).astype(np.int32)
            b = np.cumsum(np.concatenate([b[:1], b[1:] - 128])) & 0xFF   # undo predictor
            half = (len(b) + 1) // 2
            t = np.empty(len(b), np.uint8)
            t[0::2] = b[:half]; t[1::2] = b[half:]
            raw = t.tobytes()
        q = 0
        for line in range(nl):
            for nm, t in chans:
                nb = sizes[t] * w
                dt = {0: "<u4", 1: "<f2", 2: "<f4"}[t]
                out[nm][y + line] = np.frombuffer(raw, dt, w, q).astype(np.float32)
                q += nb
    names = [n for n, _ in chans]
    order = [c for c in ("R", "G", "B", "A") if c in names] or names
    return np.stack([out[c] for c in order], -1)


# ---------------------------------------------------------------------------------- writing
def _quantize(a: np.ndarray, bits: int, dither: bool) -> np.ndarray:
    maxv = (1 << bits) - 1
    x = np.clip(a, 0, 1) * maxv
    if dither:
        rng = np.random.default_rng(1234)
        x = x + rng.random(x.shape, np.float32) - 0.5
    x = np.clip(np.round(x), 0, maxv)
    return x.astype(np.uint8 if bits == 8 else np.uint16)


def write_image(path: str, img: np.ndarray, depth: str = "8") -> str:
    """Write img (H, W) or (H, W, C), C in 1-4, row 0 = top. depth from FORMATS. Returns path."""
    img = np.asarray(img, np.float32)
    if img.ndim == 2:
        img = img[..., None]
    ext = os.path.splitext(path)[1].lower()
    dither = depth.endswith("d")
    bits = int(depth.rstrip("df") or 8)
    if ext == ".exr":
        _write_exr(path, img, half=(depth == "16f"))
    elif ext == ".hdr":
        _write_hdr(path, img)
    elif ext == ".pfm":
        _write_pfm(path, img)
    elif ext in (".tif", ".tiff") and depth in ("16", "32f"):
        _write_tiff(path, img, depth)
    elif ext == ".png" and bits == 16:
        _write_png16(path, _quantize(img, 16, False))
    else:
        from PIL import Image
        q = _quantize(img, 8, dither)
        c = q.shape[2]
        if ext in (".jpg", ".jpeg") and c in (2, 4):
            q, c = q[..., :max(c - 1, 1)], c - 1
        if c == 2:
            q = np.dstack([q[..., 0]] * 3 + [q[..., 1]]); c = 4
        mode = {1: "L", 3: "RGB", 4: "RGBA"}[c]
        im = Image.fromarray(q[..., 0] if c == 1 else q, mode)
        if ext in (".jpg", ".jpeg"):
            im.save(path, quality=95)
        else:
            im.save(path)
    return path


def _write_png16(path, q: np.ndarray):
    h, w, c = q.shape
    color = {1: 0, 2: 4, 3: 2, 4: 6}[c]
    raw = b"".join(b"\0" + q[y].astype(">u2").tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 16, color, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def _write_tiff(path, img: np.ndarray, depth: str):
    h, w, c = img.shape
    if depth == "16":
        data, bps, fmt = _quantize(img, 16, False).astype("<u2"), 16, 1
    else:
        data, bps, fmt = img.astype("<f4"), 32, 3
    body = data.tobytes()
    entries = []
    off_data = 8
    n_entries = 12 if c in (2, 4) else 11
    ifd_off = off_data + len(body)
    extra_off = ifd_off + 2 + n_entries * 12 + 4
    bps_val = struct.pack("<" + "H" * c, *([bps] * c))
    fmt_val = struct.pack("<" + "H" * c, *([fmt] * c))

    def ent(tag, typ, count, value):
        entries.append((tag, typ, count, value))
    extra = b""

    def arr(b):
        nonlocal extra
        o = extra_off + len(extra)
        extra += b + (b"\0" if len(b) % 2 else b"")
        return o
    ent(256, 4, 1, w)
    ent(257, 4, 1, h)
    ent(258, 3, c, arr(bps_val) if c > 2 else struct.unpack("<I", bps_val.ljust(4, b"\0"))[0])
    ent(259, 3, 1, 1)
    ent(262, 3, 1, 2 if c >= 3 else 1)
    ent(273, 4, 1, off_data)
    ent(277, 3, 1, c)
    ent(278, 4, 1, h)
    ent(279, 4, 1, len(body))
    ent(284, 3, 1, 1)
    if c in (2, 4):
        ent(338, 3, 1, 2)
    ent(339, 3, c, arr(fmt_val) if c > 2 else struct.unpack("<I", fmt_val.ljust(4, b"\0"))[0])
    entries.sort()
    with open(path, "wb") as f:
        f.write(b"II*\0" + struct.pack("<I", ifd_off))
        f.write(body)
        f.write(struct.pack("<H", len(entries)))
        for tag, typ, count, value in entries:
            if typ == 3 and count == 1:
                f.write(struct.pack("<HHIHH", tag, typ, count, value, 0))
            else:
                f.write(struct.pack("<HHII", tag, typ, count, value))
        f.write(struct.pack("<I", 0))
        f.write(extra)


def _write_exr(path, img: np.ndarray, half=True):
    h, w, c = img.shape
    names = {1: ["Y"], 2: ["Y", "A"], 3: ["R", "G", "B"], 4: ["R", "G", "B", "A"]}[c]
    order = sorted(range(c), key=lambda i: names[i])          # channels stored alphabetically
    ptype, dt = (1, "<f2") if half else (2, "<f4")

    def attr(name, typ, value):
        return name.encode() + b"\0" + typ.encode() + b"\0" + struct.pack("<i", len(value)) + value
    chl = b"".join(names[i].encode() + b"\0" + struct.pack("<iB3xii", ptype, 0, 1, 1) for i in order) + b"\0"
    header = (struct.pack("<ii", 20000630, 2)
              + attr("channels", "chlist", chl)
              + attr("compression", "compression", b"\0")
              + attr("dataWindow", "box2i", struct.pack("<4i", 0, 0, w - 1, h - 1))
              + attr("displayWindow", "box2i", struct.pack("<4i", 0, 0, w - 1, h - 1))
              + attr("lineOrder", "lineOrder", b"\0")
              + attr("pixelAspectRatio", "float", struct.pack("<f", 1.0))
              + attr("screenWindowCenter", "v2f", struct.pack("<ff", 0.0, 0.0))
              + attr("screenWindowWidth", "float", struct.pack("<f", 1.0))
              + b"\0")
    line_bytes = w * c * (2 if half else 4)
    table_start = len(header)
    first = table_start + 8 * h
    offsets = struct.pack(f"<{h}Q", *[first + y * (8 + line_bytes) for y in range(h)])
    planar = img.astype(dt)
    with open(path, "wb") as f:
        f.write(header)
        f.write(offsets)
        for y in range(h):
            f.write(struct.pack("<ii", y, line_bytes))
            f.write(b"".join(planar[y, :, i].tobytes() for i in order))


def _write_hdr(path, img: np.ndarray):
    h, w, c = img.shape
    rgb = img[..., :3] if c >= 3 else np.repeat(img[..., :1], 3, axis=2)
    rgb = np.maximum(rgb, 0)
    m = rgb.max(axis=2)
    e = np.zeros_like(m, np.int32)
    mant, e = np.frexp(m)
    scale = np.where(m > 1e-32, mant * 256.0 / np.maximum(m, 1e-32), 0.0)
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = np.clip(rgb * scale[..., None], 0, 255).astype(np.uint8)
    out[..., 3] = np.where(m > 1e-32, e + 128, 0).astype(np.uint8)
    with open(path, "wb") as f:
        f.write(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n")
        f.write(f"-Y {h} +X {w}\n".encode())
        f.write(out.tobytes())


def _write_pfm(path, img: np.ndarray):
    h, w, c = img.shape
    kind = b"Pf" if c == 1 else b"PF"
    a = img[..., :1] if c == 1 else (img[..., :3] if c >= 3 else np.repeat(img[..., :1], 3, axis=2))
    with open(path, "wb") as f:
        f.write(kind + b"\n" + f"{w} {h}\n-1.0\n".encode())
        f.write(np.ascontiguousarray(a[::-1], "<f4").tobytes())
