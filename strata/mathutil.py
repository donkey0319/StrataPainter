"""Row-major matrix helpers (math convention M @ v). Upload with glmat()."""
import numpy as np


def normalize(v):
    v = np.asarray(v, np.float64)
    return v / max(np.linalg.norm(v), 1e-12)


def look_at(eye, target, up=(0, 1, 0)):
    eye, target = np.asarray(eye, float), np.asarray(target, float)
    f = normalize(target - eye)
    if abs(np.dot(f, normalize(up))) > 0.999:
        up = (1, 0, 0)
    s = normalize(np.cross(f, up))
    u = np.cross(s, f)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def perspective(fovy_deg, aspect, near, far):
    f = 1.0 / np.tan(np.radians(fovy_deg) / 2)
    m = np.zeros((4, 4))
    m[0, 0], m[1, 1] = f / aspect, f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1
    return m


def ortho(l, r, b, t, n, f):
    m = np.eye(4)
    m[0, 0], m[1, 1], m[2, 2] = 2 / (r - l), 2 / (t - b), -2 / (f - n)
    m[0, 3], m[1, 3], m[2, 3] = -(r + l) / (r - l), -(t + b) / (t - b), -(f + n) / (f - n)
    return m


def glmat(m) -> bytes:
    return np.ascontiguousarray(np.asarray(m, np.float32).T).tobytes()


def fibonacci_sphere(n):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(th) * np.sin(phi), np.cos(phi), np.sin(th) * np.sin(phi)], 1)
