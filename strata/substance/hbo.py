"""Decoder for Substance 3D Painter "HBO" object streams.

Painter stores its document, layer stacks and settings as HBO binary object graphs inside the
HDF5 container of .spp / .spsm / .spmsk files. Two encodings exist:

  inline   (header version_check == 0, Painter 8.1 - 10): every object/field is tagged inline
  registry (header version_check == 1, Painter 11+):      type definitions are declared once,
                                                          objects then follow their definition

Both decode to the same plain-Python tree:

  Obj   -> HObj(type: str, fields: dict[str, value])   (None for a null object)
  array -> list
  string-> bytes (may be UTF-8 text or a binary QVariant; use text() to read it)
  prim  -> Prim(code, raw bytes)                      (use as_float()/as_int()/... to interpret)

Format knowledge comes from Universal-Painter-Files (MIT, (c) 2026 YUCP Studio,
https://github.com/Yeusepe/Universal-Painter-Files). This is an independent, read-only
re-implementation for Strata.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = 0x1B7C2FDD
MAX_DEPTH = 160
MAX_ITEMS = 2_000_000

# primitive type code -> byte size, per encoding
INLINE_SIZES = {1: 4, 2: 8, 3: 12, 4: 16, 5: 4, 6: 8, 7: 12, 8: 16,
                9: 8, 10: 1, 11: 4, 12: 8, 13: 36, 14: 64, 15: 8, 16: 32, 21: 8}
REGISTRY_SIZES = {1: 4, 2: 8, 3: 12, 4: 16, 5: 4, 6: 8, 7: 12, 8: 16,
                  9: 4, 10: 1, 11: 4, 12: 8, 13: 36, 14: 64, 15: 8, 16: 32, 21: 8, 22: 16}

T_STRING, T_ARR_TYPED, T_OBJ, T_ARR, T_OBJ2 = 0x10, 0x11, 0x12, 0x13, 0x14


class HBOError(ValueError):
    pass


@dataclass
class Prim:
    code: int
    raw: bytes

    # Interpretation (verified against real files): codes 1-4 float32 x1..4, 5-8 int32 x1..4,
    # 9 int (8 bytes inline / 4 bytes registry), 10 bool, 11 uint32 (bitmasks), 12 uint64 (uids),
    # 13 float 3x3, 14 float 4x4, 15/21 int64.
    def floats(self):
        n = len(self.raw) // 4
        return list(struct.unpack(f"<{n}f", self.raw[:n * 4])) if n else []

    def ints(self):
        n = len(self.raw) // 4
        return list(struct.unpack(f"<{n}i", self.raw[:n * 4])) if n else []

    def value(self):
        c, r = self.code, self.raw
        if c == 10:
            return bool(r[0]) if r else False
        if c in (1, 2, 3, 4, 13, 14, 16):
            f = self.floats()
            return f[0] if len(f) == 1 else f
        if c in (5, 6, 7, 8):
            v = self.ints()
            return v[0] if len(v) == 1 else v
        if c == 11:
            return struct.unpack("<I", r[:4])[0]
        if c == 9:
            return struct.unpack("<q", r)[0] if len(r) == 8 else struct.unpack("<i", r)[0]
        if len(r) == 8:
            return struct.unpack("<q", r)[0]
        return r

    def __repr__(self):
        v = self.value()
        return f"P{self.code}:{v!r}" if not isinstance(v, bytes) else f"P{self.code}:{r_hex(v)}"


def r_hex(b: bytes) -> str:
    return b[:16].hex() + ("…" if len(b) > 16 else "")


@dataclass
class HObj:
    type: str
    fields: dict = field(default_factory=dict)

    def get(self, key, default=None):
        return self.fields.get(key, default)

    def __getitem__(self, key):
        return self.fields[key]

    def __contains__(self, key):
        return key in self.fields


def text(v, default="") -> str:
    """Read a string field. Painter writes plain UTF-8 for names and URLs."""
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).decode("utf-8", "replace")
    if isinstance(v, str):
        return v
    return default


def val(v, default=None):
    """Unwrap a primitive to a python value."""
    if isinstance(v, Prim):
        return v.value()
    return default if v is None else v


# ---------------------------------------------------------------------------------- reader
class _Reader:
    def __init__(self, data: bytes, pos: int):
        self.d, self.p = memoryview(data), pos

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]; self.p += 2; return v

    def u32(self):
        if self.p + 4 > len(self.d):
            raise HBOError("unexpected end of stream")
        v = struct.unpack_from("<I", self.d, self.p)[0]; self.p += 4; return v

    def take(self, n):
        if n < 0 or self.p + n > len(self.d):
            raise HBOError("unexpected end of stream")
        b = bytes(self.d[self.p:self.p + n]); self.p += n; return b

    def name(self):
        return self.take(self.u32()).decode("utf-8", "replace")

    def count(self):
        c = self.u32()
        if c > MAX_ITEMS or c > len(self.d) - self.p + 1:
            raise HBOError(f"implausible element count {c}")
        return c


def _decode_inline(data: bytes):
    r = _Reader(data, 12)

    def obj(depth):
        if depth > MAX_DEPTH:
            raise HBOError("nesting too deep")
        r.u8(); r.u32()                       # tag byte + end offset
        nm = r.name()
        fc = r.u16()
        o = HObj(nm)
        for _ in range(fc):
            fn = r.name()
            o.fields[fn] = value(depth)
        return o

    def prim(tag):
        sz = INLINE_SIZES.get(tag)
        if sz is None:
            raise HBOError(f"unknown inline primitive code {tag}")
        return Prim(tag, r.take(sz))

    def obj_or_null(depth):
        if r.d[r.p] == 0xFF:
            r.p += 1
            return None
        return obj(depth + 1)

    def value(depth):
        tag = r.u8()
        if tag == T_STRING:
            return r.take(r.u32())
        if tag in (T_OBJ, T_OBJ2):
            return obj_or_null(depth)
        if tag in (T_ARR, T_ARR_TYPED):
            r.u32()
            out = []
            for _ in range(r.count()):
                e = r.u8()
                if e in (T_OBJ, T_OBJ2):
                    out.append(obj_or_null(depth))
                elif e == T_STRING:
                    out.append(r.take(r.u32()))
                else:
                    out.append(prim(e))
            return out
        if tag == 0x00:
            return None
        return prim(tag)

    if r.u8() != T_OBJ:
        raise HBOError("inline stream has no root object")
    return obj(0)


def _decode_registry(data: bytes):
    r = _Reader(data, 12)
    r.u32()                                   # root tag
    type_count = r.u32()
    registry: list[tuple[str, list]] = []

    def typedef():
        idx = r.u32()
        if idx != 0xFFFFFFFF:
            if idx >= len(registry):
                raise HBOError(f"type index {idx} out of range")
            return registry[idx]
        nm = r.name()
        members = [(r.name(), r.u32()) for _ in range(r.u32())]
        td = (nm, members)
        registry.append(td)
        return td

    # leading table of declared types (all prefixed with 0xFFFFFFFF)
    for _ in range(type_count):
        if struct.unpack_from("<I", r.d, r.p)[0] != 0xFFFFFFFF:
            break
        typedef()

    def obj_with(td, depth):
        if depth > MAX_DEPTH:
            raise HBOError("nesting too deep")
        o = HObj(td[0])
        for mn, mt in td[1]:
            o.fields[mn] = value(mt, depth)
        return o

    def obj(depth):
        if r.u32() == 0:
            return None
        return obj_with(typedef(), depth + 1)

    def value(code, depth):
        if code in (T_OBJ, T_OBJ2):
            return obj(depth)
        if code == T_ARR:
            return [obj(depth) for _ in range(r.count())]
        if code == T_ARR_TYPED:
            n = r.count()
            if not n:
                return []
            td = typedef()
            return [obj_with(td, depth + 1) for _ in range(n)]
        if code == T_STRING:
            return r.take(r.u32())
        sz = REGISTRY_SIZES.get(code)
        if sz is None:
            raise HBOError(f"unknown registry primitive code {code}")
        return Prim(code, r.take(sz))

    return obj(0)


def is_hbo(raw: bytes) -> bool:
    return len(raw) >= 12 and struct.unpack_from("<I", raw, 0)[0] == MAGIC


def decode(raw: bytes):
    """Decode an HBO stream -> (root HObj, encoding name, data_version)."""
    if not is_hbo(raw):
        raise HBOError("not an HBO stream")
    _, vc, dv = struct.unpack_from("<III", raw, 0)
    if vc == 0:
        return _decode_inline(raw), "inline", dv
    if vc == 1:
        return _decode_registry(raw), "registry", dv
    raise HBOError(f"unknown HBO encoding {vc}")


def walk(node, fn, path=""):
    """Depth-first visit of every HObj in a decoded tree: fn(obj, path)."""
    if isinstance(node, HObj):
        fn(node, path)
        for k, v in node.fields.items():
            walk(v, fn, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, fn, f"{path}[{i}]")
