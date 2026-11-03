"""Replay Substance Painter paint strokes with Strata's brush engine (needs the GPU engine).

Painter keeps paint layers as vector strokes, not pixels. Each DataStroke stores:
  viewType        1 = painted in the 3D view, 0 = painted in the 2D (UV) view
  viewMatrix,     the camera of the 3D view at the time (column-major 4x4, in Painter's normalised
  projectionMatrix  mesh space, which is the space the .spp mesh is stored in)
  points          DataStrokeKey: position = cursor in viewport coordinates 0..1 (3D) or UV (2D)
  pressure        optional per-point pen pressure

3D strokes: a picking buffer is rendered from the stored camera, every cursor sample is looked up
on the surface and fed to a strata.painter.Stroke built with that camera, so spacing, occlusion,
back-face falloff, seam wrapping and stroke opacity behave exactly like a live Strata stroke.
2D strokes paint UV-aligned dabs at the surface point under each UV sample.

Embedded bitmap alphas and explicitly named emitter jitter fields are retained.
Unvalidated symmetry and proprietary procedural tips remain reportable approximations.
"""
from __future__ import annotations

import math

import numpy as np

from ..layers import Brush, N_CH
from ..mathutil import normalize
from ..painter import Stroke, Surface, View
from . import hbo
from .hbo import val

MAX_DABS_PER_LAYER = 40000
MAX_DABS_TOTAL = 150000          # keeps a huge autosave from stalling the import
PICK_RES = 1024


def _mat(v):
    a = np.asarray(val(v) or [], np.float64)
    if a.size != 16 or not np.any(a):
        return None
    return a.reshape(4, 4).T          # stored column-major


def _points(stroke):
    pts = []
    for k in stroke.get("points") or []:
        if isinstance(k, hbo.HObj):
            p = val(k.get("position"))
            if isinstance(p, list) and len(p) >= 2:
                pts.append((float(p[0]), float(p[1])))
    return np.asarray(pts, np.float64).reshape(-1, 2)


def _pressure(stroke, n):
    vals = []
    for p in stroke.get("pressure") or []:
        v = val(p)
        if isinstance(v, (int, float)):
            vals.append(float(v))
        elif isinstance(v, list) and v:
            vals.append(float(v[0]))
    if len(vals) == n:
        return np.clip(np.asarray(vals), 0.0, 1.0)
    return np.ones(n)


class _UVStroke(Stroke):
    """A stroke painted in Painter's 2D view: dabs are discs in UV space, no occlusion test."""

    def _make_dab(self, s, direction):
        d = super()._make_dab(s, direction)
        d.radius_uv = self.uv_radius * d.radius / max(self.radius_fn(s.pos,s.tri),1e-9)
        d.radius = self.gm.mesh.radius * 4.0          # don't cull texels by 3D distance
        d.occl = False
        return d


    def feed(self,s):
        # UV source samples form one continuous path even across world-space seams.
        self._record_sample(s,"feed")
        if self.last is None:
            self.start(s)
            return
        last=self.last;distance=float(np.linalg.norm(s.uv-last.uv));b=self.brush
        pressure=(b.min_size+(1-b.min_size)*s.pressure) if b.pressure_size else 1.
        step=max(b.spacing*self.uv_radius*pressure*2,1e-6)
        t=step-self.carry
        while t<=distance:
            f=t/max(distance,1e-12)
            sample=Surface(last.pos+(s.pos-last.pos)*f,normalize(last.nrm*(1-f)+s.nrm*f),
                           last.uv+(s.uv-last.uv)*f,s.tri,last.pressure*(1-f)+s.pressure*f)
            self._dab(sample,s.pos-last.pos)
            t+=step
        self.carry=distance-(t-step);self.last=s


class ReplayPause(Exception):
    pass


class Replayer:
    def __init__(self, engine, ts=None, max_dabs=MAX_DABS_TOTAL, progress=None, seed_offset=0):
        self.e = engine
        self.ts = ts or engine.ts
        self.dabs = 0
        self.skipped = 0
        self.truncated = False
        self.max_dabs = max_dabs
        self.progress = progress
        self.seed_offset = seed_offset
        self.cancelled = False
        self.complete = True
        self.next_cursor = (0, 0)
        self._cam_key = None
        self._cam = None
        self._uvmaps = None

    def _full(self):
        if self.dabs >= self.max_dabs:
            self.truncated = True
            return True
        return False

    # -------------------------------------------------------------- brush and camera
    def _brush(self, job, uv=False):
        b = Brush()
        b.hardness = float(np.clip(job.brush.get("hardness", 0.8), 0.0, 0.99))
        b.flow = float(np.clip(job.brush.get("flow", 1.0), 0.02, 1.0))
        b.spacing = float(np.clip(job.brush.get("spacing", 0.15), 0.02, 4.0))
        b.mode = 1 if job.erase else 0
        b.grain = 0.0
        b.alignment = 3 if uv else 1
        b.backface = 180.0 if uv else 80.0
        b.pressure_size = bool(job.brush.get("pressure_size"))
        b.min_size = float(job.brush.get("pressure_size_min", 0.0))
        b.pressure_flow = bool(job.brush.get("pressure_flow"))
        b.min_flow = float(job.brush.get("pressure_flow_min", 0.0))
        en = job.channels()
        if job.erase and not any(en):
            en = [True] * N_CH
        b.enabled = en
        if job.color is not None:
            b.color = list(job.color)
        if job.rough is not None:
            b.rough = float(job.rough)
        if job.metal is not None:
            b.metal = float(job.metal)
        if job.height is not None:
            b.height = float(job.height)
        if job.normal is not None:
            b.normal = list(job.normal)
        if job.emissive is not None:
            b.emissive = list(job.emissive)
        if job.opac is not None:
            b.opac = float(job.opac)
        b.mask_value = float(np.clip(job.mask_value if job.mask_value is not None else 1.0, 0, 1))
        for key in ("alpha", "size_jitter", "flow_jitter", "angle_jitter", "pos_jitter"):
            if key in job.brush and job.brush[key] is not None:setattr(b,key,job.brush[key])
        b.target = 0
        return b

    def _camera(self, V, P):
        """Pick buffers + View for a stored Painter camera (one camera cached at a time)."""
        key = (V.astype(np.float32).tobytes(), P.astype(np.float32).tobytes())
        if key == self._cam_key:
            return self._cam
        e = self.e
        vp = P @ V
        aspect = abs(P[1, 1] / P[0, 0]) if abs(P[0, 0]) > 1e-6 else 1.0
        h = PICK_RES
        w = int(np.clip(round(h * aspect), 64, 4096))
        r = e.renderer
        r.render_pick(e.gm, vp, w, h)

        def read(att):
            return np.frombuffer(r.pick_fbo.read(components=4, attachment=att, dtype="f4"),
                                 np.float32).reshape(h, w, 4).copy()
        pos, nrm, uvt = read(0), read(1), read(2)
        inv = np.linalg.inv(V)
        eye = inv[:3, 3]
        right = normalize(inv[:3, 0])
        ortho = abs(P[3, 3] - 1.0) < 1e-6 and abs(P[3, 2]) < 1e-6
        fwd = -normalize(inv[:3, 2])

        def wpp(p, P=P, h=h):
            if ortho:
                return 2.0 / max(abs(P[1, 1]), 1e-6) / h
            d = max(float(np.dot(np.asarray(p, float) - eye, fwd)), 1e-4)
            return 2.0 * d / max(abs(P[1, 1]), 1e-6) / h

        view = View(vp=vp, size=(w, h), campos=eye, right=right, pick_pos=r.pick_pos, pick_uv=r.pick_uv,
                    wpp=wpp)
        self._cam_key = key
        self._cam = (view, pos, nrm, uvt, eye, P, ortho)
        return self._cam

    def _radius_3d(self, job, P, eye, ortho):
        size = float(job.brush.get("size", 0.1))
        if int(job.brush.get("size_space", 1)) == 0:      # screen-relative size
            def rf(p, tri):
                if ortho:
                    return max(size / max(abs(P[1, 1]), 1e-3), 1e-5)
                d = float(np.linalg.norm(np.asarray(p, float) - eye))
                return max(size * d / max(abs(P[1, 1]), 1e-3), 1e-5)
            return rf
        r = max(size * self.e.mesh.radius, 1e-5)          # relative to the mesh bounding box
        return lambda p, tri: r

    # -------------------------------------------------------------- replay
    def replay(self, lay, jobs, target_mask=False, budget=MAX_DABS_PER_LAYER, cursor=(0,0)):
        """Replay whole strokes without decimation; pause before publishing a partial stroke."""
        n0 = self.dabs
        limit = min(self.max_dabs,self.dabs+budget)
        self.complete = True
        for ji,job in enumerate(jobs):
            for si,stroke in enumerate(job.strokes):
                if (ji,si)<tuple(cursor):continue
                self.next_cursor=(ji,si)
                if self.progress is not None and self.progress(self.dabs) is False:
                    self.cancelled,self.complete=True,False
                    return self.dabs-n0
                self._limit=limit
                pts=_points(stroke)
                if len(pts)==0:
                    self.skipped+=1
                    continue
                vt=int(val(stroke.get("viewType"),1))
                V,P=_mat(stroke.get("viewMatrix")),_mat(stroke.get("projectionMatrix"))
                try:
                    if vt==1:
                        if V is None or P is None:self.skipped+=1
                        else:self._stroke_3d(lay,job,stroke,pts,V,P,target_mask,1)
                    else:self._stroke_uv(lay,job,stroke,pts,target_mask,1)
                except ReplayPause:
                    self.complete=False
                    return self.dabs-n0
        self.next_cursor=(len(jobs),0)
        self.e.dirty=True
        return self.dabs-n0

    def _run(self, stroke, surfaces):
        original=stroke._dab
        def dab(surface,direction):
            if self.dabs+stroke.dabs>=self._limit:
                self.truncated=True
                raise ReplayPause()
            if stroke.dabs%64==0 and self.progress is not None and self.progress(self.dabs+stroke.dabs) is False:
                self.cancelled=True
                raise ReplayPause()
            return original(surface,direction)
        stroke._dab=dab
        try:
            stroke.start(surfaces[0])
            for sf in surfaces[1:]:stroke.feed(sf)
            stroke.apply()
            self.dabs+=stroke.dabs
        finally:stroke.release()

    def _new_stroke(self, cls, lay, job, view, radius_fn, target_mask, uv=False):
        e = self.e
        b = self._brush(job, uv)
        if target_mask:
            target, textures = "mask", lay.mask_tex
        else:
            target, textures = "layer", lay.tex
        return cls(e.painter, e.gm, self.ts.key, b, view, radius_fn, target, textures, quick=None,
                   mask_value=b.mask_value, seed=(self.seed_offset+self.dabs) * 31 + 7)

    def _stroke_3d(self, lay, job, stroke, pts, V, P, target_mask, stride):
        view, pos, nrm, uvt, eye, P, ortho = self._camera(V, P)
        h, w = pos.shape[:2]
        press = _pressure(stroke, len(pts))
        surfaces = []
        for (x, y), pr in zip(pts[::stride], press[::stride]):
            px, py = int(x * w), int((1.0 - y) * h)          # Painter's viewport origin is top-left
            if not (0 <= px < w and 0 <= py < h):
                continue
            p = pos[py, px]
            if p[3] < 0.5:
                continue
            u = uvt[py, px]
            surfaces.append(Surface(p[:3].astype(np.float64), normalize(nrm[py, px, :3].astype(np.float64)),
                                    u[:2].astype(np.float64), int(round(u[2])), float(pr)))
        if not surfaces:
            self.skipped += 1
            return
        st = self._new_stroke(Stroke, lay, job, view, self._radius_3d(job, P, eye, ortho), target_mask)
        self._run(st, surfaces)

    def _uv_lookup(self):
        """World position / normal per texel of the texture set (from the bakes), for 2D strokes."""
        if self._uvmaps is None:
            b = self.ts.bakes
            g = self.e.gpu
            pos = g.read(b.pos)
            nrm = g.read(b.nrm)
            self._uvmaps = (pos, nrm)
        return self._uvmaps

    def _stroke_uv(self, lay, job, stroke, pts, target_mask, stride):
        e = self.e
        pos, nrm = self._uv_lookup()
        res = pos.shape[0]
        size = float(job.brush.get("size", 0.1))
        press = _pressure(stroke, len(pts))
        surfaces = []
        for (u, v), pr in zip(pts[::stride], press[::stride]):
            uv = np.array([u, 1.0 - v])                      # Painter's 2D view has v pointing down
            tx, ty = int(np.clip(uv[0] * res, 0, res - 1)), int(np.clip(uv[1] * res, 0, res - 1))
            p, n = pos[ty, tx, :3], nrm[ty, tx, :3]
            if not np.any(p) and not np.any(n):
                p = np.zeros(3)
                n = np.array([0.0, 0.0, 1.0])
            surfaces.append(Surface(p.astype(np.float64), normalize(n.astype(np.float64) + 1e-9), uv, -1, float(pr)))
        if not surfaces:
            self.skipped += 1
            return
        r_uv = max(size * 0.5, 1e-4)
        cam = e.camera
        view = View(vp=e._vp if e._vp is not None else np.eye(4), size=e.view_size, campos=cam.eye, right=cam.right,
                    pick_pos=None, pick_uv=None, wpp=lambda p: r_uv * 0.1)
        # spacing works in world units: express the UV radius as a world radius along the surface
        world_r = r_uv * self._uv_world_scale()
        st = self._new_stroke(_UVStroke, lay, job, view, lambda p, tri: world_r, target_mask, uv=True)
        st.uv_radius = r_uv
        self._run(st, surfaces)

    def _uv_world_scale(self):
        m = self.e.mesh
        tris = getattr(self.ts, "tri_ids", None)
        idx = m.indices if tris is None or not len(tris) else m.indices[tris]
        tri = m.positions[idx]
        a3 = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1).sum()
        uv = m.uvs[idx]
        d1, d2 = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
        a2 = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]).sum()
        return math.sqrt(a3 / max(a2, 1e-9))
