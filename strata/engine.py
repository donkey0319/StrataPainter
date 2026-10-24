"""Engine: project state + all GPU subsystems. Has no UI dependency, so it runs headless."""
from __future__ import annotations

import copy
import io
import json
import os
import zipfile

import moderngl
import numpy as np

from .baker import Baker, BakeSet, PAD
from .compositor import Compositor
from .gpu import GPU, GPUMesh
from .layers import Brush, Layer, MaskGen
from .mesh import BUILTIN_MESHES, Mesh
from .painter import Painter
from .presets import SMART_MATERIALS
from .renderer import Camera, Renderer

UNDO_LIMIT = 24


class Engine:
    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        self.gpu = GPU(ctx)
        self.baker = Baker(self.gpu)
        self.painter = Painter(self.gpu)
        self.renderer = Renderer(self.gpu)
        self.camera = Camera()
        self.brush = Brush()
        self.mesh: Mesh | None = None
        self.gm: GPUMesh | None = None
        self.bakes: BakeSet | None = None
        self.comp: Compositor | None = None
        self.layers: list[Layer] = []
        self.selected = -1
        self.res = 2048
        self.normal_strength = 1.0
        self.dirty = True
        self.undo_stack, self.redo_stack = [], []
        self._stroke = None
        self.view_size = (1, 1)
        self._vp = np.eye(4)

    # ------------------------------------------------------------------ project
    def new_project(self, mesh: Mesh | str, res: int = 2048, ao_samples: int = 96, progress=None,
                    with_default_layer=True):
        if isinstance(mesh, str):
            mesh = BUILTIN_MESHES[mesh]()
        self._release_project()
        self.mesh, self.res = mesh, int(res)
        self.gm = GPUMesh(self.gpu, mesh)
        self.bakes = self.baker.bake(self.gm, self.res, ao_samples=ao_samples, progress=progress)
        self.comp = Compositor(self.gpu, self.res, self.bakes, mesh)
        self.camera.frame(mesh.center, mesh.radius)
        self.layers, self.selected = [], -1
        self.undo_stack.clear(); self.redo_stack.clear()
        if with_default_layer:
            self.add_layer("paint", record=False)
        self.dirty = True

    def _release_project(self):
        for lay in self.layers:
            self._release_layer(lay)
        for e in self.undo_stack + self.redo_stack:
            self._release_entry(e)
        for o in (self.comp, self.bakes, self.gm):
            if o is not None:
                o.release()
        self.comp = self.bakes = self.gm = None

    # ------------------------------------------------------------------ layers
    @property
    def layer(self) -> Layer | None:
        return self.layers[self.selected] if 0 <= self.selected < len(self.layers) else None

    def _alloc_paint(self, lay: Layer):
        r = (self.res, self.res)
        g = self.gpu
        lay.tex = {"C": g.texture(r, 4), "R": g.texture(r, 2), "M": g.texture(r, 2), "H": g.texture(r, 2)}
        for t in lay.tex.values():
            g.fill(t, (0, 0, 0, 0))

    def _alloc_mask(self, lay: Layer, value: float):
        lay.mask_tex = self.gpu.texture((self.res, self.res), 1)
        self.gpu.fill(lay.mask_tex, (value, value, value, 1))

    def _release_layer(self, lay: Layer):
        self.painter.forget(lay)
        if lay.tex:
            for t in lay.tex.values():
                t.release()
            lay.tex = None
        if lay.mask_tex is not None:
            lay.mask_tex.release()
            lay.mask_tex = None

    def _snapshot_stack(self):
        return ("stack", list(self.layers), self.selected)

    def add_layer(self, kind="paint", name=None, layer: Layer | None = None, index=None, record=True):
        if record:
            self._push_undo(self._snapshot_stack())
        lay = layer or Layer(name=name or ("Paint layer" if kind == "paint" else "Fill layer"), kind=kind)
        if lay.kind == "paint" and lay.tex is None:
            self._alloc_paint(lay)
        if lay.has_mask and lay.mask_tex is None:
            self._alloc_mask(lay, 1.0)
        idx = len(self.layers) if index is None else index
        self.layers.insert(idx, lay)
        self.selected = idx
        self.dirty = True
        return lay

    def add_smart_material(self, name: str):
        self._push_undo(self._snapshot_stack())
        # land under a selected paint layer, so the user's painting stays on top
        sel = self.layer
        idx = 0 if sel is None else (self.selected if sel.kind == "paint" else self.selected + 1)
        new = SMART_MATERIALS[name]()
        for i, lay in enumerate(new):
            self.add_layer(layer=lay, index=idx + i, record=False)
        if sel is not None and sel.kind == "paint":
            self.selected = self.layers.index(sel)   # keep painting where you were

    def delete_layer(self, idx=None):
        idx = self.selected if idx is None else idx
        if not (0 <= idx < len(self.layers)):
            return
        self._push_undo(self._snapshot_stack())
        self.layers.pop(idx)            # GPU data stays alive in the undo entry
        self.selected = min(idx, len(self.layers) - 1)
        self.dirty = True

    def duplicate_layer(self, idx=None):
        idx = self.selected if idx is None else idx
        if not (0 <= idx < len(self.layers)):
            return
        src = self.layers[idx]
        lay = Layer.from_dict(src.to_dict())
        lay.name = src.name + " copy"
        if src.tex:
            lay.tex = {k: self.gpu.clone(t) for k, t in src.tex.items()}
        if src.mask_tex is not None:
            lay.mask_tex = self.gpu.clone(src.mask_tex)
        self.add_layer(layer=lay, index=idx + 1)

    def move_layer(self, idx, delta):
        j = idx + delta
        if 0 <= idx < len(self.layers) and 0 <= j < len(self.layers):
            self._push_undo(self._snapshot_stack())
            self.layers[idx], self.layers[j] = self.layers[j], self.layers[idx]
            self.selected = j
            self.dirty = True

    def add_mask(self, value=1.0, idx=None):
        lay = self.layers[self.selected if idx is None else idx]
        if lay.mask_tex is None:
            self._alloc_mask(lay, value)
        else:
            self.gpu.fill(lay.mask_tex, (value, value, value, 1))
        lay.has_mask = True
        self.dirty = True

    def remove_mask(self, idx=None):
        lay = self.layers[self.selected if idx is None else idx]
        lay.has_mask = False
        self.dirty = True

    def fill_mask(self, value, idx=None):
        lay = self.layers[self.selected if idx is None else idx]
        if lay.mask_tex is None:
            self.add_mask(value, idx)
            return
        self._push_undo(("tex", lay, {"mask": self.gpu.clone(lay.mask_tex)}))
        self.gpu.fill(lay.mask_tex, (value, value, value, 1))
        self.dirty = True

    def clear_paint(self, idx=None):
        lay = self.layers[self.selected if idx is None else idx]
        if lay.kind != "paint":
            return
        self._push_undo(("tex", lay, {k: self.gpu.clone(t) for k, t in lay.tex.items()}))
        for t in lay.tex.values():
            self.gpu.fill(t, (0, 0, 0, 0))
        self.dirty = True

    # ------------------------------------------------------------------ undo / redo
    def _push_undo(self, entry, clear_redo=True):
        self.undo_stack.append(entry)
        if clear_redo:
            dropped, self.redo_stack = self.redo_stack, []
            for e in dropped:
                self._release_entry(e)
        while len(self.undo_stack) > UNDO_LIMIT:
            self._release_entry(self.undo_stack.pop(0))

    def _live_layers(self):
        live = {id(l) for l in self.layers}
        for e in self.undo_stack + self.redo_stack:
            live |= {id(l) for l in e[1]} if e[0] == "stack" else {id(e[1])}
        return live

    def _release_entry(self, e):
        if e[0] == "tex":
            for t in e[2].values():
                t.release()
        elif e[0] == "stack":
            live = self._live_layers()
            for lay in e[1]:
                if id(lay) not in live:
                    self._release_layer(lay)

    def _apply(self, e):
        """Restore entry e, returning the inverse entry."""
        if e[0] == "stack":
            inv = self._snapshot_stack()
            self.layers, self.selected = list(e[1]), e[2]
            return inv
        lay, saved = e[1], e[2]
        cur = {}
        for k, t in saved.items():
            dst = lay.mask_tex if k == "mask" else lay.tex[k]
            cur[k] = self.gpu.clone(dst)
            self.gpu.blit(t, dst)
            t.release()
        return ("tex", lay, cur)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._apply(self.undo_stack.pop()))
            self.dirty = True

    def redo(self):
        if self.redo_stack:
            self._push_undo(self._apply(self.redo_stack.pop()), clear_redo=False)
            self.dirty = True

    # ------------------------------------------------------------------ viewport
    def update_view(self, w, h):
        self.view_size = (max(int(w), 1), max(int(h), 1))
        cam = self.camera
        self._vp = cam.proj(self.view_size[0] / self.view_size[1]) @ cam.view()
        self.renderer.render_pick(self.gm, self._vp, *self.view_size)

    def pick(self, x, y):
        return self.renderer.read_pick(x, y)

    def update(self):
        if self.dirty and self.comp is not None:
            self.comp.composite(self.layers, self.normal_strength)
            if self.renderer.mode == 6 and self.layer is not None:
                self.comp.render_mask(self.layer)
            self.dirty = False

    def render(self, rect, cursor=None):
        """Draw the viewport into the bound framebuffer. rect=(x,y,w,h) in framebuffer pixels."""
        target = self.ctx.fbo
        self.update()
        target.use()
        self.renderer.render(self.gm, self.camera, self._vp, self.comp, self.bakes, rect)
        if cursor is not None:
            hit, nrm = cursor
            self.renderer.draw_cursor(hit, nrm, self.brush_radius(hit), self._vp, rect)

    # ------------------------------------------------------------------ painting
    def brush_radius(self, hit):
        return self.brush.size_px * 0.5 * self.camera.world_per_pixel(hit, self.view_size[1])

    def can_paint(self):
        lay = self.layer
        if lay is None or not lay.visible:
            return False
        if self.brush.target == 1:
            return True
        return lay.kind == "paint"

    def begin_stroke(self, hit):
        lay = self.layer
        if not self.can_paint():
            return False
        to_mask = self.brush.target == 1
        if to_mask and (lay.mask_tex is None or not lay.has_mask):
            self.add_mask(0.0 if self.brush.mask_value > 0.5 else 1.0)
        saved = {"mask": self.gpu.clone(lay.mask_tex)} if to_mask else \
            {k: self.gpu.clone(t) for k, t in lay.tex.items()}
        self._push_undo(("tex", lay, saved))
        self._stroke = {"last": np.asarray(hit, float), "carry": 0.0, "mask": to_mask}
        self._dab(hit)
        return True

    def stroke_to(self, hit):
        if self._stroke is None:
            return
        hit = np.asarray(hit, float)
        st = self._stroke
        seg = hit - st["last"]
        dist = float(np.linalg.norm(seg))
        r = self.brush_radius(hit)
        step = max(self.brush.spacing * r * 2, 1e-5)
        if dist > r * 6:            # jumped across the model: restart instead of streaking
            st["last"], st["carry"] = hit, 0.0
            self._dab(hit)
            return
        t = step - st["carry"]
        while t <= dist:
            self._dab(st["last"] + seg * (t / dist))
            t += step
        st["carry"] = dist - (t - step)
        st["last"] = hit

    def end_stroke(self):
        self._stroke = None

    def _dab(self, hit):
        self.painter.dab(self.gm, self.layer, self.brush, hit, self.brush_radius(hit), self._vp,
                         self.camera.eye, self.renderer.pick_pos, self._stroke["mask"])
        self.dirty = True

    # ------------------------------------------------------------------ save / load
    def save(self, path):
        arrays = {}
        m = self.mesh
        for k in ("positions", "normals", "uvs", "indices", "tangents", "curvature"):
            arrays["mesh_" + k] = getattr(m, k)
        layers = []
        for i, lay in enumerate(self.layers):
            d = lay.to_dict()
            if lay.tex:
                for k, t in lay.tex.items():
                    arrays[f"L{i}_{k}"] = self.gpu.read(t).astype(np.float16)
            if lay.mask_tex is not None:
                arrays[f"L{i}_mask"] = self.gpu.read(lay.mask_tex).astype(np.float16)
            layers.append(d)
        meta = {"version": 1, "mesh_name": m.name, "res": self.res, "selected": self.selected,
                "normal_strength": self.normal_strength, "layers": layers,
                "brush": self.brush.__dict__}
        buf = io.BytesIO()
        np.savez_compressed(buf, **arrays)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
            z.writestr("project.json", json.dumps(meta, indent=1))
            z.writestr("data.npz", buf.getvalue())

    def load(self, path, progress=None):
        with zipfile.ZipFile(path) as z:
            meta = json.loads(z.read("project.json"))
            data = np.load(io.BytesIO(z.read("data.npz")))
            mesh = Mesh(meta["mesh_name"], *(data["mesh_" + k] for k in ("positions", "normals", "uvs", "indices")),
                        tangents=data["mesh_tangents"], curvature=data["mesh_curvature"]).finalize()
            self.new_project(mesh, meta["res"], progress=progress, with_default_layer=False)
            for i, d in enumerate(meta["layers"]):
                lay = Layer.from_dict(d)
                if lay.kind == "paint":
                    self._alloc_paint(lay)
                    for k in "CRMH":
                        lay.tex[k].write(data[f"L{i}_{k}"].astype(np.float16).tobytes())
                if f"L{i}_mask" in data:
                    self._alloc_mask(lay, 1.0)
                    lay.mask_tex.write(data[f"L{i}_mask"].astype(np.float16).tobytes())
                self.layers.append(lay)
            self.selected = min(meta.get("selected", 0), len(self.layers) - 1)
            self.normal_strength = meta.get("normal_strength", 1.0)
            b = meta.get("brush")
            if b:
                for k, v in b.items():
                    if hasattr(self.brush, k):
                        setattr(self.brush, k, v)
        self.dirty = True
