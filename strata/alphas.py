"""CPU-only procedural brush alpha definitions; re-exported by resources."""
import zlib
import numpy as np

BUILTIN_ALPHAS = ["Square", "Square Soft", "Diamond", "Star", "Ring", "Triangle", "Cross",
                  "Splatter", "Speckle", "Cloud", "Scratches", "Line", "Brush Bristles"]
ALPHA_RES = 256


def _grid(n=ALPHA_RES):
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    return (x + 0.5) / n * 2 - 1, (y + 0.5) / n * 2 - 1


def _smooth(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0, 1)
    return t * t * (3 - 2 * t)


def make_alpha(name: str, n: int = ALPHA_RES) -> np.ndarray:
    """Procedural alpha as float32 (n, n), 0-1, centred, row 0 = bottom."""
    x, y = _grid(n)
    r = np.hypot(x, y)
    a = np.arctan2(y, x)
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    if name == "Square":
        v = (np.maximum(abs(x), abs(y)) < 0.9).astype(np.float32)
    elif name == "Square Soft":
        v = 1 - _smooth(0.55, 0.95, np.maximum(abs(x), abs(y)))
    elif name == "Diamond":
        v = 1 - _smooth(0.8, 0.95, abs(x) + abs(y))
    elif name == "Star":
        k = 0.55 + 0.35 * np.cos(5 * a)
        v = 1 - _smooth(k - 0.04, k + 0.04, r)
    elif name == "Ring":
        v = 1 - _smooth(0.06, 0.12, abs(r - 0.7))
    elif name == "Triangle":
        d = np.maximum.reduce([-y - 0.5, 0.866 * x + 0.5 * y - 0.5, -0.866 * x + 0.5 * y - 0.5])
        v = 1 - _smooth(-0.04, 0.02, d)
    elif name == "Cross":
        v = 1 - _smooth(0.12, 0.2, np.minimum(abs(x), abs(y)) + _smooth(0.75, 0.95, np.maximum(abs(x), abs(y))))
    elif name in ("Splatter", "Speckle"):
        v = np.zeros_like(x)
        count, big = (40, 0.22) if name == "Splatter" else (160, 0.06)
        for _ in range(count):
            cr = rng.random() ** 0.7 * 0.8
            ca = rng.random() * 2 * np.pi
            cx, cy = cr * np.cos(ca), cr * np.sin(ca)
            rad = big * (0.25 + rng.random() * (1 - cr))
            v = np.maximum(v, 1 - _smooth(rad * 0.7, rad, np.hypot(x - cx, y - cy)))
    elif name == "Cloud":
        v = np.zeros_like(x)
        for octave in range(5):
            f = 2 ** octave * 2.0
            ph = rng.random(4) * 6.28
            v += (np.sin(x * f * 3.1 + ph[0]) * np.sin(y * f * 2.7 + ph[1])
                  + np.sin((x + y) * f * 1.9 + ph[2])) * 0.5 ** octave
        v = np.clip(v * 0.35 + 0.5, 0, 1) * (1 - _smooth(0.5, 1.0, r))
    elif name == "Scratches":
        v = np.zeros_like(x)
        for _ in range(14):
            ang = rng.random() * np.pi
            off = (rng.random() - 0.5) * 1.4
            d = abs(np.cos(ang) * y - np.sin(ang) * x - off)
            length = np.abs(np.sin(ang) * y + np.cos(ang) * x) < 0.3 + rng.random() * 0.6
            v = np.maximum(v, (1 - _smooth(0.0, 0.015 + rng.random() * 0.01, d)) * length)
    elif name == "Line":
        v = (1 - _smooth(0.05, 0.12, abs(y))) * (1 - _smooth(0.8, 0.95, abs(x)))
    elif name == "Brush Bristles":
        v = np.zeros_like(x)
        for _ in range(60):
            cx, cy = (rng.random(2) - 0.5) * 1.5
            v = np.maximum(v, (1 - _smooth(0.02, 0.06, np.hypot((x - cx) * 0.35, y - cy))) * (0.5 + rng.random() * 0.5))
        v *= 1 - _smooth(0.6, 1.0, r)
    else:
        v = 1 - _smooth(0.7, 1.0, r)
    return np.clip(v, 0, 1).astype(np.float32)


