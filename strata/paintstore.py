"""Lazy authored raster channels. Read-only get() uses shared transparent defaults."""
from .channels import CHANNEL_DESCRIPTORS, BY_KEY


class PaintTextures(dict):
    def __init__(self, gpu, resolution, values=()):
        super().__init__(values)
        self.gpu, self.resolution = gpu, int(resolution)

    def __bool__(self):
        return True  # an empty authored paint layer is still a paint layer

    def __missing__(self, key):
        from .userchannels import descriptor
        channel = descriptor(key)
        texture = self.gpu.texture((self.resolution, self.resolution), channel.paint_components, dtype=channel.paint_dtype, purpose="paint/" + key)
        try:
            self.gpu.fill(texture, (0, 0, 0, 0))
        except Exception:
            texture.release()
            raise
        self[key] = texture
        return texture

    def get(self, key, default=None):
        if key in self:
            return super().get(key)
        from .userchannels import is_user
        return self.gpu.black if key in BY_KEY or is_user(key) else default

    def ensure(self, keys):
        added = []
        try:
            for key in keys:
                if key not in self:
                    self[key]
                    added.append(key)
        except Exception:
            for key in added:
                self.pop(key).release()
            raise
