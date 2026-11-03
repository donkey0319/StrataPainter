"""Owned tile texture residency with lossless CPU backing and explicit GL-thread leases."""
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import zlib
import numpy as np

from .tiles import TileAddress

_DTYPES = {"f1": np.uint8, "f2": np.float16, "f4": np.float32}


@dataclass
class _Page:
    textures: dict = field(default_factory=dict)
    saved: dict = field(default_factory=dict)
    pins: int = 0
    resident: bool = False


class TileLease:
    def __init__(self, store, key, page):
        self._store, self.key, self._page = store, key, page
        self._active = True

    def _check(self):
        if not self._active:
            raise RuntimeError("Tile lease has expired")

    def texture(self, name, size, components, dtype="f2"):
        self._check()
        if not isinstance(name, str) or not name:
            raise ValueError("A tile texture needs a stable owner/channel name")
        if (dtype not in _DTYPES or type(components) is not int or not 1 <= components <= 4
                or len(size) != 2 or any(type(n) is not int or n < 1 or n > 32768 for n in size)):
            raise ValueError("Invalid tile texture specification")
        current = self._page.textures.get(name)
        if current is not None:
            if current.size != tuple(size) or current.components != components or current.dtype != dtype:
                raise ValueError("Tile texture specification changed; stage a resolution change first")
            return current
        required = int(np.prod(size)) * components * np.dtype(_DTYPES[dtype]).itemsize
        self._store._make_room(required)
        texture = self._store.gpu.texture(tuple(size), components, dtype=dtype, purpose="tile/" + name)
        try:
            self._store.gpu.fill(texture, (0, 0, 0, 0))
        except Exception:
            texture.release()
            raise
        self._page.textures[name] = texture
        return texture

    def get(self, name):
        self._check()
        return self._page.textures.get(name)

    def items(self):
        self._check()
        return tuple(self._page.textures.items())


class TileStore:
    """One document cache keyed by (material set pid, address).

    Leased pages cannot be evicted. Released pages retain every texture byte in
    compressed CPU backing before their GL objects are destroyed. No callback
    creates or releases GPU objects from a worker thread. Callers must not retain
    texture references after leaving a lease.
    """
    def __init__(self, gpu, resident_bytes, forget=None):
        if type(resident_bytes) is not int or resident_bytes <= 0:
            raise ValueError("Tile residency budget must be a positive integer")
        self.gpu, self.limit = gpu, resident_bytes
        self.pages, self.lru = {}, OrderedDict()
        self.forget = forget or (lambda textures: None)
        self.closed = False
        self.evictions = 0

    @staticmethod
    def _bytes(texture):
        return int(np.prod(texture.size)) * texture.components * np.dtype(_DTYPES[texture.dtype]).itemsize

    @staticmethod
    def _decode(record):
        expected = int(np.prod(record["size"])) * record["components"] * np.dtype(_DTYPES[record["dtype"]]).itemsize
        decoder = zlib.decompressobj()
        try:
            content = decoder.decompress(record["content"], expected + 1)
        except zlib.error as error:
            raise ValueError("Invalid tile backing data") from error
        if len(content) != expected or not decoder.eof or decoder.unused_data:
            raise ValueError("Invalid tile backing data")
        return content

    @property
    def resident_bytes(self):
        return sum(self._bytes(texture) for page in self.pages.values() for texture in page.textures.values())

    def _evict(self, key):
        page = self.pages[key]
        if page.pins or not page.resident:
            raise RuntimeError("A leased or nonresident tile cannot be evicted")
        saved = self._capture(page)
        self.forget(list(page.textures.values()))
        for texture in page.textures.values():
            texture.release()
        page.saved, page.textures, page.resident = saved, {}, False
        self.lru.pop(key, None)
        self.evictions += 1

    def _capture(self, page):
        saved = {}
        # Compress the whole page before releasing any owned GL texture.
        for name, texture in page.textures.items():
            values = self.gpu.read(texture)
            if texture.dtype == "f1":
                values = np.clip(values, 0, 1) * 255 + .5
            content = np.ascontiguousarray(values, _DTYPES[texture.dtype]).tobytes()
            saved[name] = {"size": texture.size, "components": texture.components, "dtype": texture.dtype,
                           "content": zlib.compress(content)}
        return saved

    def _make_room(self, required):
        while (self.resident_bytes + required > self.limit or
               self.gpu.memory.live_bytes + required > self.gpu.memory.limit_bytes):
            candidate = next((key for key in self.lru if self.pages[key].resident and not self.pages[key].pins), None)
            if candidate is None:
                raise MemoryError("Tile residency budget exhausted; release active tile leases or increase the budget")
            self._evict(candidate)

    def _restore(self, key, page):
        required = sum(int(np.prod(value["size"])) * value["components"] * np.dtype(_DTYPES[value["dtype"]]).itemsize
                       for value in page.saved.values())
        self._make_room(required)
        staged = {}
        try:
            for name, record in page.saved.items():
                content = self._decode(record)
                texture = self.gpu.texture(record["size"], record["components"], dtype=record["dtype"], purpose="tile/" + name)
                staged[name] = texture
                texture.write(content)
        except Exception:
            for texture in staged.values():
                texture.release()
            raise
        page.textures, page.resident = staged, True

    @contextmanager
    def lease(self, set_pid, address=TileAddress()):
        if self.closed:
            raise RuntimeError("Tile store is closed")
        if not isinstance(set_pid, str) or not set_pid or not isinstance(address, TileAddress):
            raise ValueError("Tile leases require a material-set identity and TileAddress")
        key = (set_pid, address)
        page = self.pages.setdefault(key, _Page())
        if not page.resident:
            self._restore(key, page)
        page.pins += 1
        self.lru.pop(key, None)
        self.lru[key] = None
        lease = TileLease(self, key, page)
        try:
            yield lease
        finally:
            lease._active = False
            page.pins -= 1
            self.lru.move_to_end(key)

    def evict(self, set_pid, address):
        self._evict((set_pid, address))

    def capture(self, set_pid, address, textures):
        """Capture borrowed source textures directly into owned CPU backing."""
        if self.closed or not isinstance(set_pid, str) or not set_pid or not isinstance(address, TileAddress):
            raise ValueError("Invalid tile backing capture")
        key = (set_pid, address)
        if key in self.pages:
            raise ValueError("Tile backing capture requires a new page")
        saved = self._capture(_Page(textures=dict(textures)))
        self.pages[key] = _Page(saved=saved)

    def discard(self, set_pid, address):
        """Drop disposable data, including backing; callers must release its leases first."""
        key = (set_pid, address)
        page = self.pages.get(key)
        if page is None:
            return
        if page.pins:
            raise RuntimeError("Release tile leases before discarding their page")
        self.forget(list(page.textures.values()))
        for texture in page.textures.values():
            texture.release()
        del self.pages[key]
        self.lru.pop(key, None)

    def snapshot(self):
        """Return metadata/NPZ arrays without eviction or changing live texture objects."""
        if self.closed or any(page.pins for page in self.pages.values()):
            raise RuntimeError("Release tile leases before taking a backing snapshot")
        pages, arrays = [], {}
        for index, ((set_pid, address), page) in enumerate(self.pages.items()):
            saved = self._capture(page) if page.resident else page.saved
            textures = []
            for channel, (name, record) in enumerate(saved.items()):
                member = f"tile_{index}_{channel}"
                content = record["content"]
                arrays[member] = np.frombuffer(content, np.uint8).copy()
                textures.append({"name": name, "size": list(record["size"]), "components": record["components"],
                                 "dtype": record["dtype"], "array": member, "sha256": hashlib.sha256(content).hexdigest()})
            pages.append({"set_pid": set_pid, "address": address.to_list(), "textures": textures})
        return {"version": 1, "pages": pages}, arrays

    @classmethod
    def from_snapshot(cls, gpu, resident_bytes, meta, arrays, forget=None, max_pages=256):
        """Validate CPU backing before creating any GL objects; leases restore lazily."""
        if (not isinstance(meta, dict) or type(meta.get("version")) is not int or meta["version"] != 1
                or not isinstance(meta.get("pages"), list) or len(meta["pages"]) > max_pages):
            raise ValueError("Unsupported or excessive tile backing snapshot")
        result = cls(gpu, resident_bytes, forget)
        members = set()
        for record in meta["pages"]:
            if (not isinstance(record, dict) or not isinstance(record.get("set_pid"), str) or not record["set_pid"]
                    or not isinstance(record.get("address"), list) or len(record["address"]) != 2
                    or not isinstance(record.get("textures"), list)):
                raise ValueError("Invalid material/tile backing identity")
            key = (record["set_pid"], TileAddress(*record["address"]))
            if key in result.pages:
                raise ValueError("Duplicate material/tile backing identity")
            saved = {}
            for texture in record["textures"]:
                if not isinstance(texture, dict):
                    raise ValueError("Invalid tile backing texture")
                name, size = texture.get("name"), texture.get("size")
                components, dtype, member = texture.get("components"), texture.get("dtype"), texture.get("array")
                if (not isinstance(name, str) or not name or name in saved or not isinstance(size, list)
                        or len(size) != 2 or any(type(n) is not int or not 1 <= n <= 32768 for n in size)
                        or type(components) is not int or not 1 <= components <= 4 or not isinstance(dtype, str) or dtype not in _DTYPES
                        or not isinstance(member, str) or member in members or member not in arrays):
                    raise ValueError("Invalid or duplicate tile backing texture")
                values = arrays[member]
                if not isinstance(values, np.ndarray) or values.dtype != np.uint8 or values.ndim != 1:
                    raise ValueError("Invalid tile backing array")
                content = values.tobytes()
                if hashlib.sha256(content).hexdigest() != texture.get("sha256"):
                    raise ValueError("Tile backing checksum mismatch")
                saved[name] = {"size": tuple(size), "components": components, "dtype": dtype, "content": content}
                cls._decode(saved[name])
                members.add(member)
            result.pages[key] = _Page(saved=saved)
        return result

    def close(self):
        if any(page.pins for page in self.pages.values()):
            raise RuntimeError("Release tile leases before closing their store")
        for page in self.pages.values():
            self.forget(list(page.textures.values()))
            for texture in page.textures.values():
                texture.release()
        self.pages.clear()
        self.lru.clear()
        self.closed = True
