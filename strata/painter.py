"""3D brush engine.

Each dab rasterises the mesh in UV space; texels near the hit point (in 3D, on screen or in UV,
depending on the alignment) receive paint if the camera can see them. Paint and erase strokes
accumulate into a stroke buffer that is merged over a snapshot of the layer, which is what makes
Stroke Opacity a ceiling rather than a per-dab value. Smudge and clone pull texels through the
screen-space pick buffer, so they work across UV seams.
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field

import moderngl
import numpy as np

from . import shaders as S
from .gpu import GPU, GPUMesh
from .layers import Brush, Layer
from .channels import CHANNEL_DESCRIPTORS, N_CH
from .userchannels import paint_channels, descriptor, is_user
from .mathutil import glmat, normalize

PAINT_BLEND = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA, moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
ERASE_BLEND = (moderngl.ZERO, moderngl.ONE_MINUS_SRC_ALPHA, moderngl.ZERO, moderngl.ONE_MINUS_SRC_ALPHA)
COVER_BLEND = (moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)

TOOL_PAINT, TOOL_SMUDGE, TOOL_CLONE, TOOL_PROJECTION = range(4)
IDENTITY = np.eye(4)


def channel_shader(source, keys):
    """Compact MRT locations for authored channels; retain the established shader math."""
    keys = ["H" if is_user(key) else key for key in keys]
    enabled = {channel.index: index for index, channel in enumerate(c for c in CHANNEL_DESCRIPTORS if c.key in keys)}
    for channel in CHANNEL_DESCRIPTORS:
        i = channel.index
        declaration = f"layout(location={i}) out vec4 o{i};"
        if i in enabled:
            source = source.replace(declaration, f"layout(location={enabled[i]}) out vec4 o{i};")
        else:
            source = source.replace(declaration, "")
            source = re.sub(rf"\bo{i}\s*=\s*[^;]*;", "", source)
    return source


@dataclass
class View:
    """What the brush needs to know about the camera for one stroke."""
    vp: np.ndarray            # view-projection, row-major
    size: tuple               # viewport pixels (w, h)
    campos: np.ndarray
    right: np.ndarray         # camera right vector (world)
    pick_pos: object          # textures from the renderer's pick pass
    pick_uv: object
    wpp: callable             # world_per_pixel(point) -> float
    uv_mapping: object = None # native 2D mapping; distances are UV units
    tile_offset: tuple = (0, 0) # global operation coordinates -> local raster coordinates

    def project(self, p):
        if self.uv_mapping is not None:
            return self.uv_mapping.pixel(np.asarray(p)[:2])
        c = self.vp @ np.append(np.asarray(p, float), 1.0)
        if c[3] <= 1e-9:
            return None
        s = c[:2] / c[3] * 0.5 + 0.5
        return s * np.asarray(self.size, float)


@dataclass
class Surface:
    pos: np.ndarray
    nrm: np.ndarray
    uv: np.ndarray
    tri: int = -1
    pressure: float = 1.0


@dataclass
class Dab:
    hit: np.ndarray
    radius: float
    frame: tuple              # T, B, N
    rot: tuple                # cos, sin
    hit_px: np.ndarray
    radius_px: float
    hit_uv: np.ndarray
    radius_uv: float
    flow: float
    sym_inv: np.ndarray = field(default_factory=lambda: np.eye(4))
    occl: bool = True


def symmetry_transforms(brush: Brush) -> list:
    """Object-space 4x4 transforms for the extra symmetric copies of each dab."""
    if brush.symmetry == 0:
        return []
    c = np.asarray(brush.sym_center, float)
    ax = int(brush.sym_axis) % 3
    T, Ti = np.eye(4), np.eye(4)
    T[:3, 3], Ti[:3, 3] = c, -c
    if brush.symmetry == 1:
        M = np.eye(4)
        M[ax, ax] = -1.0
        return [T @ M @ Ti]
    out = []
    n = max(int(brush.radial_count), 1)
    for k in range(1, n):
        a = 2 * math.pi * k / n
        R = np.eye(4)
        i, j = [(1, 2), (2, 0), (0, 1)][ax]
        R[i, i], R[i, j], R[j, i], R[j, j] = math.cos(a), -math.sin(a), math.sin(a), math.cos(a)
        out.append(T @ R @ Ti)
    return out


def stencil_matrix(xform, image_size, view_size) -> np.ndarray:
    """mat3 mapping viewport pixels -> stencil/projection image UV."""
    cx, cy, scale, rot = (list(xform) + [0.5, 0.5, 1.0, 0.0])[:4]
    vw, vh = view_size
    iw, ih = image_size
    aspect = iw / max(ih, 1)
    h = max(scale, 1e-4) * vh
    w = h * aspect
    a = math.radians(rot)
    c, s = math.cos(-a), math.sin(-a)
    Tc = np.array([[1, 0, -cx * vw], [0, 1, -cy * vh], [0, 0, 1]], float)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)
    Sc = np.array([[1 / w, 0, 0], [0, 1 / h, 0], [0, 0, 1]], float)
    Th = np.array([[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1]], float)
    return Th @ Sc @ R @ Tc


def _mat3(m) -> bytes:
    return np.ascontiguousarray(np.asarray(m, np.float32).T).tobytes()


class Painter:
    def __init__(self, gpu: GPU, resources=None):
        self.gpu = gpu
        self.resources = resources
        self.p_paint = gpu.program("brush_paint", S.UV_VS, S.BRUSH_PAINT_FS)
        self.p_mask = gpu.program("brush_mask", S.UV_VS, S.BRUSH_MASK_FS)
        self.p_sample = gpu.program("brush_sample", S.UV_VS, S.SAMPLE_TOOL_FS)
        self.p_apply = gpu.fs_program("stroke_apply", S.STROKE_APPLY_FS)
        self.p_apply_mask = gpu.fs_program("stroke_apply_mask", S.STROKE_APPLY_MASK_FS)
        self._fbos = {}

    # ------------------------------------------------------------------ framebuffers
    def _fbo(self, key, textures):
        k = (key, tuple(id(t) for t in textures))
        f = self._fbos.get(k)
        if f is None:
            f = self._fbos[k] = self.gpu.ctx.framebuffer(list(textures))
        return f

    def forget(self, lay: Layer):
        ids = set()
        if lay.tex:
            ids |= {id(t) for t in lay.tex.values()}
        if lay.mask_tex is not None:
            ids.add(id(lay.mask_tex))
        for k in [k for k in self._fbos if ids & set(k[1])]:
            self._fbos.pop(k).release()

    def forget_textures(self, textures):
        ids = {id(t) for t in textures}
        for k in [k for k in self._fbos if ids & set(k[1])]:
            self._fbos.pop(k).release()

    # ------------------------------------------------------------------ uniforms
    def _common(self, p, brush: Brush, view: View, dab: Dab | None, quick, mesh_radius: float):
        g = self.gpu
        set_ = g.set
        res = self.resources
        mapping = view.uv_mapping
        tile = np.asarray(view.tile_offset, float)
        set_(p, "u_uvView", int(mapping is not None))
        if mapping is not None:
            set_(p, "u_uvScale", tuple(mapping.scale))
            set_(p, "u_uvCenter", tuple(np.asarray(mapping.center) - tile))
            if "u_uvAxes" in p:
                p["u_uvAxes"].write(np.ascontiguousarray(mapping.axes.T, np.float32).tobytes())
        if dab is not None:
            T, B, N = dab.frame
            hit = np.asarray(dab.hit, float).copy()
            if mapping is not None:
                hit[:2] -= tile
            set_(p, "u_hit", tuple(map(float, hit)))
            set_(p, "u_radius", float(dab.radius))
            set_(p, "u_fT", tuple(map(float, T))); set_(p, "u_fB", tuple(map(float, B)))
            set_(p, "u_fN", tuple(map(float, N)))
            set_(p, "u_rot", tuple(map(float, dab.rot)))
            set_(p, "u_hitPx", tuple(map(float, dab.hit_px)))
            set_(p, "u_radiusPx", float(max(dab.radius_px, 1e-3)))
            set_(p, "u_hitUV", tuple(map(float, np.asarray(dab.hit_uv) - tile)))
            set_(p, "u_radiusUV", float(max(dab.radius_uv, 1e-6)))
            set_(p, "u_flow", float(dab.flow))
            set_(p, "u_occl", int(dab.occl))
            set_(p, "u_tol", float(dab.radius * 0.25 + mesh_radius * 0.004))
            if "u_symInv" in p:
                p["u_symInv"].write(glmat(dab.sym_inv))
            align = int(brush.alignment)
            if align == 3 and not np.allclose(dab.sym_inv, IDENTITY):
                align = 2          # UV alignment can't be mirrored: use planar for copies
            set_(p, "u_align", align)
            set_(p, "u_full", 0)
        else:
            set_(p, "u_full", 1)
            if "u_symInv" in p:
                p["u_symInv"].write(glmat(IDENTITY))
            set_(p, "u_flow", 1.0)
        if "u_vp" in p:
            p["u_vp"].write(glmat(view.vp))
        set_(p, "u_viewport", tuple(float(x) for x in view.size))
        set_(p, "u_campos", tuple(map(float, view.campos)))
        set_(p, "u_backCos", float(math.cos(math.radians(np.clip(brush.backface, 1.0, 180.0)))))
        set_(p, "u_hardness", float(brush.hardness))
        set_(p, "u_grain", float(brush.grain))
        set_(p, "u_grainScale", float(brush.grain_scale) / max(mesh_radius, 1e-3))
        units = {"u_pickPos": (0, view.pick_pos or g.black), "u_uvCoverage": (14, view.pick_pos or g.black)}
        alpha = res.alpha(brush.alpha) if (res and brush.alpha) else None
        set_(p, "u_hasAlpha", int(alpha is not None))
        set_(p, "u_alphaInv", int(bool(brush.alpha_invert)))
        units["u_alpha"] = (1, alpha or g.white)
        stencil = None
        if res and brush.stencil and brush.stencil_enabled:
            try:
                stencil = res.texture(brush.stencil, "gray")
            except Exception as e:
                print(f"[strata] stencil: {e}")
        set_(p, "u_hasStencil", int(stencil is not None))
        if stencil is not None:
            if "u_stencilXf" in p:
                p["u_stencilXf"].write(_mat3(stencil_matrix(brush.stencil_xform, stencil.size, view.size)))
            set_(p, "u_stencilTile", int(brush.stencil_tiling))
        units["u_stencil"] = (2, stencil or g.white)
        use_quick = quick is not None and brush.use_quick_mask
        set_(p, "u_hasQuick", int(use_quick))
        units["u_quick"] = (3, quick if use_quick else g.white)
        return units

    def _paint_values(self, p, brush: Brush, erase: bool):
        g = self.gpu
        en = [int(bool(brush.enabled[channel.index])) for channel in CHANNEL_DESCRIPTORS]
        if brush.user_channel and brush.target == 0:
            en = [0, 0, 0, 1, 0, 0, 0]
        if "u_en" in p:
            p["u_en"].value = tuple(en[:p["u_en"].array_length]) if p["u_en"].array_length > 1 else en[0]
        for channel in CHANNEL_DESCRIPTORS:
            value = brush.user_value if brush.user_channel and brush.target == 0 and channel.key == "H" else getattr(brush, channel.attribute)
            if self.resources is not None and channel.key in ("C", "E"):
                value = self.resources.pipeline.working(value)
            uniform_value = tuple(map(float, value)) if channel.value_components > 1 else float(value)
            g.set(p, "u_" + channel.attribute, uniform_value)

    def _map_units(self, p, brush: Brush, view: View, projection: bool, erase=False):
        g, res = self.gpu, self.resources
        units, has = {}, [0] * N_CH
        size = None
        maps = brush.proj_maps if projection else brush.maps
        if res and (projection or (not brush.user_channel and not erase)):
            for channel in CHANNEL_DESCRIPTORS:
                i = channel.index
                path = maps.get(channel.key)
                if not path or not brush.enabled[i]:
                    continue
                try:
                    t = res.texture(path, channel.resource_kind)
                except Exception as e:
                    print(f"[strata] brush map {path}: {e}")
                    continue
                units[f"u_p{i}"] = (4 + i, t)
                has[i] = 1
                size = size or t.size
        for channel in CHANNEL_DESCRIPTORS:
            units.setdefault(f"u_p{channel.index}", (4 + channel.index, g.black))
        active = projection and any(has)
        g.set(p, "u_projActive", (1 if projection else 2) if any(has) else 0)
        if "u_hasP" in p:
            p["u_hasP"].value = tuple(has[:p["u_hasP"].array_length]) if p["u_hasP"].array_length > 1 else has[0]
        if active and "u_projXf" in p:
            p["u_projXf"].write(_mat3(stencil_matrix(brush.proj_xform, size, view.size)))
            g.set(p, "u_projTile", int(brush.proj_tiling))
        return units

    def _begin_draw(self, fbo, size):
        ctx = self.gpu.ctx
        fbo.use()
        ctx.viewport = (0, 0, size[0], size[1])
        ctx.scissor = None
        ctx.disable(moderngl.DEPTH_TEST | moderngl.CULL_FACE)

    # ------------------------------------------------------------------ dabs
    def dab_paint(self, gm: GPUMesh, subset, buffers: list, brush: Brush, view: View, dab: Dab,
                  quick, projection: bool):
        """Accumulate one dab into a 7-texture stroke buffer (paint, erase or projection)."""
        keys = [c.key for c in paint_channels(brush)]
        vertex = S.UV_BRUSH_VS if view.uv_mapping is not None else S.UV_VS
        p = self.gpu.program("brush_sparse_" + str(view.uv_mapping is not None) + "".join(keys),
                             vertex, channel_shader(S.BRUSH_PAINT_FS, keys))
        units = self._common(p, brush, view, dab, quick, gm.mesh.radius)
        units.update(self._map_units(p, brush, view, projection, erase=bool(brush.mode)))
        self._paint_values(p, brush, False)
        self.gpu.bind(p, units)
        ctx = self.gpu.ctx
        self._begin_draw(self._fbo("stroke", buffers), buffers[0].size)
        ctx.enable(moderngl.BLEND)
        ctx.blend_equation = moderngl.FUNC_ADD
        ctx.blend_func = PAINT_BLEND
        self.gpu.draw_quad(p) if view.uv_mapping is not None else gm.render(p, subset)
        ctx.disable(moderngl.BLEND)

    def dab_mask(self, gm: GPUMesh, subset, buffer, brush: Brush, view: View, dab: Dab, quick):
        """Accumulate one dab's coverage into a single-channel stroke buffer."""
        p = (self.gpu.program("uv_brush_mask", S.UV_BRUSH_VS, S.BRUSH_MASK_FS)
             if view.uv_mapping is not None else self.p_mask)
        units = self._common(p, brush, view, dab, quick, gm.mesh.radius)
        self.gpu.set(p, "u_direct", 0)
        self.gpu.bind(p, units)
        ctx = self.gpu.ctx
        self._begin_draw(self._fbo("mstroke", [buffer]), buffer.size)
        ctx.enable(moderngl.BLEND)
        ctx.blend_equation = moderngl.FUNC_ADD
        ctx.blend_func = COVER_BLEND
        self.gpu.draw_quad(p) if view.uv_mapping is not None else gm.render(p, subset)
        ctx.disable(moderngl.BLEND)

    def dab_sample(self, gm: GPUMesh, subset, targets: list, sources: list, brush: Brush, view: View,
                   dab: Dab, quick, offset_px):
        """Smudge / clone: for each target texture pull texels from `sources` at a screen offset."""
        g = self.gpu
        p = (g.program("uv_brush_sample", S.UV_BRUSH_VS, S.SAMPLE_TOOL_FS)
             if view.uv_mapping is not None else self.p_sample)
        units = self._common(p, brush, view, dab, quick, gm.mesh.radius)
        g.set(p, "u_offsetPx", tuple(float(x) for x in offset_px))
        ctx = g.ctx
        for tgt, src in zip(targets, sources):
            scratch = g.scratch("sample_cur", tgt.size, tgt.components, tgt.dtype)
            g.blit(tgt, scratch)
            u = dict(units)
            u["u_pickUV"] = (4, view.pick_uv or g.black)
            u["u_cur"] = (5, scratch)
            u["u_src"] = (6, scratch if src is None else src)
            g.bind(p, u)
            self._begin_draw(self._fbo("sample", [tgt]), tgt.size)
            ctx.disable(moderngl.BLEND)
            g.draw_quad(p) if view.uv_mapping is not None else gm.render(p, subset)

    # ------------------------------------------------------------------ stroke buffers
    def apply_paint(self, layer_tex: dict, snapshot: dict, buffers: list, stroke_opacity: float, erase: bool):
        """layer = snapshot (+) stroke buffer * stroke opacity, all seven channels at once."""
        g = self.gpu
        keys = list(snapshot)
        p = g.fs_program("apply_sparse_" + "".join(keys), channel_shader(S.STROKE_APPLY_FS, keys))
        units = {}
        for index, key in enumerate(keys):
            channel = descriptor(key)
            i = channel.index
            units[f"u_s{i}"] = (i, snapshot[channel.key])
            units[f"u_k{i}"] = (N_CH + i, buffers[index])
        g.bind(p, units)
        g.set(p, "u_so", float(stroke_opacity))
        g.set(p, "u_erase", int(erase))
        targets = [layer_tex[key] for key in keys]
        self._begin_draw(self._fbo("apply", targets), targets[0].size)
        g.ctx.disable(moderngl.BLEND)
        g.draw_quad(p)

    def apply_mask(self, target, snapshot, buffer, stroke_opacity: float, value: float):
        g, p = self.gpu, self.p_apply_mask
        g.bind(p, {"u_snap": (0, snapshot), "u_stroke": (1, buffer)})
        g.set(p, "u_so", float(stroke_opacity))
        g.set(p, "u_value", float(value))
        self._begin_draw(self._fbo("apply_mask", [target]), target.size)
        g.ctx.disable(moderngl.BLEND)
        g.draw_quad(p)

    # ------------------------------------------------------------------ polygon fill
    def fill_tris(self, gm: GPUMesh, tri_ids, target: dict | object, brush: Brush, view: View,
                  erase=False, mask_value=None):
        """Fill whole triangles. target: layer tex dict (paint channels from the brush) or a single
        mask texture (mask_value)."""
        g = self.gpu
        ctx = g.ctx
        if isinstance(target, dict):
            keys = [c.key for c in paint_channels(brush)]
            if not keys:
                return
            p = g.program("fill_sparse_" + "".join(keys), S.UV_VS, channel_shader(S.BRUSH_PAINT_FS, keys))
            units = self._common(p, brush, view, None, None, gm.mesh.radius)
            units.update(self._map_units(p, brush, view, False, erase=erase))
            self._paint_values(p, brush, erase)
            g.bind(p, units)
            textures = [target[key] for key in keys]
            self._begin_draw(self._fbo("fill", textures), textures[0].size)
            ctx.enable(moderngl.BLEND)
            ctx.blend_equation = moderngl.FUNC_ADD
            ctx.blend_func = ERASE_BLEND if erase else PAINT_BLEND
            gm.render_tris(p, tri_ids)
            ctx.disable(moderngl.BLEND)
        else:
            p = self.p_mask
            units = self._common(p, brush, view, None, None, gm.mesh.radius)
            g.set(p, "u_direct", 1)
            g.set(p, "u_value", float(0.0 if erase else (1.0 if mask_value is None else mask_value)))
            g.bind(p, units)
            self._begin_draw(self._fbo("mfill", [target]), target.size)
            ctx.disable(moderngl.BLEND)
            gm.render_tris(p, tri_ids)

    def release(self):
        for f in self._fbos.values():
            f.release()
        self._fbos.clear()


# ---------------------------------------------------------------------------------- strokes
class Stroke:
    """Turns a stream of surface samples into dabs: lazy mouse, spacing, pressure, jitter,
    follow-path and symmetry. GPU work is delegated to the Painter."""

    def __init__(self, painter: Painter, gm: GPUMesh, subset, brush: Brush, view: View, radius_fn,
                 target: str, textures, quick=None, mask_value=1.0, clone_offset=None, seed=0):
        self.painter, self.gm, self.subset = painter, gm, subset
        self.brush = Brush()
        self.brush.load_dict(brush.to_dict())       # settings are frozen for the stroke
        if view.uv_mapping is not None:
            self.brush.alignment = 3
        self.view = view
        self.radius_fn = radius_fn
        self.target = target                         # "layer" | "mask" | "quick"
        self.textures = textures                     # dict key->tex (layer) or single texture
        self.quick = quick if target != "quick" else None
        self.mask_value = mask_value
        self.seed = int(seed) % (2 ** 32)
        self.rng = np.random.default_rng(self.seed)
        self.syms = symmetry_transforms(self.brush)
        b = self.brush
        self.tool = int(b.tool)
        self.erase = b.mode == 1
        self.direct = self.tool in (TOOL_SMUDGE, TOOL_CLONE)
        if b.user_channel and target == "layer" and self.tool != TOOL_PAINT:
            raise ValueError("User channel strokes support Paint and Erase; choose Paint")
        g = painter.gpu
        # Admit the complete initial working set before lazy raster allocation.
        # A late buffer-budget failure must not publish empty authored channels.
        itemsize = {"f1": 1, "f2": 2, "f4": 4}
        required = 0
        if target == "layer":
            channels = paint_channels(b)
            for channel in channels:
                if channel.key in textures:
                    texture = textures[channel.key]
                    size, components, dtype = texture.size, texture.components, texture.dtype
                else:
                    size = (textures.resolution, textures.resolution)
                    components, dtype = channel.paint_components, channel.paint_dtype
                    required += size[0] * size[1] * components * itemsize[dtype]
                required += size[0] * size[1] * components * itemsize[dtype]
                if not self.direct:
                    required += size[0] * size[1] * max(4, channel.paint_components) * itemsize[channel.paint_dtype]
        else:
            required = textures.size[0] * textures.size[1] * (textures.components * itemsize[textures.dtype] + (0 if self.direct else 2))
        g.memory.check(required)
        if target == "layer":
            channels = paint_channels(b)
            if hasattr(textures, "ensure"):
                textures.ensure([c.key for c in channels])
            self.snapshot = {channel.key: g.clone(textures[channel.key], purpose="stroke snapshot/" + channel.key) for channel in channels}
            if not self.direct:
                size = textures[channels[0].key].size
                # Brush shader outputs remain vec4, including scalar value/coverage channels.
                self.buffers = [g.texture(size, max(4, channel.paint_components), dtype=channel.paint_dtype, purpose="stroke buffer/" + channel.key)
                                for channel in channels]
                for t in self.buffers:
                    g.fill(t, (0, 0, 0, 0))
        else:
            self.snapshot = {"mask": g.clone(textures)}
            if not self.direct:
                self.buffers = [g.texture(textures.size, 1, dtype="f2")]
                g.fill(self.buffers[0], (0, 0, 0, 0))
        if self.direct:
            self.buffers = []
        self.clone_offset = np.zeros(2) if clone_offset is None else np.asarray(clone_offset, float)
        self.last = None            # last dab surface
        self.lazy = None
        self.carry = 0.0
        self.changed = False
        self.dabs = 0
        self.last_px = None
        self.recorded_views, self.recorded_samples, self.recorded_dabs = [], [], []
        self.started_at = time.monotonic()

    def _record_view(self):
        from .journal import view_record
        view = view_record(self.view)
        if not self.recorded_views or view != self.recorded_views[-1]:
            self.recorded_views.append(view)
        return len(self.recorded_views) - 1

    def _record_sample(self, surface, event):
        self.recorded_samples.append({"event": event, "seconds": time.monotonic() - self.started_at,
                                      "view": self._record_view(), "position": np.asarray(surface.pos).tolist(),
                                      "normal": np.asarray(surface.nrm).tolist(), "uv": np.asarray(surface.uv).tolist(),
                                      "triangle": int(surface.tri), "pressure": float(surface.pressure)})

    # -- input
    def start(self, s: Surface):
        self._record_sample(s, "start")
        self.lazy = s.pos.copy()
        self.last = s
        self._dab(s, None)

    def feed(self, s: Surface):
        self._record_sample(s, "feed")
        b = self.brush
        if self.last is None:
            self.start(s)
            return
        if b.lazy > 0:
            lazy_w = b.lazy * self.view.wpp(s.pos)
            d = float(np.linalg.norm(s.pos - self.lazy))
            if d <= lazy_w:
                return
            self.lazy = self.lazy + (s.pos - self.lazy) * (1 - lazy_w / d)
            s = Surface(self.lazy.copy(), s.nrm, s.uv, s.tri, s.pressure)
        last = self.last
        seg = s.pos - last.pos
        dist = float(np.linalg.norm(seg))
        r = self._radius(s.pos, s.tri, s.pressure)
        step = max(b.spacing * r * 2, 1e-6)
        if dist > r * 6 and b.lazy <= 0:      # jumped across the model: restart instead of streaking
            self.last, self.carry = s, 0.0
            self._dab(s, None)
            return
        t = step - self.carry
        while t <= dist:
            f = t / max(dist, 1e-12)
            q = Surface(last.pos + seg * f, normalize(last.nrm * (1 - f) + s.nrm * f),
                        last.uv * (1 - f) + s.uv * f, s.tri, last.pressure * (1 - f) + s.pressure * f)
            self._dab(q, seg)
            t += step
        self.carry = dist - (t - step)
        self.last = Surface(s.pos, s.nrm, s.uv, s.tri, s.pressure)

    def _radius(self, pos, tri, pressure):
        b = self.brush
        r = self.radius_fn(pos, tri)
        if b.pressure_size:
            r *= b.min_size + (1 - b.min_size) * float(np.clip(pressure, 0, 1))
        return r

    # -- dab construction
    def _make_dab(self, s: Surface, direction) -> Dab:
        b, v, rng = self.brush, self.view, self.rng
        r = self._radius(s.pos, s.tri, s.pressure)
        if b.size_jitter > 0:
            r *= 1 - b.size_jitter * rng.random()
        flow = b.flow
        if b.flow_jitter > 0:
            flow *= 1 - b.flow_jitter * rng.random()
        if b.pressure_flow:
            flow *= b.min_flow + (1 - b.min_flow) * float(np.clip(s.pressure, 0, 1))
        N = normalize(s.nrm)
        ref = v.right
        if b.follow_path and direction is not None and np.linalg.norm(direction) > 1e-12:
            ref = direction
        T = ref - N * np.dot(ref, N)
        if np.linalg.norm(T) < 1e-8:
            T = np.cross(N, [0, 1, 0] if abs(N[1]) < 0.9 else [1, 0, 0])
        T = normalize(T)
        B = np.cross(N, T)
        angle = math.radians(b.angle)
        if b.angle_jitter > 0:
            angle += b.angle_jitter * (rng.random() * 2 - 1) * math.pi
        hit = np.asarray(s.pos, float)
        if b.pos_jitter > 0:
            a = rng.random() * 2 * math.pi
            hit = hit + (T * math.cos(a) + B * math.sin(a)) * r * b.pos_jitter * rng.random()
        px = v.project(hit)
        if px is None:
            px = np.zeros(2)
        rpx = r / max(v.wpp(hit), 1e-12)
        cam_angle = angle
        if b.alignment == 0 and b.follow_path and direction is not None:
            p0 = v.project(hit - direction)
            if p0 is not None:
                d = px - p0
                if np.linalg.norm(d) > 1e-6:
                    cam_angle += math.atan2(d[1], d[0])
        topo = self.gm.mesh.topology
        uvs = topo.uv_scale(s.tri) if 0 <= s.tri < topo.n_tris else 1.0
        if v.uv_mapping is not None:
            if b.follow_path and direction is not None and np.linalg.norm(direction[:2]) > 1e-9:
                angle += math.atan2(direction[1], direction[0])
            return Dab(hit=hit, radius=r, frame=(T, B, N), rot=(math.cos(angle), math.sin(angle)),
                       hit_px=px, radius_px=rpx, hit_uv=hit[:2], radius_uv=r, flow=float(flow), occl=False)
        rot_a = cam_angle if b.alignment == 0 else angle
        return Dab(hit=hit, radius=r, frame=(T, B, N), rot=(math.cos(rot_a), math.sin(rot_a)),
                   hit_px=px, radius_px=rpx, hit_uv=np.asarray(s.uv, float), radius_uv=r / max(uvs, 1e-9),
                   flow=float(flow))

    def _dab(self, s: Surface, direction):
        d = self._make_dab(s, direction)
        copies = [d] + [Dab(**{**d.__dict__, "sym_inv": np.linalg.inv(S_), "occl": False}) for S_ in self.syms]
        view_index = self._record_view()
        for dab in copies:
            values = {key: (value.tolist() if isinstance(value, np.ndarray) else
                           [np.asarray(item).tolist() for item in value] if key == "frame" else value)
                      for key, value in dab.__dict__.items()}
            self.recorded_dabs.append({"view": view_index, "values": values})
        pt, b = self.painter, self.brush
        for dab in copies:
            if self.direct:
                if self.tool == TOOL_SMUDGE:
                    off = np.zeros(2) if self.last_px is None else -(d.hit_px - self.last_px) * b.smudge_strength * 4.0
                else:
                    off = self.clone_offset
                targets, sources = self._sample_targets()
                pt.dab_sample(self.gm, self.subset, targets, sources, b, self.view, dab, self.quick, off)
            elif self.target == "layer":
                pt.dab_paint(self.gm, self.subset, self.buffers, b, self.view, dab, self.quick,
                             projection=self.tool == TOOL_PROJECTION)
            else:
                pt.dab_mask(self.gm, self.subset, self.buffers[0], b, self.view, dab, self.quick)
        self.last_px = d.hit_px
        self.dabs += 1
        self.changed = True

    def _sample_targets(self):
        clone = self.tool == TOOL_CLONE
        if self.target == "layer":
            keys = [channel.key for channel in paint_channels(self.brush)]
            return ([self.textures[k] for k in keys],
                    [self.snapshot[k] if clone else None for k in keys])
        return [self.textures], [self.snapshot["mask"] if clone else None]

    # -- merge into the target
    def apply(self):
        if not self.changed or self.direct:
            self.changed = False
            return
        b = self.brush
        if self.target == "layer":
            self.painter.apply_paint(self.textures, self.snapshot, self.buffers, b.stroke_opacity, self.erase)
        else:
            value = 0.0 if self.erase else float(self.mask_value)
            self.painter.apply_mask(self.textures, self.snapshot["mask"], self.buffers[0], b.stroke_opacity, value)
        self.changed = False

    def release(self, keep_snapshot=False):
        """Free stroke buffers. Returns the snapshot (for undo) unless released too."""
        self.painter.forget_textures(self.buffers)
        for t in self.buffers:
            t.release()
        self.buffers = []
        snap = self.snapshot
        if not keep_snapshot:
            for t in snap.values():
                t.release()
            snap = None
        self.snapshot = None
        return snap
