"""Minimal reader for Qt QDataStream values (big-endian), as Painter writes them.

Painter stores several small datasets as a serialised QVariantMap: projectsettings.ini, the header
of every .image resource, resources.toc and the .alg_meta/preset.bin shelf metadata (which carries
the thumbnail). Only the QVariant types those files use are supported; anything else raises.
"""
from __future__ import annotations

import struct

# QMetaType ids (Qt 5)
_BOOL, _INT, _UINT, _LONGLONG, _ULONGLONG, _DOUBLE = 1, 2, 3, 4, 5, 6
_MAP, _LIST, _STRING, _STRINGLIST, _BYTEARRAY, _FLOAT = 8, 9, 10, 11, 12, 38


class QtStreamError(ValueError):
    pass


class QReader:
    def __init__(self, data: bytes, pos: int = 0):
        self.d, self.p = memoryview(data), pos

    def _unpack(self, fmt, n):
        if self.p + n > len(self.d):
            raise QtStreamError("unexpected end of Qt stream")
        v = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += n
        return v

    def u8(self):
        return self._unpack(">B", 1)

    def u32(self):
        return self._unpack(">I", 4)

    def i32(self):
        return self._unpack(">i", 4)

    def take(self, n):
        if n < 0 or self.p + n > len(self.d):
            raise QtStreamError("unexpected end of Qt stream")
        b = bytes(self.d[self.p:self.p + n])
        self.p += n
        return b

    def qstring(self):
        n = self.u32()
        if n == 0xFFFFFFFF:
            return None
        return self.take(n).decode("utf-16-be", "replace")

    def qbytearray(self):
        n = self.u32()
        if n == 0xFFFFFFFF:
            return None
        return self.take(n)

    def variant(self):
        t = self.u32()
        self.u8()                                   # is-null flag
        if t == _STRING:
            return self.qstring()
        if t == _BYTEARRAY:
            return self.qbytearray()
        if t == _INT:
            return self.i32()
        if t == _UINT:
            return self.u32()
        if t == _BOOL:
            return bool(self.u8())
        if t == _DOUBLE:
            return self._unpack(">d", 8)
        if t == _FLOAT:
            return self._unpack(">f", 4)
        if t == _LONGLONG:
            return self._unpack(">q", 8)
        if t == _ULONGLONG:
            return self._unpack(">Q", 8)
        if t == _MAP:
            return self.vmap()
        if t == _LIST:
            return [self.variant() for _ in range(self.u32())]
        if t == _STRINGLIST:
            return [self.qstring() for _ in range(self.u32())]
        raise QtStreamError(f"unsupported QVariant type {t}")

    def vmap(self) -> dict:
        n = self.u32()
        if n > 100000:
            raise QtStreamError("implausible map size")
        return {self.qstring(): self.variant() for _ in range(n)}


def read_map(data: bytes) -> dict:
    """Decode a QVariantMap that starts at offset 0."""
    return QReader(data).vmap()


def read_map_with_end(data: bytes):
    r = QReader(data)
    m = r.vmap()
    return m, r.p
