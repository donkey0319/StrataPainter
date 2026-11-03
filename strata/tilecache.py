"""Disposable bounded cache of native-precision per-tile material outputs."""
from contextlib import contextmanager
from types import SimpleNamespace
from .tilestore import TileStore
from .tilepreview import TilePreview

COMP = ("color", "rmh", "normal", "emissive", "mask_preview")
BAKES = ("pos", "nrm", "curv", "ao", "cov", "thick", "id", "part", "tangent", "normal_hp", "height_hp", "projection")


class TileEvaluationCache:
    def __init__(self, material, resident_bytes=256 * 1024**2):
        self.material = material
        self.store = TileStore(material.engine.gpu, resident_bytes)
        self.key, self.ready, self.names = None, set(), {}
        self.evaluations = 0
        self.failures = {}
        self.resolution = None

    def close(self):
        self.store.close()

    @contextmanager
    def lease(self, address, resolution=None, refresh=True):
        m, e = self.material, self.material.engine
        res = m.res if resolution is None else resolution
        if type(res) is not int or not 1 <= res <= 8192 or address not in m.addresses:
            raise ValueError("Invalid material tile/resolution")
        # The thumbnail cache uses the same material/resource revision contract.
        revision = TilePreview.revision(self, "surface", res)
        if self.key is None or (refresh and revision != self.key):
            limit = self.store.limit
            self.store.close()
            self.store = TileStore(e.gpu, limit)
            self.key, self.ready, self.names = revision, set(), {}
            self.failures.clear()
            self.resolution = res
        res = self.resolution
        if address in self.failures:
            raise ValueError(self.failures[address])
        try:
            with self.store.lease(m.ts.pid, address) as page:
                if address not in self.ready:
                    names = []
                    with m.evaluate(address, resolution=res) as tile:
                        if e.layer is not None:
                            selected = next((layer for root in tile.layers for layer in root.walk() if layer.pid == e.layer.pid), None)
                            if selected is not None:
                                tile.comp.render_mask(selected)
                        for prefix, source, fields in (("comp", tile.comp, COMP), ("bake", tile.bakes, BAKES)):
                            for field in fields:
                                texture = getattr(source, field)
                                if texture is None:
                                    continue
                                name = prefix + "/" + field
                                target = page.texture(name, texture.size, texture.components, texture.dtype)
                                e.gpu.blit(texture, target)
                                names.append((prefix, field, texture.filter, texture.repeat_x, texture.repeat_y))
                        for field, texture in list(tile.comp.user_outputs.items()) + [("semantic"+str(i), t) for i,t in enumerate(tile.comp.semantic_textures)]:
                            target = page.texture("user/"+field, texture.size, texture.components, texture.dtype)
                            e.gpu.blit(texture,target)
                    self.names[address] = names
                    self.ready.add(address)
                    self.evaluations += 1
                for prefix, field, filtering, repeat_x, repeat_y in self.names[address]:
                    texture = page.get(prefix + "/" + field)
                    texture.filter, texture.repeat_x, texture.repeat_y = filtering, repeat_x, repeat_y
                comp = SimpleNamespace(**{field: page.get("comp/" + field) for field in COMP})
                comp.resources = e.resources
                comp.user_outputs = {key:page.get("user/"+key) for key in e.user_channels}
                comp.semantic_textures = [page.get("user/semantic"+str(i)) for i in range(2)] if page.get("user/semantic0") is not None else []
                bakes = SimpleNamespace(**{field: page.get("bake/" + field) for field in BAKES})
                yield SimpleNamespace(comp=comp, bakes=bakes, res=res, address=address, key=m.ts.key)
        except Exception as error:
            self.ready.discard(address)
            self.names.pop(address, None)
            self.store.discard(m.ts.pid, address)
            if isinstance(error, (ValueError, OSError)):
                self.failures[address] = "Tile resource unavailable: " + str(error) if isinstance(error, OSError) else str(error)
                if isinstance(error, OSError):
                    raise ValueError(self.failures[address]) from error
            raise
