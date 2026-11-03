"""View coordinates shared by input, cursor, display and brush evaluation (no UI/GL)."""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class ViewInput:
    rect: tuple
    framebuffer_scale: tuple = (1., 1.)

    @property
    def size(self):
        return tuple(max(int(v * s), 1) for v, s in zip(self.rect[2:], self.framebuffer_scale))

    def pixel(self, position):
        x, y, w, h = self.rect
        sx, sy = self.framebuffer_scale
        return np.array([(position[0] - x) * sx, (y + h - position[1]) * sy])


@dataclass(frozen=True)
class UVMapping:
    size: tuple
    zoom: float = 1.
    center: tuple = (.5, .5)
    rotation: float = 0.  # radians; view state, also retained by native stroke provenance

    def __post_init__(self):
        if (len(self.size) != 2 or min(self.size) <= 0 or not np.isfinite(self.size).all()
                or not np.isfinite(self.zoom) or self.zoom <= 0
                or len(self.center) != 2 or not np.isfinite(self.center).all()
                or not np.isfinite(self.rotation)):
            raise ValueError("Invalid UV view dimensions, zoom or center")
        object.__setattr__(self, "size", tuple(self.size))
        object.__setattr__(self, "center", tuple(self.center))

    @property
    def scale(self):
        w, h = self.size
        aspect, base = w / h, 1.08 / self.zoom
        return np.array((base * aspect, base) if aspect >= 1 else (base, base / aspect))

    @property
    def units_per_pixel(self):
        return float(self.scale[0] / self.size[0])

    def uv(self, pixel):
        return self.uv_delta(np.asarray(pixel) - np.asarray(self.size) * .5) + self.center

    def pixel(self, uv):
        return self.pixel_delta(np.asarray(uv) - self.center) + np.asarray(self.size) * .5

    @property
    def axes(self):
        c, s = np.cos(self.rotation), np.sin(self.rotation)
        return np.array([[c, -s], [s, c]])

    def uv_delta(self, pixels):
        return (np.asarray(pixels) * self.scale / self.size) @ self.axes.T

    def pixel_delta(self, uv):
        return (np.asarray(uv) @ self.axes) / self.scale * self.size

    def matrix(self):
        matrix = np.eye(3)
        matrix[:2, :2] = np.diag(2 / self.scale) @ self.axes.T
        matrix[:2, 2] = -matrix[:2, :2] @ self.center
        return matrix.astype(np.float32)


def uv_triangle(mesh, triangles, uv, single_tile=True):
    """First containing triangle in the active set. Overlaps share texture pixels.

    Degenerate triangles and empty/outside-tile positions are not paint targets.
    Lookup supplies size-space provenance, not a second raster paint pipeline.
    """
    uv = np.asarray(uv, float)
    if uv.shape != (2,) or not np.isfinite(uv).all() or np.any(uv < 0) or (single_tile and np.any(uv > 1)):
        return None
    ids = np.asarray(triangles, np.int64)
    pts = mesh.uvs[mesh.indices[ids]]
    a, b = pts[:, 1] - pts[:, 0], pts[:, 2] - pts[:, 0]
    delta = uv - pts[:, 0]
    det = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
    safe = np.where(abs(det) > 1e-12, det, 1)
    u = (delta[:, 0] * b[:, 1] - delta[:, 1] * b[:, 0]) / safe
    v = (a[:, 0] * delta[:, 1] - a[:, 1] * delta[:, 0]) / safe
    found = np.flatnonzero((abs(det) > 1e-12) & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7))
    return int(ids[found[0]]) if len(found) else None
