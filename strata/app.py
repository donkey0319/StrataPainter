"""Desktop front end: GLFW window, Dear ImGui panels, viewport input.

The layout mirrors Substance 3D Painter's default workspace so Painter users can work without
re-learning where things are:

    +------------------------------------------------------------------------------+
    | File  Edit  Layer  Viewport  Window  Help                 [Search  Ctrl+K]   |  main menu
    | Paint | Size  Flow  Hardness  Spacing | Target: Layer/Mask | ...    Export   |  tool options
    +--+----------+--------------------------------------+-------------------+--+
    |T | Assets   |                                      | Texture Set List  |D |
    |o | (smart   |          3D / 2D viewport            +-------------------+o |
    |o |  mats,   |       (F1 split, F2 3D, F3 2D)       | Layer Stack | TSS |c |
    |l |  mats,   |                                      +-------------------+k |
    |s |  gens)   |                                      | Properties        |  |
    +--+----------+--------------------------------------+-------------------+--+
    | status / hints                                                     fps     |
    +------------------------------------------------------------------------------+

Every panel is a docking window: drag tabs to rearrange, Window > Reset Layout to go back.
All actions live in one command registry (ui/commands.py), which feeds the menus, the
keyboard shortcuts, the Ctrl+K command palette and the rebindable Shortcuts window.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import sys
import time
import traceback

import glfw
import moderngl
import numpy as np
from imgui_bundle import imgui
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer

from .engine import Engine
from . import exporter as texture_exporter
from .baker import BakeSettings
from .channels import CHANNEL_DESCRIPTORS
from .layers import BLEND_MODES, CHANNELS, GENERATORS, HEIGHT_BLEND, STENCIL_TILING, SYMMETRY, MASK_EFFECTS, CONTENT_EFFECTS
from .layers import _ids as _layer_ids
from .painter import TOOL_CLONE, TOOL_PAINT, TOOL_PROJECTION, TOOL_SMUDGE, stencil_matrix
from .mesh import BUILTIN_MESHES, load_mesh
from .presets import MATERIALS, SMART_MATERIALS
from .renderer import DISPLAY_MODES
from .materialpreview import MaterialPreviews
from .presets import fill as preset_fill
from .ui.commands import Chord, Palette, Registry, capturable_keys
from .ui.theme import (ACCENT, FILL_COL, ICON, PAINT_COL, SEL_BG, SEL_BG_HI, SEL_BG_SOFT, TEXT_DIM, V2, V4,
                       WARN_COL, apply_theme,
                       col32, load_fonts)
from .ui.uvview import UVView
from .ui.brushpreview import BrushPreview
from .ui.project import ProjectUI
from .ui.material import MaterialUI
from .ui.effects import EffectsUI
from .ui.export import ExportUI
from .ui.bake import BakeUI
from .ui.imports import ImportUI
from .ui.authored import AuthoredUI
from .ui.channels import ChannelsUI
from .ui.delivery import DeliveryUI
from . import authored as authored_model
from .ui.native import NativeUI
from .ui.memory import MemoryUI
from .ui.tiles import TilesUI
from .ui.assistant import AssistantUI
from .tablet import TabletInput
from .resources import BUILTIN_ALPHAS
from .layers import ALIGNMENTS
from .viewinput import ViewInput
from .substance import importer as sp_import
from .substance import library as sp_library

try:
    from imgui_bundle import portable_file_dialogs as pfd
except Exception:  # pragma: no cover
    pfd = None

APP = "Strata"
RESOLUTIONS = [512, 1024, 2048, 4096]
MESH_EXTS = ["*.obj", "*.fbx", "*.gltf", "*.glb"]
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".strata")
LAYOUT_VERSION = 1

# panel names match Painter's
W_ASSETS, W_TSL, W_LAYERS, W_TSS, W_PROPS = "Assets", "Texture Set List", "Layer Stack", "Texture Set Settings", "Properties"
W_DISPLAY, W_HISTORY, W_LOG, W_KEYS, W_SETTINGS = "Display Settings", "History", "Log", "Shortcuts", "Settings"
W_AI = "AI Assistant"
DOCKED = [W_ASSETS, W_TSL, W_LAYERS, W_TSS, W_PROPS, W_AI]
FLOATING = [W_DISPLAY, W_HISTORY, W_LOG, W_KEYS, W_SETTINGS]

VIEW_3D, VIEW_SPLIT, VIEW_2D = 0, 1, 2
TOOL_FILL = 4                         # polygon fill is a UI tool; the engine's brush tools are 0-3
CHANNEL_MODES = [1, 2, 3, 4, 5, 10, 11]          # C / Shift+C: material channels
MESHMAP_MODES = [7, 8, 12, 13, 14, 15]           # B / Shift+B: baked mesh maps
FILL_MODES = ["Triangle", "Polygon", "UV island", "Mesh part", "Texture set"]
NA = "Not available yet"              # category for Painter shortcuts whose feature Strata lacks
CONTENT_FIELDS = ("color", "rough", "metal", "height", "normal", "emissive", "opac", "enabled",
                  "variation", "bump", "var_scale", "seed", "maps", "proj")
BLEND_SHORT = {"Normal": "Norm", "Multiply": "Mult", "Screen": "Scrn", "Overlay": "Ovrl", "Add": "Add"}
GEN_INFO = {
    1: "Wear along convex edges, driven by the baked curvature.",
    2: "Dirt that collects in cavities (ambient occlusion + concavity).",
    3: "The baked ambient occlusion, as a mask.",
    4: "Dust settling on upward-facing surfaces.",
    5: "Gradient along the mesh height (bottom to top).",
    6: "Procedural noise breakup.",
}
MOUSE_HELP = [
    ("Paint", "Left mouse"),
    ("Straight line from the last stroke", "Shift + Left click"),
    ("Straight line, snapped to 15 degree steps", "Ctrl + Shift + Left click"),
    ("Orbit", "Alt + Left drag   (or Right drag)"),
    ("Snap to axis views (front, side, top...)", "Alt + Shift + Left drag, or click the axis gizmo"),
    ("Resize the 3D and 2D views", "Drag the divider between them"),
    ("Pan", "Alt + Middle drag,  Ctrl + Alt + Left drag,  or Middle drag"),
    ("Zoom", "Alt + Right drag,  wheel,  or Alt + wheel"),
    ("Brush size / hardness", "Ctrl + Right drag  (horizontal / vertical)"),
    ("Brush flow / angle", "Ctrl + Left drag  (horizontal / vertical)"),
    ("Brush size (wheel)", "Ctrl + wheel"),
    ("Rotate light", "Shift + Right drag"),
    ("Stencil / projection image", "S + Left drag rotate (Shift snaps), S + Middle move, S + Right scale"),
    ("Clone source", "V + Left click"),
    ("Pick the texture set under the cursor", "Ctrl + Alt + Right click"),
    ("Quick brush settings", "Right click (no drag)"),
    ("Show a layer's mask in the viewport", "Alt + click its mask thumbnail"),
    ("Disable / enable a layer's mask", "Shift + click its mask thumbnail"),
    ("Paint a mask", "Click the layer's mask thumbnail"),
    ("Select several layers", "Ctrl + click, Shift + click"),
    ("2D view", "Alt+Left rotate (Shift snaps), Alt+Middle pan, Alt+Right zoom, wheel zoom"),
    ("Open a file", "Drag .obj / .fbx / .gltf / .strata / .spp onto the window"),
    ("Use a Painter smart material", "Drag a .spsm onto the window, or use Assets > Substance"),
    ("Add a material / smart material", "Double-click it in Assets, or drag it onto the Layer Stack"),
]


def _tip(text):
    """Tooltip for the last item (shows on disabled items too). '%' is escaped for the printf API."""
    if text:
        imgui.set_item_tooltip(text.replace("%", "%%"))


def _esc_closes():
    """Keyboard navigation is off (Tab is a Painter shortcut), so popups handle Esc themselves."""
    if imgui.is_key_pressed(imgui.Key.escape):
        imgui.close_current_popup()


def _ellipsize(text, width):
    if imgui.calc_text_size(text).x <= width:
        return text
    while text and imgui.calc_text_size(text + "...").x > width:
        text = text[:-1]
    return text + "..."


# brush size spaces, in the engine's order (Brush.size_space): label, slider range, format
SIZE_SPACE_UI = [("Screen", "pixels: the circle keeps its size on screen when you zoom", 2.0, 800.0, "%.0f px"),
                 ("World", "a fraction of the mesh: the circle keeps its size on the mesh when you zoom", 0.1, 100.0, "%.1f %%"),
                 ("UV", "a fraction of the texture: same texel coverage everywhere", 0.1, 100.0, "%.1f %%")]


class BrushSize:
    """The brush size in whichever space the brush uses, as one value the UI can edit:
    screen pixels, or percent of the mesh size (world) or of the UV square."""

    def __init__(self, get_brush):
        self._get = get_brush            # the engine may swap its Brush (presets, projects)

    @property
    def b(self):
        return self._get()

    @property
    def spec(self):
        return SIZE_SPACE_UI[int(self.b.size_space) if 0 <= int(self.b.size_space) < 3 else 0]

    @property
    def value(self):
        sp = int(self.b.size_space)
        return self.b.size_obj * 100 if sp == 1 else self.b.size_uv * 100 if sp == 2 else self.b.size_px

    @value.setter
    def value(self, v):
        _, _, lo, hi, _ = self.spec
        v = float(np.clip(v, lo, hi))
        sp = int(self.b.size_space)
        if sp == 1:
            self.b.size_obj = v / 100
        elif sp == 2:
            self.b.size_uv = v / 100
        else:
            self.b.size_px = v

    def scale(self, k):
        self.value = self.value * k

    def text(self):
        return self.spec[4] % self.value


class App:
    def __init__(self, width=1600, height=960):
        if not glfw.init():
            raise RuntimeError("Could not initialise GLFW")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
        glfw.window_hint(glfw.SAMPLES, 4)
        self.window = glfw.create_window(width, height, APP, None, None)
        if not self.window:
            raise RuntimeError("Could not create an OpenGL 3.3 window")
        glfw.make_context_current(self.window)
        glfw.swap_interval(1)
        self.ctx = moderngl.create_context()
        try:
            self.ctx.enable_direct(0x809D)  # GL_MULTISAMPLE
        except Exception:
            pass

        self._load_settings()
        imgui.create_context()
        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.docking_enable
        io.config_windows_move_from_title_bar_only = True
        self.ini_path = ""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            self.ini_path = os.path.join(CONFIG_DIR, "layout.ini")
        except Exception:
            pass
        io.set_ini_filename(self.ini_path)
        self.need_layout = (self.settings.get("layout_version") != LAYOUT_VERSION
                            or not (self.ini_path and os.path.exists(self.ini_path)))

        load_fonts(15.0)
        apply_theme()
        scale = self.settings.get("ui_scale")
        if not scale:
            try:
                scale = glfw.get_window_content_scale(self.window)[0]   # follow Windows display scaling
            except Exception:
                scale = 1.0
        self.ui_scale = 1.0
        self._set_ui_scale(float(np.clip(scale, 0.75, 2.0)), save=False)
        self.impl = GlfwRenderer(self.window)
        # the Python GLFW backend ignores ImGui's cursor requests; _apply_cursor() does it instead,
        # so panel splitters, window edges and table columns show resize arrows
        imgui.get_io().backend_flags |= imgui.BackendFlags_.has_mouse_cursors
        self._glfw_cursors, self._cur_cursor = {}, None
        glfw.set_drop_callback(self.window, self._on_drop)
        glfw.set_window_close_callback(self.window, self._on_close_request)
        self.tablet = TabletInput()
        self.tablet.attach(self.window)

        self.engine = Engine(self.ctx)
        self.bsize = BrushSize(lambda: self.engine.brush)
        self.engine.brush.size_space = int(self.settings.get("brush_space", 1))     # World by default
        self.uv = UVView(self.engine.gpu)
        self.project_path = None
        self.status, self.status_t = "", 0.0
        self.log = []
        self.pending = None          # (label, callable) run after a 'working' frame is shown
        self._pending_shown = 0
        self.drag = None
        self.drag_start = None
        self.cursor = None
        self.vp_rect = (0, 0, 1, 1)  # 3D view, screen coords (x, y-down, w, h)
        self.uv_rect = (0, 0, 0, 0)  # 2D view
        self.fb_scale = (1.0, 1.0)
        self.fps = 0.0
        # panels / view state
        self.show = {w: True for w in DOCKED}
        self.show.update({w: False for w in FLOATING})
        self.show.update({k: v for k, v in self.settings.get("show", {}).items() if k in self.show})
        self.view_mode = int(self.settings.get("view_mode", VIEW_SPLIT))
        self.ui_hidden = False
        self.thumb = int(self.settings.get("thumb", 64))
        self.asset_query, self.asset_sel = "", None
        self.prop_filter, self._flt, self._sec_match = "", "", False
        self.sel_uids, self._last_primary, self._anchor = set(), None, -1
        self.renaming, self.rename_buf, self._rename_focus = None, "", False
        self.rebind, self.keys_filter = None, ""
        self.quick_open = False
        self._focus_layers = 0
        # tools and modes behind Painter's shortcuts
        self.poly_fill, self.fill_mode, self.clone_absolute = False, 2, False
        self.layer_channel = 0  # 0: all channels; 1..7: one channel's blend and opacity
        self.workspace_mode = "paint"
        self._hover_set = None
        self.lazy_last, self.sym_last = 25.0, 1
        self.quick_edit, self._prev_target = False, 0
        self.paused, self.isolate, self.view_swap = False, False, False
        self.split_frac = float(np.clip(self.settings.get("split_frac", 0.5), 0.15, 0.85))  # 3D/2D divider
        self._split_hit = None            # (x, y0, y1) of the divider while both views show
        self._gizmo = None                # [(axis, x, y, r)] clickable axis ends of the view gizmo
        self._wire_hl = None              # (mesh id, tri, mode, set) -> highlighted polygon-fill triangles
        self.clipboard, self.content_clip = [], None
        self._last_hit, self._resume = None, False
        self._last_uv_hit = None
        self.open_bake = self.open_close = False
        self.open_quit, self._quit_ok, self._close_unsaved = False, False, False
        self.bake_settings, self.bake_all = None, True
        self._strip_btn_pos = {}
        self.dock_id = 0
        # dialogs
        self.open_new = False
        self.open_export = False
        self.open_help = False       # kept for scripts/tests: opens the Shortcuts window
        self.new_mesh_idx, self.new_res_idx, self.new_path = 0, 2, ""
        self.new_color_mode = self.new_tangent_basis = 0
        self.new_auto_uv = self.new_uv_regenerate = False
        self.new_uv_method = self.new_unit = 0
        self.new_uv_tiles = 1
        self.new_uv_padding, self.new_uv_info = 8, ""
        self.new_uv_angle, self.new_uv_rotate = 66., True
        self.export_preset, self.export_dir = 0, os.path.abspath("export")
        self.export_name, self.export_open_folder = "", True
        self.export_templates = ["Unreal Engine (Packed)"] + [
            n for n in texture_exporter.OUTPUT_TEMPLATES if n != "Unreal Engine (Packed)"]
        self.export_custom_template = None
        self.export_template_json = ""
        self.export_format, self.export_depth, self.export_size = "", "", None
        self.export_padding, self.export_dilation = "infinite", 16
        self.export_sets, self.export_set_identity = {}, None
        self.export_overrides = {}

        self.project_ui = ProjectUI(self, CONFIG_DIR, pfd)
        self.material_ui = MaterialUI(self)
        self.effects_ui = EffectsUI(self)
        self.export_ui = ExportUI(self)
        self.export_results = []
        self.export_results_requested = False
        self.bake_ui = BakeUI(self)
        self.import_ui = ImportUI(self)
        self.authored_ui = AuthoredUI(self)
        self.channels_ui = ChannelsUI(self)
        self.delivery_ui = DeliveryUI(self)
        self.native_ui = NativeUI(self)
        self.memory_ui = MemoryUI(self)
        self.tiles_ui = TilesUI(self)
        self.assistant_ui = AssistantUI(self, CONFIG_DIR)
        self._fill_projection_drag = None
        self.palette = Palette()
        self._assets = ([("smart", n) for n in SMART_MATERIALS] + [("mat", n) for n in MATERIALS]
                        + [("gen", k) for k in range(1, len(GENERATORS))])
        self._smart_cache = {n: SMART_MATERIALS[n]() for n in SMART_MATERIALS}
        # Substance Painter assets found on disk, and .spp import state
        self.sp_items, self.sp_folders = [], []
        self.sp_thumbs, self.sp_cache = {}, {}
        self.sp_loader = None
        self.sp_kind = 0                 # Assets > Substance: 0 smart materials, 1 smart masks
        self.spp_info, self.spp_set, self.open_spp = None, 0, False
        self.report, self.open_report = None, False
        self.busy_detail = ""
        self._scan_substance()
        self._build_commands()
        self.reg.overrides = {k: list(v) for k, v in self.settings.get("keys", {}).items()}

        self._run_busy("Baking Rounded Cube...", lambda: self._new_project("Rounded Cube", 2048))

    # ------------------------------------------------------------------ settings
    def _load_settings(self):
        try:
            with open(os.path.join(CONFIG_DIR, "settings.json")) as f:
                self.settings = json.load(f)
        except Exception:
            self.settings = {}

    def _save_settings(self):
        self.settings.update({"ui_scale": self.ui_scale, "layout_version": LAYOUT_VERSION,
                              "show": self.show, "view_mode": self.view_mode, "thumb": self.thumb,
                              "split_frac": self.split_frac,
                              "keys": self.reg.overrides})
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(os.path.join(CONFIG_DIR, "settings.json"), "w") as f:
                json.dump(self.settings, f, indent=1)
        except Exception:
            pass

    def _set_ui_scale(self, scale, save=True):
        scale = float(np.clip(scale, 0.75, 2.0))
        style = imgui.get_style()
        style.scale_all_sizes(scale / self.ui_scale)
        style.font_scale_main = scale
        self.ui_scale = scale
        if save:
            self._save_settings()

    # ------------------------------------------------------------------ helpers
    def msg(self, text):
        self.status, self.status_t = text, time.time()
        self.log.append((time.strftime("%H:%M:%S"), text))
        del self.log[:-300]
        print(text)

    def _run_busy(self, label, fn, detail="Baking AO and curvature on the GPU"):
        self.pending = (label, fn)
        self.busy_detail = detail
        self._pending_shown = 0

    def _new_project(self, mesh, res):
        self.workspace_mode = "paint"
        self._last_uv_hit = None
        self._finish_fill_projection(cancel=True)
        self._finish_property_edit()
        t = time.time()
        self.engine.new_project(mesh, res, color_settings={"mode": "managed" if self.new_color_mode else "legacy"},
                                tangent_basis="mikk" if self.new_tangent_basis else "legacy",
                                uv_settings={"method": "angle" if self.new_uv_method else "smart",
                                             "preserve_valid": not self.new_uv_regenerate, "padding_px": self.new_uv_padding,
                                             "angle_degrees": self.new_uv_angle, "rotate": self.new_uv_rotate,
                                             "resolution": int(res), "tile_count": self.new_uv_tiles} if self.new_auto_uv else None,
                                source_unit=[None, "m", "cm", "mm", "in", "ft"][self.new_unit])
        self.export_ui.restore()
        self.material_ui.transform_tool = None
        self.material_ui.transform_layer_pid = None
        self.project_path = None
        self.uv.reset()
        name = mesh if isinstance(mesh, str) else mesh.name
        self.msg(f"New project: {name} @ {res}px  (baked in {time.time() - t:.1f}s)")
        uv = self.engine.mesh.uvs
        if uv.min() < -1e-3 or uv.max() > 1.001:
            for ts in self.engine.sets:
                coordinates = uv[self.engine.mesh.indices[ts.tri_ids]]
                if ts.tiles is None and (coordinates.min() < -1e-3 or coordinates.max() > 1.001):
                    self.msg("This mesh has UVs outside 0-1. Supported UDIM pages can be painted after enabling material tiles.")
                    break

    def _on_drop(self, window, paths):
        if not paths:
            return
        p = paths[0]
        ext = os.path.splitext(p)[1].lower()
        if ext == ".strata" or re.search(r"\.strata\.bak[0-9]+$", p, re.IGNORECASE):
            self._run_busy("Opening project...", lambda: self._open(p))
        elif ext in (".obj", ".fbx", ".gltf", ".glb"):
            self.new_path, self.new_mesh_idx = p, len(BUILTIN_MESHES)
            self.open_new = True
        elif ext in sp_import.PROJECT_EXTS:
            self._begin_spp(p)
        elif ext in sp_import.SMART_MATERIAL_EXTS:
            if self.engine.comp is None:
                self.msg("Open or create a project first, then drop the smart material.")
            else:
                self._add_sp_smart(p)
        elif ext in sp_import.SMART_MASK_EXTS:
            if self._lay_ok() is True:
                self._apply_sp_mask(p)
            else:
                self.msg("Select a layer first, then drop the smart mask on the window.")
        elif ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".bmp", ".exr", ".hdr"):
            self.material_ui.import_resources(paths)
        else:
            self.msg(f"Can't open {os.path.basename(p)}: unsupported file type")

    def _open(self, path):
        self._finish_fill_projection(cancel=True)
        self._finish_property_edit()
        self.engine.load(path)
        self.export_ui.restore()
        self.workspace_mode = "paint"
        self._last_uv_hit = None
        self.material_ui.transform_tool = None
        self.material_ui.transform_layer_pid = None
        backup = re.search(r"\.bak[0-9]+$", os.fspath(path), re.IGNORECASE)
        self.project_path = os.fspath(path)[:backup.start()] if backup else path
        if backup:
            self.engine.mark_modified()
        self._release_clip()
        self.sel_uids, self._last_primary = set(), None
        self.project_ui.last_snapshot = None
        self.uv.reset()
        self.msg(f"{'Recovered backup' if backup else 'Opened'} {os.path.basename(path)}")
        for diagnostic in getattr(self.engine, "project_diagnostics", []):
            self.msg(str(diagnostic.get("message", diagnostic)))

    def _save(self, save_as=False, portable=False):
        self._finish_fill_projection()
        self._finish_property_edit()
        path = self.project_path
        if save_as or not path:
            if pfd is None:
                self.msg("File dialogs unavailable"); return False
            path = pfd.save_file("Save project", "untitled.strata", ["Strata project", "*.strata"]).result()
            if not path:
                return False
            if not path.lower().endswith(".strata"):
                path += ".strata"
        try:
            self.engine.save(path, portable=portable, backups=self.project_ui.backups)
            self.project_path = path
            self.msg(f"Saved {'portable project ' if portable else ''}{path}")
            return True
        except Exception as e:
            self.msg(f"Save failed: {e}")
            return False

    # ------------------------------------------------------------------ quitting
    def _on_close_request(self, window):
        """Window close button / Alt+F4 / File > Quit: when the project has unsaved changes, keep
        the window open and ask whether to save first (the "Unsaved Changes" dialog)."""
        if self._quit_ok:
            return
        try:
            unsaved = self.engine.modified
        except Exception:
            traceback.print_exc()
            unsaved = False
        if unsaved:
            glfw.set_window_should_close(window, False)
            self.open_quit = True

    def _request_quit(self):
        glfw.set_window_should_close(self.window, True)
        self._on_close_request(self.window)

    def _quit_now(self):
        self._quit_ok = True
        glfw.set_window_should_close(self.window, True)

    def _ask_open(self):
        if pfd is None:
            self.msg("File dialogs unavailable"); return
        r = pfd.open_file("Open project", "", ["Strata project and backups", "*.strata *.strata.bak*"]).result()
        if r:
            self._run_busy("Opening project...", lambda: self._open(r[0]))

    def _ask_mesh(self):
        if pfd is None:
            return ""
        r = pfd.open_file("Import mesh", "", ["Meshes", " ".join(MESH_EXTS)]).result()
        return r[0] if r else ""

    # ------------------------------------------------------------------ Substance Painter files
    def _scan_substance(self):
        try:
            self.sp_items, self.sp_folders = sp_library.scan(self.settings.get("substance_folders", []))
        except Exception as e:
            self.sp_items, self.sp_folders = [], []
            self.msg(f"Couldn't scan for Substance assets: {e}")

    def _sp_thumb(self, path):
        """GPU texture of a Painter shelf thumbnail, or None while it loads."""
        if path in self.sp_thumbs:
            return self.sp_thumbs[path]
        if self.sp_loader is None:
            self.sp_loader = sp_library.ThumbLoader()
        self.sp_loader.request(path)
        return None

    def _poll_thumbs(self):
        if self.sp_loader is None:
            return
        for path, img in self.sp_loader.poll():
            tex = None
            if img is not None:
                tex = self.ctx.texture((img.shape[1], img.shape[0]), 4, np.ascontiguousarray(img).tobytes())
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.sp_thumbs[path] = tex

    def _sp_result(self, path):
        """Converted smart material / mask (cached per file)."""
        key = (path, os.path.getmtime(path) if os.path.exists(path) else 0)
        if key not in self.sp_cache:
            kind = sp_import.kind_of(path)
            self.sp_cache[key] = sp_import.load_smart_mask(path) if kind == "smart_mask" \
                else sp_import.load_smart_material(path)
        return self.sp_cache[key]

    def _log_notes(self, notes):
        for n in notes:
            self.log.append((time.strftime("%H:%M:%S"), "   - " + n))
        del self.log[:-300]

    def _add_sp_smart(self, path, index=None):
        try:
            res = self._sp_result(path)
        except Exception as e:
            traceback.print_exc()
            self.msg(f"Couldn't read {os.path.basename(path)}: {e}")
            return
        if not res.layers:
            self.msg(f"{res.name}: nothing Strata can show (see Log)")
            self._log_notes(res.notes)
            return
        import copy
        fresh = copy.copy(res)
        fresh.layers = [copy.deepcopy(il) for il in res.layers]     # every drop gets its own layers
        for il in fresh.layers:
            il.layer.uid = next(_layer_ids)
        def apply():
            self.engine.add_imported(fresh, index=index, progress=self.import_ui.progress, max_dabs=self.import_ui.max_dabs, per_layer=self.import_ui.per_layer)
            self.engine.brush.target = 0
            n = len(res.notes)
            self.msg(f"Added Substance smart material: {res.name}" + (f"  ({n} approximation{'s' if n > 1 else ''}, see Log)" if n else ""))
            self._log_notes(res.notes)
        self.import_ui.run(apply)

    def _apply_sp_mask(self, path, idx=None, replace=False):
        try:
            sm = self._sp_result(path)
        except Exception as e:
            traceback.print_exc()
            self.msg(f"Couldn't read {os.path.basename(path)}: {e}")
            return
        if sm.mask is None:
            self.msg(f"{sm.name}: no mask Strata can use (see Log)")
        else:
            def apply():
                if self.engine.apply_mask_state(sm.mask, idx, replace=replace, report=sm.report, progress=self.import_ui.progress, max_dabs=self.import_ui.max_dabs, per_layer=self.import_ui.per_layer):
                    self.msg(f"Applied Substance smart mask: {sm.name}")
            self.import_ui.run(apply)
        self._log_notes(sm.notes)

    def _begin_spp(self, path):
        try:
            self.spp_info = sp_import.inspect_project(path)
        except Exception as e:
            traceback.print_exc()
            self.msg(f"Couldn't read {os.path.basename(path)}: {e}")
            return
        self.spp_set = 0
        self.open_spp = True

    def _import_spp(self, info, set_index):
        def job():
            t = time.time()
            proj = sp_import.load_project(info.path, set_index)
            self.import_ui.cancelled=False
            dabs = self.engine.import_painter_project(proj, progress=self.import_ui.progress, max_dabs=self.import_ui.max_dabs, per_layer=self.import_ui.per_layer)
            self.project_path = None
            self.uv.reset()
            rep_ = self.engine.last_replay
            lines = list(proj.result.notes)
            if rep_ is not None and rep_.truncated:
                lines.insert(0, f"Very long paint history: replay paused at a saved checkpoint after {rep_.dabs} brush dabs")
            if rep_ is not None and rep_.skipped:
                lines.append(f"{rep_.skipped} strokes had missing camera data or no surface samples and were skipped")
            n_sets = len(self.engine.sets)
            n_layers = sum(len(list(self.engine.all_layers(ts))) for ts in self.engine.sets)
            summary = (f"{proj.name}: {n_sets} texture set{'s' if n_sets != 1 else ''}, {n_layers} layers, "
                       f"{dabs} brush dabs replayed, {time.time() - t:.1f}s")
            self.msg("Imported " + summary)
            self._log_notes(lines)
            self.report = (f"Imported {os.path.basename(info.path)}", summary, lines,
                           [l.name for l in self.engine.layers][::-1])
            self.open_report = True
        self._run_busy(f"Importing {os.path.basename(info.path)}...", job,
                       "Baking mesh maps and replaying paint strokes")

    def _ask_import_spp(self):
        if pfd is None:
            self.msg("File dialogs unavailable"); return
        r = pfd.open_file("Import Substance Painter project", "", ["Substance Painter project", "*.spp"]).result()
        if r:
            self._begin_spp(r[0])

    def _ask_import_preset(self):
        if pfd is None:
            self.msg("File dialogs unavailable"); return
        r = pfd.open_file("Import smart material or smart mask", "",
                          ["Substance smart materials and masks", "*.spsm *.spmsk"]).result()
        if r:
            self._on_drop(None, [r[0]])

    def _add_sp_folder(self):
        if pfd is None:
            self.msg("File dialogs unavailable"); return
        p = pfd.select_folder("Folder with Substance smart materials / masks", "").result()
        if p:
            folders = self.settings.setdefault("substance_folders", [])
            if p not in folders:
                folders.append(p)
                self._save_settings()
            self._scan_substance()
            self.msg(f"Added asset folder {p} ({len(self.sp_items)} Substance assets)")

    # ------------------------------------------------------------------ actions
    def _has(self):
        return True if self.engine.comp is not None else "No project is open."

    def _lay_ok(self):
        if self.engine.comp is None:
            return "No project is open."
        return True if self.engine.layer is not None else "Select a layer in the Layer Stack first."

    def _mask_ok(self):
        r = self._lay_ok()
        if r is not True:
            return r
        return True if self.engine.layer.has_mask else "This layer has no painted mask."

    def _set_mode(self, m):
        self.engine.brush.mode = m

    def _set_target(self, t):
        self.engine.end_stroke()
        self.drag = None
        self.engine.brush.target = t
        if t == 1:
            self.engine.set_mask_paint_target(None)

    def _insert_point(self):
        """(parent, index) just above the selected layer, inside its folder if it is in one."""
        eng = self.engine
        lay = eng.layer
        f = eng.find(lay) if lay is not None else None
        if not f:
            return None, len(eng.layers)
        _, i, parent = f
        return parent, i + 1

    def _add_layer(self, kind):
        parent, idx = self._insert_point()
        self.engine.add_layer(kind, index=idx, parent=parent)
        if kind != "group":
            self.engine.brush.target = 0

    def _delete_selected(self):
        eng = self.engine
        sel = self._top_selected()
        if len(sel) <= 1:
            if eng.layer is not None:
                eng.delete_layer(layer=eng.layer)
            return
        eng._push_undo(eng._snapshot_stack())        # one undo step for the whole selection
        for l in sel:
            f = eng.find(l)
            if f:
                f[0].remove(l)
        eng.ts.focus = None
        eng.ts.selected = min(max(eng.ts.selected, 0), len(eng.layers) - 1)
        eng.dirty = True

    def _drop_layer_on(self, src, dst, placement="auto"):
        """Layer drag-and-drop: onto a folder = into it, onto a layer = just above it, None = bottom."""
        eng = self.engine
        moved = self._top_selected() if src.uid in self.sel_uids else [src]
        if any(layer is dst for layer in moved):
            return
        if dst is not None and any(any(l is dst for l in layer.walk()) for layer in moved):
            self.msg("A folder can't be moved into itself.")
            return
        if dst is None:
            parent, index = None, 0
        elif dst.is_group and placement in ("auto", "inside"):
            parent, index = dst, len(dst.children)
            dst.expanded = True
        else:
            lst, i, parent = eng.find(dst)
            index = i if placement == "below" else i + 1
        eng.move_layers_to(moved, parent, index)
        primary = src if any(layer is src for layer in moved) else moved[-1]
        eng.select(primary)
        self.sel_uids = {layer.uid for layer in moved}
        self._last_primary = primary.uid
        eng.dirty = True

    def _nudge(self, delta):
        eng = self.engine
        lay = eng.layer
        lst, i, parent = eng.find(lay)
        j = i + delta
        if 0 <= j < len(lst):
            eng.move_layer_to(lay, parent, j)
            eng.select(lay)

    def _can_nudge(self, delta):
        r = self._lay_ok()
        if r is not True:
            return r
        lst, i, _ = self.engine.find(self.engine.layer)
        if 0 <= i + delta < len(lst):
            return True
        return "Already at the top." if delta > 0 else "Already at the bottom."

    def _flat(self):
        """Visible layer rows, top of the stack first: (layer, depth, parent)."""
        out = []

        def rec(lst, depth, parent):
            for lay in reversed(lst):
                out.append((lay, depth, parent))
                if lay.is_group and lay.expanded:
                    rec(lay.children, depth + 1, lay)
        rec(self.engine.layers, 0, None)
        return out

    def _select_step(self, step):
        rows = [r[0] for r in self._flat()]
        lay = self.engine.layer
        if not rows:
            return
        i = next((k for k, l in enumerate(rows) if l is lay), 0)
        self.engine.select(rows[int(np.clip(i - step, 0, len(rows) - 1))])

    def _top_selected(self):
        """Selected layers, minus those already inside a selected folder (stack order, bottom first)."""
        sel = self._sel_layers()
        return [l for l in sel if not any(o is not l and o.is_group and any(c is l for c in o.walk()) for o in sel)]

    # -- clipboard (Painter: Ctrl+C / X / V, Ctrl+Shift+C / V for the content)
    def _release_clip(self):
        for lay in self.clipboard:
            for l in lay.walk():
                self.engine._release_layer(l)
        self.clipboard = []

    def _copy_layers(self, cut=False):
        eng = self.engine
        sel = self._top_selected()
        if not sel:
            return
        self._release_clip()
        self.clipboard = eng.clone_layers(sel)
        for c, l in zip(self.clipboard, sel):
            c.name = l.name
        if cut:
            self._delete_selected()
        self.msg(f"{'Cut' if cut else 'Copied'} {len(sel)} layer{'s' if len(sel) > 1 else ''}")

    def _paste_layers(self):
        eng = self.engine
        parent, idx = self._insert_point()
        eng._push_undo(eng._snapshot_stack())
        last = None
        clones = eng.clone_layers(self.clipboard)
        for j, (l, c) in enumerate(zip(self.clipboard, clones)):
            c.name = l.name
            last = eng.add_layer(layer=c, index=idx + j, parent=parent, record=False)
        if last is not None:
            eng.select(last)
        self.msg(f"Pasted {len(self.clipboard)} layer{'s' if len(self.clipboard) > 1 else ''}")

    def _copy_content(self):
        eng = self.engine
        lay = eng.layer
        if lay.kind == "group":
            self.msg("Folders have no content of their own to copy.")
            return
        if self.content_clip and self.content_clip[0] == "paint":
            for t in self.content_clip[1].values():
                t.release()
        if lay.kind == "paint":
            self.content_clip = ("paint", {k: eng.gpu.clone(t) for k, t in lay.tex.items()})
        else:
            self.content_clip = ("fill", {k: copy.deepcopy(getattr(lay, k)) for k in CONTENT_FIELDS})
        self.msg(f"Copied the content of '{lay.name}'")

    def _paste_content(self):
        eng = self.engine
        lay = eng.layer
        kind, data = self.content_clip
        if lay.kind != kind:
            self.msg(f"The copied content comes from a {kind} layer: select a {kind} layer to paste it into.")
            return
        if kind == "paint":
            eng._push_undo(("tex", lay, {k: eng.gpu.clone(t) for k, t in lay.tex.items()}))
            for k, t in data.items():
                if k in lay.tex:
                    eng.gpu.blit(t, lay.tex[k])
        else:
            self._edit_properties("Paste layer content", [(lay, copy.deepcopy(data))])
        eng.dirty = True
        self.msg(f"Pasted content into '{lay.name}'")

    def _group_selected(self):
        eng = self.engine
        sel = self._top_selected()
        if not sel:
            return
        grp = eng.group_layers(sel, "Folder")
        eng.select(grp)
        self.sel_uids = {grp.uid}
        self.msg(f"Grouped {len(sel)} layer{'s' if len(sel) > 1 else ''} into a folder")

    def _toggle_mask(self, lay):
        self._edit_properties("Toggle layer mask", [(lay, {"mask_enabled": not lay.mask_enabled})])
        self.msg(f"Mask of '{lay.name}' {'enabled' if lay.mask_enabled else 'disabled'}  (Shift+click the mask)")

    def _use_material(self, name):
        """Click a material: set the selected fill layer's material, otherwise the brush's."""
        eng = self.engine
        col, r, m = MATERIALS[name]
        lay = eng.layer
        if lay is not None and lay.kind == "fill" and eng.brush.target == 0:
            self._edit_properties("Apply material " + name, [
                (l, {"color": list(col), "rough": r, "metal": m})
                for l in self._sel_layers() if l.kind == "fill"])
            self.msg(f"Fill material set to {name}")
        else:
            eng.brush.color, eng.brush.rough, eng.brush.metal = list(col), r, m
            self.msg(f"Brush material set to {name}")

    def _add_fill_material(self, name, index=None, parent=None):
        eng = self.engine
        col, r, m = MATERIALS[name]
        if index is None:
            parent, index = self._insert_point()
        lay = eng.add_layer("fill", name=name, index=index, parent=parent)
        lay.color, lay.rough, lay.metal = list(col), r, m
        eng.brush.target = 0
        eng.dirty = True

    def _add_smart(self, name, index=None, parent=None):
        eng = self.engine
        if index is None:
            eng.add_smart_material(name)
        else:
            eng._push_undo(eng._snapshot_stack())
            for j, lay in enumerate(SMART_MATERIALS[name]()):
                eng.add_layer(layer=lay, index=index + j, parent=parent, record=False)
        self.msg(f"Added smart material: {name}")

    def _apply_generator(self, kind, layer=None):
        eng = self.engine
        if layer is not None and not any(l is layer for l in self._sel_layers()):
            eng.select(layer)
            self._sync_selection()
        self._edit_properties("Apply mask generator", [
            (l.gen, {"kind": kind}) for l in self._sel_layers() or [eng.layer]])
        self.msg(f"Mask generator: {GENERATORS[kind]}")

    def _set_view(self, mode):
        if self.drag in ("paint", "uvpaint"):
            self.engine.end_stroke()
            self.drag = None
        self.view_mode = mode

    def _cycle_display(self, modes=None, step=1):
        r = self.engine.renderer
        modes = modes or list(range(len(DISPLAY_MODES)))
        i = modes.index(r.mode) if r.mode in modes else (-1 if step > 0 else 0)
        r.mode = modes[(i + step) % len(modes)]
        self.engine.dirty = True
        self.msg(f"Display: {DISPLAY_MODES[r.mode]}")

    # -- tools and modes
    def _set_tool(self, tool, erase=False, absolute=False):
        self.engine.end_stroke()
        self.drag = None
        self._finish_fill_projection(cancel=True)
        self.material_ui.transform_tool = self.material_ui.transform_layer_pid = None
        b = self.engine.brush
        self.poly_fill = tool == TOOL_FILL
        if tool != TOOL_FILL:
            b.tool = tool
        b.mode = 1 if erase else 0
        if tool == TOOL_CLONE:
            self.clone_absolute = absolute
            if self.engine.clone_source is None:
                self.msg("Clone: hold V and click to set the source, then paint.")
        if tool == TOOL_PROJECTION and not b.proj_maps:
            self.msg("Projection: load an image in Properties > Projection, place it with S + mouse, then paint.")

    def _tool_is(self, tool, mode=None):
        b = self.engine.brush
        if tool == TOOL_FILL:
            return self.poly_fill
        return not self.poly_fill and b.tool == tool and (mode is None or b.mode == mode)

    def _tool_label(self):
        b = self.engine.brush
        if self.poly_fill:
            return ICON.polyfill, "Polygon fill" + (" (erase)" if b.mode else "")
        if b.tool == TOOL_SMUDGE:
            return ICON.smudge, "Smudge"
        if b.tool == TOOL_CLONE:
            return ICON.clone, "Clone" + (" (absolute)" if self.clone_absolute else "")
        if b.tool == TOOL_PROJECTION:
            return ICON.image, "Projection"
        return (ICON.erase, "Eraser") if b.mode else (ICON.paint, "Paint")

    def _toggle_lazy(self):
        b = self.engine.brush
        if b.lazy > 0:
            self.lazy_last, b.lazy = b.lazy, 0.0
        else:
            b.lazy = self.lazy_last or 25.0
        self.msg(f"Lazy mouse {'on (%.0f px)' % b.lazy if b.lazy else 'off'}  (D)")

    def _toggle_symmetry(self):
        b = self.engine.brush
        if b.symmetry:
            self.sym_last, b.symmetry = b.symmetry, 0
        else:
            b.symmetry = self.sym_last or 1
        axis = "XYZ"[int(b.sym_axis) % 3]
        self.msg(f"Symmetry {SYMMETRY[b.symmetry].lower()}" + (f" on {axis}" if b.symmetry else "") + "  (L)")

    def _pick_material(self):
        if not self._over(self.vp_rect):
            self.msg("Hover the mesh in the 3D view, then press P to pick the material under the cursor.")
            return
        try:
            vals = self.engine.pick_material(*self._mouse_vp())
        except (ValueError, OSError) as error:
            self.msg("Material pick failed: " + str(error))
            return
        self.msg("Picked the material under the cursor into the brush." if vals else "Nothing under the cursor to pick.")

    def _quick_edit_toggle(self):
        e, b = self.engine, self.engine.brush
        if self.quick_edit:
            self.quick_edit = False
            b.target = self._prev_target
            e.quick_mask_enabled = True
            e.dirty = True
            self.msg("Quick mask on: painting is limited to its white areas.  I inverts, Y clears, U edits.")
        else:
            e.ensure_quick_mask(1.0)
            self._prev_target, b.target = (b.target if b.target != 2 else 0), 2
            b.mask_value = 0.0
            self.quick_edit = True
            self.msg("Editing the quick mask: paint black to protect areas (X swaps), U when done.")

    def _quick_clear(self):
        e = self.engine
        q = e.ensure_quick_mask(1.0)
        e._push_undo(("quick", e.ts, {"quick": e.gpu.clone(q)}))
        e.clear_quick_mask(1.0)
        e.dirty = True
        self.msg("Quick mask cleared")

    def _quick_invert(self):
        e = self.engine
        q = e.ensure_quick_mask(1.0)
        e._push_undo(("quick", e.ts, {"quick": e.gpu.clone(q)}))
        e.gpu.write(q, 1.0 - e.gpu.read(q))
        e.dirty = True
        self.msg("Quick mask inverted")

    def _open_bake(self):
        ts = self.engine.ts
        self.bake_settings = BakeSettings.from_dict(ts.bake_settings.to_dict())
        self.open_bake = True

    def _set_workspace_mode(self, mode):
        self._finish_fill_projection(cancel=True)
        self.engine.end_stroke()
        self.drag = None
        self._finish_property_edit()
        if mode == "bake":
            self.bake_ui.prepare()
        self.workspace_mode = mode
        self._show_win(W_PROPS, True)
        self.msg("Baking mode: configure maps and corrections in Properties; F9 returns to painting."
                 if mode == "bake" else "Painting mode")

    def _projection_eligible(self):
        layer = self.engine.layer
        if layer is None or layer.kind != "fill" or self.engine.brush.target != 0:
            return "Select fill-layer content to transform its projection."
        return True if layer.maps or layer.authored is not None else "Assign a bitmap or surface object to the fill layer first."

    def _projection_tool(self, tool=None):
        self._finish_fill_projection(cancel=True)
        self._finish_property_edit()
        current = self.material_ui.transform_tool
        chosen = tool if tool else (None if current else getattr(self, "_last_projection_tool", "translate"))
        self.material_ui.transform_tool = chosen
        self.material_ui.transform_layer_pid = self.engine.layer.pid if chosen else None
        if chosen:
            self._last_projection_tool = chosen
        self.msg((chosen.title() + " projection: drag in a viewport; Q finishes; Escape cancels the drag.")
                 if chosen else "Projection transform finished")

    def _close_project(self):
        self.workspace_mode = "paint"
        self._last_uv_hit = None
        self._finish_fill_projection(cancel=True)
        self.material_ui.transform_tool = None
        self.material_ui.transform_layer_pid = None
        e = self.engine
        self._release_clip()
        e._release_project()
        e.mesh = None
        self.project_path = None
        self.sel_uids, self._last_primary = set(), None
        self.quick_edit = self.isolate = self.paused = False
        self._last_hit = None
        self.msg("Project closed")

    def _show_win(self, name, on=None):
        self.show[name] = (not self.show[name]) if on is None else on
        if self.show[name] and name in DOCKED:
            imgui.set_window_focus(name)

    def _reset_layout(self):
        self.need_layout = True
        for w in DOCKED:
            self.show[w] = True
        self.msg("Layout reset to default")

    # ------------------------------------------------------------------ command registry
    def _build_commands(self):
        R = self.reg = Registry()
        e, b = self.engine, self.engine.brush
        has, lay_ok = self._has, self._lay_ok

        def can_undo():
            return True if e.undo_stack else "Nothing to undo."

        def can_redo():
            return True if e.redo_stack else "Nothing to redo."

        def na(why):
            return lambda: why

        def noop():
            pass

        def multi_sets():
            r = has()
            return r if r is not True else (True if len(e.sets) > 1 else "This project has a single texture set.")

        def has_stencil():
            r = has()
            return r if r is not True else (True if b.stencil else "No stencil loaded (Properties > Stencil).")

        def has_clip():
            r = has()
            return r if r is not True else (True if self.clipboard else "Nothing copied yet (Ctrl+C a layer first).")

        def has_content_clip():
            r = lay_ok()
            return r if r is not True else (True if self.content_clip else "No layer content copied yet (Ctrl+Shift+C).")

        def has_last():
            r = has()
            return r if r is not True else (True if self._last_hit is not None or self._last_uv_hit is not None else "Paint a stroke first.")

        def is_group():
            r = lay_ok()
            return r if r is not True else (True if e.layer.is_group else "Select a folder to ungroup.")

        # --- File (Painter defaults)
        R.add("file.new", "New Project...", "File", lambda: setattr(self, "open_new", True), ["Ctrl+N"])
        R.add("file.open", "Open Project...", "File", self._ask_open, ["Ctrl+O"])
        R.add("file.import_spp", "Import Substance Painter project (.spp)...", "File", self._ask_import_spp, [],
              tip="Mesh, every texture set with its layer stack, and the recorded paint strokes.")
        R.add("file.import_preset", "Import smart material / smart mask...", "File", self._ask_import_preset, [], has,
              tip="Add a Painter .spsm to the Layer Stack, or apply a .spmsk to the selected layer.")
        R.add("file.save", "Save", "File", self._save, ["Ctrl+S"], has)
        R.add("file.save_as", "Save As...", "File", lambda: self._save(save_as=True), ["Ctrl+Shift+S"], has)
        self.project_ui.register_commands(R)
        R.add("file.close", "Close Project", "File", lambda: setattr(self, "open_close", True), ["Ctrl+F4"], has)
        R.add("file.export", "Export Textures...", "File", lambda: setattr(self, "open_export", True),
              ["Ctrl+Shift+E", "Ctrl+E"], has)
        R.add("file.delivery", "Deliver mesh and materials...", "File", lambda:setattr(self.delivery_ui,"open",True), enabled=has)
        R.add("file.bake", "Bake Mesh Maps...", "File", self._open_bake, ["Ctrl+Shift+B"], has)
        R.add("file.quit", "Quit", "File", self._request_quit, ["Alt+F4"])
        R.add("edit.undo", "Undo", "Edit", e.undo, ["Ctrl+Z"], can_undo)
        R.add("edit.redo", "Redo", "Edit", e.redo, ["Ctrl+Y", "Ctrl+Shift+Z"], can_redo)
        R.add("edit.settings", "Settings...", "Edit", lambda: self._show_win(W_SETTINGS, True))

        # --- Modes
        R.add("mode.bake", "Baking", "Modes", lambda: self._set_workspace_mode("bake"), ["F8"], has,
              checked=lambda: self.workspace_mode == "bake")
        R.add("mode.paint", "Painting", "Modes", lambda: self._set_workspace_mode("paint"), ["F9"], has,
              checked=lambda: self.workspace_mode == "paint")

        # --- Tools
        R.add("tool.paint", "Paint", "Tools", lambda: self._set_tool(TOOL_PAINT), ["1"], has,
              checked=lambda: self._tool_is(TOOL_PAINT, 0), tip="Paint material channels onto the selected paint layer.")
        R.add("tool.erase", "Eraser", "Tools", lambda: self._set_tool(TOOL_PAINT, erase=True), ["2"], has,
              checked=lambda: self._tool_is(TOOL_PAINT, 1), tip="Erase paint (or mask) with the same brush.")
        R.add("tool.projection", "Projection", "Tools", lambda: self._set_tool(TOOL_PROJECTION), ["3"], has,
              checked=lambda: self._tool_is(TOOL_PROJECTION),
              tip="Paint an image projected from the screen. Place it with S + mouse.")
        R.add("tool.fill", "Polygon fill", "Tools", lambda: self._set_tool(TOOL_FILL), ["4"], has,
              checked=lambda: self._tool_is(TOOL_FILL), tip="Click to fill a triangle, polygon, UV island or mesh part.")
        R.add("tool.smudge", "Smudge", "Tools", lambda: self._set_tool(TOOL_SMUDGE), ["5"], has,
              checked=lambda: self._tool_is(TOOL_SMUDGE), tip="Drag existing paint around.")
        R.add("tool.clone", "Clone (relative source)", "Tools", lambda: self._set_tool(TOOL_CLONE), ["6"], has,
              checked=lambda: self._tool_is(TOOL_CLONE) and not self.clone_absolute,
              tip="V + click sets the source; the offset is kept between strokes.")
        R.add("tool.clone_abs", "Clone (absolute source)", "Tools", lambda: self._set_tool(TOOL_CLONE, absolute=True),
              ["Ctrl+6"], has, checked=lambda: self._tool_is(TOOL_CLONE) and self.clone_absolute,
              tip="Every stroke starts copying from the source point.")
        R.add("tool.toggle_erase", "Toggle Paint / Eraser", "Tools", lambda: self._set_mode(1 - b.mode), [], has)
        R.add("tool.pick", "Pick stroke material", "Tools", self._pick_material, ["P"], has,
              tip="Loads the material under the cursor into the brush.")
        R.add("tool.lazy", "Lazy mouse", "Tools", self._toggle_lazy, ["D"], has, checked=lambda: b.lazy > 0,
              tip="Smooths strokes: the brush trails the cursor.")
        R.add("tool.ignore_stencil", "Ignore stencil", "Tools",
              lambda: setattr(b, "stencil_enabled", not b.stencil_enabled), ["N"], has_stencil,
              checked=lambda: bool(b.stencil) and not b.stencil_enabled)
        R.add("tool.resume", "Resume previous stroke", "Tools",
              lambda: (setattr(self, "_resume", True), self.msg("The next stroke continues from where the last one ended.")),
              ["A"], has_last)
        R.add("tool.symmetry", "Symmetry", "Tools", self._toggle_symmetry, ["L"], has, checked=lambda: b.symmetry > 0)
        R.add("tool.target", "Paint the layer's mask", "Tools", lambda: self._set_target(1 - min(b.target, 1)), [], has,
              checked=lambda: b.target == 1,
              tip="Switch the brush between the layer content and its mask\n(same as clicking the mask thumbnail).")
        R.add("tool.mask_swap", "Invert mask paint (white / black)", "Tools",
              lambda: setattr(b, "mask_value", 1.0 - b.mask_value), ["X"], has)
        R.add("tool.size_down", "Brush size smaller", "Tools",
              lambda: self.bsize.scale(1 / 1.15), ["["], has, repeat=True)
        R.add("tool.size_up", "Brush size larger", "Tools",
              lambda: self.bsize.scale(1.15), ["]"], has, repeat=True)

        # --- Quick mask
        R.add("quick.edit", "Quick mask: edit / apply", "Quick mask", self._quick_edit_toggle, ["U"], has,
              checked=lambda: self.quick_edit)
        R.add("quick.clear", "Quick mask: clear", "Quick mask", self._quick_clear, ["Y"], has)
        R.add("quick.invert", "Quick mask: invert", "Quick mask", self._quick_invert, ["I"], has)
        R.add("quick.use", "Quick mask: limit painting", "Quick mask",
              lambda: setattr(e, "quick_mask_enabled", not e.quick_mask_enabled), [], has,
              checked=lambda: e.quick_mask_enabled)

        # --- Layers
        R.add("layer.add_paint", "Add paint layer", "Layer", lambda: self._add_layer("paint"), [], has)
        R.add("layer.add_fill", "Add fill layer", "Layer", lambda: self._add_layer("fill"), [], has)
        R.add("layer.add_group", "Add folder", "Layer", lambda: self._add_layer("group"), [], has)
        R.add("layer.copy", "Copy layer", "Layer", self._copy_layers, ["Ctrl+C"], lay_ok)
        R.add("layer.cut", "Cut layer", "Layer", lambda: self._copy_layers(cut=True), ["Ctrl+X"], lay_ok)
        R.add("layer.paste", "Paste layer", "Layer", self._paste_layers, ["Ctrl+V"], has_clip)
        R.add("layer.duplicate", "Duplicate layer", "Layer", lambda: e.duplicate_layer(layer=e.layer), ["Ctrl+D"], lay_ok)
        R.add("layer.delete", "Delete layer", "Layer", self._delete_selected, ["Delete"], lay_ok)
        R.add("layer.group", "Group layers into a folder", "Layer", self._group_selected, ["Ctrl+G"], lay_ok)
        R.add("layer.ungroup", "Ungroup folder", "Layer", lambda: e.ungroup(e.layer), [], is_group)
        R.add("layer.copy_content", "Copy layer content", "Layer", self._copy_content, ["Ctrl+Shift+C"], lay_ok)
        R.add("layer.paste_content", "Paste layer content", "Layer", self._paste_content, ["Ctrl+Shift+V"],
              has_content_clip)
        R.add("layer.up", "Move layer up", "Layer", lambda: self._nudge(+1), [], lambda: self._can_nudge(+1))
        R.add("layer.down", "Move layer down", "Layer", lambda: self._nudge(-1), [], lambda: self._can_nudge(-1))
        R.add("layer.mask_white", "Add white mask (shows everything)", "Layer", lambda: e.add_mask(1.0), [], lay_ok)
        R.add("layer.mask_black", "Add black mask (hides everything)", "Layer", lambda: e.add_mask(0.0), [], lay_ok)
        R.add("layer.mask_remove", "Remove painted mask", "Layer", e.remove_mask, [], self._mask_ok)
        R.add("layer.mask_toggle", "Disable / enable mask", "Layer", lambda: self._toggle_mask(e.layer), [], lay_ok,
              checked=lambda: e.layer is not None and not e.layer.mask_enabled)
        R.add("layer.clear", "Clear painting", "Layer", e.clear_paint, [],
              lambda: lay_ok() if lay_ok() is not True else (True if e.layer.kind == "paint" else "Only paint layers hold painting."))
        R.add("layer.select_up", "Select layer above", "Layer", lambda: self._select_step(+1), [], lay_ok)
        R.add("layer.select_down", "Select layer below", "Layer", lambda: self._select_step(-1), [], lay_ok)

        # --- Viewport (Painter defaults)
        for i, name in enumerate(DISPLAY_MODES):
            R.add(f"view.mode{i}", f"Show {name}", "Viewport",
                  lambda i=i: (setattr(e.renderer, "mode", i), setattr(e, "dirty", True)), [], has,
                  checked=lambda i=i: e.renderer.mode == i)
        R.add("view.material", "Display material", "Viewport",
              lambda: (setattr(e.renderer, "mode", 0), setattr(e, "dirty", True)), ["M"], has)
        R.add("view.next_channel", "Display next channel", "Viewport", lambda: self._cycle_display(CHANNEL_MODES, 1),
              ["C"], has)
        R.add("view.prev_channel", "Display previous channel", "Viewport",
              lambda: self._cycle_display(CHANNEL_MODES, -1), ["Shift+C"], has)
        R.add("view.next_map", "Display next mesh map", "Viewport", lambda: self._cycle_display(MESHMAP_MODES, 1),
              ["B"], has)
        R.add("view.prev_map", "Display previous mesh map", "Viewport", lambda: self._cycle_display(MESHMAP_MODES, -1),
              ["Shift+B"], has)
        R.add("view.split", "3D and 2D views", "Viewport", lambda: self._set_view(VIEW_SPLIT), ["F1"], has,
              checked=lambda: self.view_mode == VIEW_SPLIT)
        R.add("view.3d", "3D view only", "Viewport", lambda: self._set_view(VIEW_3D), ["F2"], has,
              checked=lambda: self.view_mode == VIEW_3D)
        R.add("view.2d", "2D view only", "Viewport", lambda: self._set_view(VIEW_2D), ["F3"], has,
              checked=lambda: self.view_mode == VIEW_2D)
        R.add("view.swap", "Swap 2D / 3D views", "Viewport", lambda: setattr(self, "view_swap", not self.view_swap),
              ["F4"], has, checked=lambda: self.view_swap)
        R.add("view.persp", "Perspective camera", "Viewport", lambda: setattr(e.camera, "ortho", False), ["F5"], has,
              checked=lambda: not e.camera.ortho)
        R.add("view.ortho", "Orthographic camera", "Viewport", lambda: setattr(e.camera, "ortho", True), ["F6"], has,
              checked=lambda: e.camera.ortho)
        R.add("view.frame", "Frame mesh", "Viewport", lambda: e.camera.frame(e.mesh.center, e.mesh.radius), ["F"], has)
        R.add("view.hide_ui", "Hide panels (maximise viewport)", "Viewport",
              lambda: setattr(self, "ui_hidden", not self.ui_hidden), ["Tab"], has, checked=lambda: self.ui_hidden)
        R.add("view.isolate", "Isolate texture set", "Viewport", lambda: setattr(self, "isolate", not self.isolate),
              ["Alt+Q"], multi_sets, checked=lambda: self.isolate)
        R.add("view.material_tiles", "Material tiles...", "Viewport", lambda: setattr(self.tiles_ui, "open", True), [], has)
        R.add("view.frame_uv_tiles", "Frame UV tiles", "Viewport", lambda: self.uv.fit_tiles(e, self._uv_input()[0].size), [], has)
        R.add("view.pause", "Pause engine computation", "Viewport",
              lambda: (setattr(self, "paused", not self.paused),
                       self.msg("Engine paused: the viewport stops updating (Shift+Esc resumes)." if self.paused
                                else "Engine resumed")), ["Shift+Escape"], has, checked=lambda: self.paused)
        R.add("view.reset_2d", "Reset 2D view", "Viewport",
              lambda: self.uv.fit_tiles(e, self._uv_input()[0].size) if e.ts.tiles is not None else self.uv.reset(), [], has)
        R.add("view.uv_wire", "UV wireframe", "Viewport", lambda: setattr(self.uv, "wire", not self.uv.wire), [], has,
              checked=lambda: self.uv.wire)

        # --- Painter shortcuts whose feature doesn't exist yet: listed (and rebindable) so they explain themselves
        manip = "There is no on-screen manipulator yet: hold S and drag (left rotate, middle move, right scale) " \
                "to place stencils and projection images."
        for cid, name, keys in (("manip.show", "Show / hide manipulator", ["Q"]),
                                ("manip.bigger", "Increase manipulator size", ["="]),
                                ("manip.smaller", "Decrease manipulator size", ["-"]),
                                ("manip.space", "Cycle manipulation spaces", ["T"]),
                                ("manip.translate", "Manipulator: translate", ["W"]),
                                ("manip.rotate", "Manipulator: rotate", ["E"]),
                                ("manip.scale", "Manipulator: scale", ["R"]),
                                ("manip.surface", "Manipulator: surface", ["Shift+W"]),
                                ("manip.warp", "Toggle warp edit mode", ["Shift+V"])):
            tool = {"manip.translate": "translate", "manip.rotate": "rotate", "manip.scale": "scale", "manip.show": None}
            if cid in tool:
                R.add(cid, name, "Projection", lambda selected=tool[cid]: self._projection_tool(selected), keys,
                      self._projection_eligible,
                      checked=lambda selected=tool[cid]: bool(self.material_ui.transform_tool) if selected is None else self.material_ui.transform_tool == selected)
            else:
                R.add(cid, name, NA, noop, keys, na(manip), in_palette=False)
        R.add("na.render", "Rendering mode (Iray)", NA, noop, ["F10"], na("Iray rendering isn't available in Strata yet."),
              in_palette=False)
        R.add("na.particles", "Paint / Eraser / Projection + particles", NA, noop, ["Ctrl+1", "Ctrl+2", "Ctrl+3"],
              na("Particle brushes aren't available in Strata yet."), in_palette=False)
        R.add("na.anim", "Toggle animation (particles)", NA, noop, ["Space"],
              na("Particle animation isn't available in Strata yet."), in_palette=False)
        R.add("na.excluded", "Hide / ignore excluded geometry", NA, noop, ["Alt+H"],
              na("Hiding excluded geometry isn't available in Strata yet."), in_palette=False)

        for w in DOCKED + FLOATING:
            R.add("win." + w, w, "Window", lambda w=w: self._show_win(w), [], checked=lambda w=w: self.show[w])
        R.add("win.reset", "Reset layout", "Window", self._reset_layout)
        R.add("win.palette", "Command palette", "Window", self.palette.request, ["Ctrl+K"], in_palette=False)
        R.add("help.shortcuts", "Shortcuts and mouse controls", "Help", lambda: self._show_win(W_KEYS, True))
        R.add("layer.channels", "Channels and shaders...", "Layer", lambda:setattr(self.channels_ui,"open",True))
        R.add("layer.authored", "Paths, ribbons and text...", "Layer", lambda:setattr(self.authored_ui,"open",True))
        R.add("assets.import_coverage", "Painter import coverage...", "Assets", lambda: setattr(self.import_ui,"open",True))
        R.add("assets.sp_rescan", "Rescan Substance Painter assets", "Assets",
              lambda: (self._scan_substance(), self.msg(f"Found {len(self.sp_items)} Substance assets")))
        R.add("assets.sp_folder", "Add Substance asset folder...", "Assets", self._add_sp_folder)
        R.add("assets.sp_tab", "Show Substance Painter assets", "Assets",
              lambda: (setattr(self, "asset_tab_request", "substance"), self._show_win(W_ASSETS, True)))

        for name in SMART_MATERIALS:
            R.add("smart." + name, f"Add smart material: {name}", "Assets", lambda n=name: self._add_smart(n), [], has)
        for name in MATERIALS:
            R.add("mat." + name, f"Use material: {name}", "Assets", lambda n=name: self._use_material(n), [], has)
            R.add("matfill." + name, f"Add fill layer: {name}", "Assets", lambda n=name: self._add_fill_material(n), [], has)
        for k in range(1, len(GENERATORS)):
            R.add(f"gen.{k}", f"Mask generator: {GENERATORS[k]}", "Assets", lambda k=k: self._apply_generator(k), [], lay_ok)

    # ------------------------------------------------------------------ main loop
    def run(self):
        last = time.time()
        try:
            while not glfw.window_should_close(self.window):
                glfw.poll_events()
                self.impl.process_inputs()
                now = time.time()
                self.fps = 0.9 * self.fps + 0.1 / max(now - last, 1e-4)
                last = now
                self.frame()
                glfw.swap_buffers(self.window)
                if self.pending and self._pending_shown >= 2:
                    label, fn = self.pending
                    self.pending = None
                    try:
                        fn()
                    except Exception as e:
                        traceback.print_exc()
                        self.msg(f"{label.rstrip('.')} failed: {e}")
                self.project_ui.tick()
        finally:
            self.assistant_ui.close()
        self._save_settings()
        try:
            if self.ini_path:
                imgui.save_ini_settings_to_disk(self.ini_path)
        except Exception:
            pass
        self._drain_gl_errors()
        try:
            self.impl.shutdown()
        except Exception:
            pass
        if hasattr(self, "material_previews"):
            self.material_previews.release()
        if hasattr(self, "brush_preview"):
            self.brush_preview.release(self.engine.painter)
        self.tablet.close()
        glfw.terminate()

    def frame(self):
        self.assistant_ui.tick()
        imgui.new_frame()
        ww, wh = glfw.get_window_size(self.window)
        fw, fh = glfw.get_framebuffer_size(self.window)
        self.fb_scale = (fw / max(ww, 1), fh / max(wh, 1))
        if self.open_help:
            self.show[W_KEYS], self.open_help = True, False
        has_project = self.engine.comp is not None
        self._sync_selection()

        menu_h = self.menu_bar()
        status_h = round(imgui.get_frame_height() + 6 * self.ui_scale)
        top, left, right = menu_h, 0, ww
        if has_project and not self.ui_hidden:
            top += self.toolbar(ww, top)
            left = self.tool_strip(top, wh - status_h)
            right = ww - self.dock_strip(ww, top, wh - status_h)
        area = (left, top, max(right - left, 1), max(wh - top - status_h, 1))
        central = self.dock_host(area, active=has_project and not self.ui_hidden)
        self._hover_set = None
        if has_project and not self.ui_hidden:
            self.panels(ww)
        vp = central if (has_project and not self.ui_hidden) else (0, menu_h, ww, max(wh - menu_h - status_h, 1))
        self._split_view(vp)
        if has_project:
            self.viewport_overlay(vp)
        elif not self.pending:
            self.welcome(vp)
        self.status_bar(ww, wh, status_h)
        self.dialogs()
        self.extra_dialogs()
        self.quick_brush()
        self.palette.draw(self.reg, self.msg, self.ui_scale)
        if getattr(self, "_property_edit_key", None) is not None and not imgui.is_any_item_active():
            self._finish_property_edit(cancel=imgui.is_key_pressed(imgui.Key.escape))
        if self.pending:
            self.busy_overlay(ww, wh)
            self._pending_shown += 1
        if not self.pending:
            self.shortcuts()
            if has_project:
                try:
                    self.viewport_input()
                except MemoryError as error:
                    self._memory_failure(error)

        self.ctx.screen.use()
        self.ctx.viewport = (0, 0, fw, fh)
        self.ctx.clear(0.08, 0.085, 0.09)
        if has_project and not getattr(self, "_memory_error", None):
            try:
                self._render_views(wh)
                self._authored_error=None
            except authored_model.AuthoredResourceError as error:
                if str(error)!=getattr(self,"_authored_error",None):self.msg(str(error))
                self._authored_error=str(error)
            except MemoryError as error:
                self._memory_failure(error)
        try:
            # Prepare tile thumbnails after shortcuts and viewport edits; their
            # texture leases must remain pinned until ImGui submits its draws.
            self.tiles_ui.draw()
            self.ctx.screen.use()
            self.ctx.viewport = (0, 0, fw, fh)
            imgui.render()
            self._apply_cursor()
            self._drain_gl_errors()
            self.impl.render(imgui.get_draw_data())
        finally:
            self.tiles_ui.finish_frame()
            if hasattr(self, "material_previews"):
                self.material_previews.finish_frame()

    def _memory_failure(self, error):
        self.engine.cancel_stroke()
        self.drag = None
        self._memory_error = str(error)
        self.msg(str(error) + "; adjust Memory and history settings to resume the preview.")

    def _render_views(self, wh):
        sx, sy = self.fb_scale
        if self.drag == "uvpaint":
            self._paint_uv_at_cursor()
        vx, vy, vw, vh = self.vp_rect
        if vw > 1 and vh > 1:
            rect = (int(vx * sx), int((wh - vy - vh) * sy), int(vw * sx), int(vh * sy))
            self.engine.update_view(rect[2], rect[3])
            if self.drag == "paint":      # stroke follows the cursor every frame
                self._paint_at_cursor()
            self.cursor = self._pick_cursor() if self.drag in (None, "paint") else None
            self.ctx.screen.use()
            self._render_3d(rect, self.cursor if self._cursor_visible() else None)
        ux, uy, uw, uh = self.uv_rect
        if uw > 1 and uh > 1:
            self.ctx.screen.use()
            self.uv.render(self.engine, (int(ux * sx), int((wh - uy - uh) * sy), int(uw * sx), int(uh * sy)), refresh=not self.paused)
            diagnostics = self.uv.diagnostics
            if diagnostics and diagnostics != getattr(self, "_uv_tile_report", None):
                self.msg("UV tile preview: " + "; ".join(f"{item['udim']}: {item['message']}" for item in diagnostics))
            elif not diagnostics and getattr(self, "_uv_tile_report", None):
                self.msg("UV tile preview refreshed.")
            self._uv_tile_report = diagnostics
            self._draw_uv_cursor()

    _CURSOR_SHAPES = {   # ImGui cursor -> GLFW standard cursors to try (the first one this GLFW has wins)
        "text_input": ("IBEAM_CURSOR",),
        "resize_all": ("RESIZE_ALL_CURSOR", "CROSSHAIR_CURSOR"),
        "resize_ns": ("RESIZE_NS_CURSOR", "VRESIZE_CURSOR"),
        "resize_ew": ("RESIZE_EW_CURSOR", "HRESIZE_CURSOR"),
        "resize_nesw": ("RESIZE_NESW_CURSOR", "RESIZE_ALL_CURSOR", "CROSSHAIR_CURSOR"),
        "resize_nwse": ("RESIZE_NWSE_CURSOR", "RESIZE_ALL_CURSOR", "CROSSHAIR_CURSOR"),
        "hand": ("POINTING_HAND_CURSOR", "HAND_CURSOR"),
        "not_allowed": ("NOT_ALLOWED_CURSOR",),
    }

    def _apply_cursor(self):
        """Show the mouse cursor ImGui asks for (resize arrows over splitters and edges, I-beam in text)."""
        want = imgui.get_mouse_cursor()
        if self._over(self.vp_rect) and self.engine.ts is not None:
            hit = self.engine._last_pick
            if hit is not None and self.engine._set_of_tri(hit["tri"]) != self.engine.active:
                want = imgui.MouseCursor_.not_allowed
        if (self.engine.comp is not None and self._cursor_visible() and want == imgui.MouseCursor_.arrow
                and (self._over_viewport() or self.drag == "paint")):
            want = imgui.MouseCursor_.none           # the brush circle is the cursor on the mesh
        if want == self._cur_cursor:
            return
        self._cur_cursor = want
        name = next((n for n in self._CURSOR_SHAPES if getattr(imgui.MouseCursor_, n, None) == want), None)
        cur = None
        if name is not None:
            if name not in self._glfw_cursors:
                self._glfw_cursors[name] = None
                for shape in self._CURSOR_SHAPES[name]:
                    if hasattr(glfw, shape):
                        try:
                            self._glfw_cursors[name] = glfw.create_standard_cursor(getattr(glfw, shape))
                        except Exception:          # shape missing from this GLFW library build
                            continue
                        if self._glfw_cursors[name]:
                            break
            cur = self._glfw_cursors[name]
        try:
            glfw.set_input_mode(self.window, glfw.CURSOR,
                                glfw.CURSOR_HIDDEN if want == imgui.MouseCursor_.none else glfw.CURSOR_NORMAL)
            glfw.set_cursor(self.window, cur)        # None restores the normal arrow
        except Exception:
            pass

    def _render_3d(self, rect, cursor):
        """engine.render(), plus Painter's view options: pause, texture-set isolation, quick-mask display."""
        e = self.engine
        r = e.renderer
        if not self.paused:
            e.update()
        mode = r.mode
        if self.quick_edit and e.ts is not None and e.ts.quick is not None:
            e.gpu.blit(e.ts.quick, e.comp.mask_preview)      # show the quick mask while editing it
            r.mode = 6
        self.ctx.screen.use()
        sets = [(ts.key, ts.comp, ts.bakes) for i, ts in enumerate(e.sets)
                if ts.visible and ts.comp is not None and (not self.isolate or i == e.active)]
        if any(ts.tiles is not None for i, ts in enumerate(e.sets) if ts.visible and (not self.isolate or i == e.active)):
            diagnostics = e.render_materials(rect, [e.active] if self.isolate else None, refresh=not self.paused)
            if diagnostics and diagnostics != getattr(self, "_tile_render_report", None):
                self.msg("Tiled preview: " + "; ".join(f"{item['udim']}: {item['message']}" for item in diagnostics))
            elif not diagnostics and getattr(self, "_tile_render_report", None):
                self.msg("Tiled preview refreshed.")
            self._tile_render_report = diagnostics
        else:
            r.render_sets(e.gm, e.camera, e._vp, sets, rect)
        r.mode = mode
        if self.poly_fill and sets:
            self._draw_fill_wire(rect, cursor)
        self._draw_set_highlight(rect)
        r.draw_symmetry(e.gm, e._vp, rect, e.brush, [key for key, _, _ in sets])
        if cursor is not None:
            hit, nrm = cursor
            r.draw_cursor(hit, nrm, e.brush_radius(hit), e._vp, rect)

    def _draw_fill_wire(self, rect, cursor):
        """Polygon fill shows the mesh's faces and edges, and tints what a click would fill."""
        e = self.engine
        topo = e.mesh.topology
        visible = (e.active,) if e.ts.visible else ()
        only = np.concatenate([e.sets[i].tri_ids for i in visible]) if visible else np.empty(0, np.int64)
        key = (id(e.mesh), visible)
        hl = None
        tri = (e._last_pick or {}).get("tri", -1) if cursor is not None else -1
        if 0 <= tri < topo.n_tris and e.ts is not None:
            hk = (id(e.mesh), int(tri), self.fill_mode, e.active)
            if self._wire_hl is None or self._wire_hl[0] != hk:
                tris = topo.expand([tri], self.fill_mode)
                tris = tris[np.isin(tris, e.ts.tri_ids)]
                self._wire_hl = (hk, e.mesh.positions[e.mesh.indices[tris]])
            hl = self._wire_hl
        e.renderer.draw_wire(key, lambda: topo.wire_segments(only), e.camera, e._vp, rect, hl)

    def _draw_set_highlight(self, rect):
        e = self.engine
        chosen = self._hover_set
        io = imgui.get_io()
        if (chosen is None and io.key_ctrl and io.key_alt and self._over(self.vp_rect)
                and not any(imgui.is_mouse_down(k) for k in (0, 1, 2))):
            info = e.pick_info(*self._mouse_vp())
            chosen = info["set"] if info else None
        if chosen is None or not 0 <= chosen < len(e.sets) or not e.sets[chosen].visible:
            return
        empty = np.empty((0, 2, 3), np.float32)
        ts = e.sets[chosen]
        key = ("set-hover", id(e.mesh), ts.pid)
        e.renderer.draw_wire(("set-hover-empty",), lambda: (empty, empty), e.camera, e._vp, rect,
                             (key, e.mesh.positions[e.mesh.indices[ts.tri_ids]]))

    def welcome(self, vp):
        x, y, w, h = vp
        imgui.set_next_window_pos(V2(x + w / 2, y + h / 2), 0, V2(0.5, 0.5))
        imgui.begin("##welcome", None, imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.always_auto_resize
                    | imgui.WindowFlags_.no_saved_settings)
        imgui.text("No project open")
        imgui.text_disabled("Drop a mesh or .strata file here, or:")
        self._cmd_btn(ICON.plus, "file.new", label="New project  (Ctrl+N)")
        imgui.same_line()
        self._cmd_btn(ICON.open, "file.open", label="Open  (Ctrl+O)")
        imgui.end()

    def _drain_gl_errors(self):
        # moderngl never checks glGetError, but the PyOpenGL-based ImGui backend does, so a
        # stale flag from a harmless driver query would surface there as an exception.
        for _ in range(16):
            if self.ctx.error == "GL_NO_ERROR":
                break

    # ------------------------------------------------------------------ docking layout
    def dock_host(self, area, active=True):
        """Invisible window holding the dockspace. Returns the central (viewport) rect."""
        x, y, w, h = area
        imgui.set_next_window_pos(V2(x, y))
        imgui.set_next_window_size(V2(w, h))
        W = imgui.WindowFlags_
        flags = (W.no_title_bar | W.no_collapse | W.no_resize | W.no_move | W.no_bring_to_front_on_focus
                 | W.no_nav_focus | W.no_background | W.no_docking | W.no_saved_settings | W.no_scrollbar)
        if not active:
            flags |= W.no_inputs
        imgui.push_style_var(imgui.StyleVar_.window_padding, V2(0, 0))
        imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
        imgui.begin("##dock_host", None, flags)
        imgui.pop_style_var(2)
        self.dock_id = imgui.get_id("StrataDockspace")
        I = imgui.internal
        if active and (self.need_layout or I.dock_builder_get_node(self.dock_id) is None):
            self._build_layout(w, h)
            self.need_layout = False
            self._save_settings()
        D = imgui.DockNodeFlags_
        dflags = D.passthru_central_node | D.no_docking_over_central_node
        if not active:
            dflags |= D.keep_alive_only
        imgui.dock_space(self.dock_id, V2(0, 0), dflags)
        imgui.end()
        node = I.dock_builder_get_central_node(self.dock_id) if active else None
        if node is None:
            return area
        return (node.pos.x, node.pos.y, max(node.size.x, 1), max(node.size.y, 1))

    def _build_layout(self, w, h):
        I = imgui.internal
        s = self.ui_scale
        did = self.dock_id
        I.dock_builder_remove_node(did)
        I.dock_builder_add_node(did, I.DockNodeFlagsPrivate_.dock_space)
        I.dock_builder_set_node_size(did, V2(w, h))
        left_px = min(260 * s, w * 0.24)
        right_px = min(370 * s, (w - left_px) * 0.42)
        sp = I.dock_builder_split_node(did, imgui.Dir.left, left_px / w)
        left, rest = sp.id_at_dir, sp.id_at_opposite_dir
        sp = I.dock_builder_split_node(rest, imgui.Dir.right, right_px / max(w - left_px, 1))
        right = sp.id_at_dir                      # the other side is the viewport (central node)
        sp = I.dock_builder_split_node(right, imgui.Dir.up, min(0.14, 96 * s / h))
        tsl, rrest = sp.id_at_dir, sp.id_at_opposite_dir
        sp = I.dock_builder_split_node(rrest, imgui.Dir.up, 0.47)
        layers, props = sp.id_at_dir, sp.id_at_opposite_dir
        I.dock_builder_dock_window(W_ASSETS, left)
        I.dock_builder_dock_window(W_TSL, tsl)
        I.dock_builder_dock_window(W_LAYERS, layers)
        I.dock_builder_dock_window(W_TSS, layers)      # tabbed behind Layer Stack, as in Painter
        I.dock_builder_dock_window(W_PROPS, props)
        I.dock_builder_dock_window(W_AI, props)
        I.dock_builder_finish(did)
        self._focus_layers = 3

    def _split_view(self, vp):
        x, y, w, h = vp
        if self.view_mode == VIEW_3D:
            self.vp_rect, self.uv_rect = vp, (0, 0, 0, 0)
        elif self.view_mode == VIEW_2D:
            self.vp_rect, self.uv_rect = (x, y, 0, 0), vp
        else:
            # the divider between the views can be dragged; split_frac is the left view's share
            half = int(np.clip(round(w * self.split_frac), 60, max(w - 60, 61)))
            a, b = (x, y, half - 1, h), (x + half + 1, y, w - half - 1, h)
            self.vp_rect, self.uv_rect = (b, a) if self.view_swap else (a, b)      # F4 swaps the sides
            self._split_hit = (x + half, y, y + h, x, w)
            hot = self.drag == "split" or self._over_split()
            if hot:
                imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ew)
            imgui.get_background_draw_list().add_rect_filled(
                V2(x + half - (2 if hot else 1), y), V2(x + half + (2 if hot else 1), y + h),
                col32(*ACCENT, 0.9) if hot else col32(0.2, 0.21, 0.23))
            return
        self._split_hit = None

    def _over_split(self):
        """Mouse over the 3D / 2D divider (a few pixels either side of it)."""
        if self._split_hit is None or self.drag:
            return False
        io = imgui.get_io()
        mx, my = io.mouse_pos
        sx, y0, y1 = self._split_hit[:3]
        return abs(mx - sx) <= 4 * self.ui_scale and y0 <= my < y1 and not io.want_capture_mouse

    # ------------------------------------------------------------------ widgets
    def _icon_btn(self, icon, tip, enabled=True, active=False, size=None, sid=None):
        if size is None:
            fh = imgui.get_frame_height()
            size = V2(fh * 1.15, fh)
        imgui.push_id(sid or tip)
        if active:
            imgui.push_style_color(imgui.Col_.button, V4(*SEL_BG, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, V4(*SEL_BG_HI, 1.0))
        if not enabled:
            imgui.begin_disabled()
        clicked = imgui.button(icon, size)
        if not enabled:
            imgui.end_disabled()
        if active:
            imgui.pop_style_color(2)
        _tip(tip)
        imgui.pop_id()
        return clicked and enabled

    def _cmd_btn(self, icon, cid, active=None, size=None, label=None):
        c = self.reg[cid]
        ok, why = c.state()
        sc = self.reg.all_shortcuts(cid)
        tip = c.name + (f"   ({sc})" if sc else "") + (f"\n{c.tip}" if c.tip else "") + (f"\n\n{why}" if not ok else "")
        if active is None and c.checked is not None:
            active = c.checked()
        text = icon if label is None else f"{icon}  {label}"
        if size is None and label is not None:
            size = V2(0, 0)
        if self._icon_btn(text, tip, ok, bool(active), size, sid=cid):
            self.reg.run(cid, self.msg)

    def _seg(self, sid, options, current, tips=None, width=0.0):
        """Segmented control. Returns the chosen index."""
        new = current
        imgui.push_id(sid)
        for i, text in enumerate(options):
            if i:
                imgui.same_line(0, 1)
            on = i == current
            if on:
                imgui.push_style_color(imgui.Col_.button, V4(*SEL_BG, 1.0))
                imgui.push_style_color(imgui.Col_.button_hovered, V4(*SEL_BG_HI, 1.0))
            if imgui.button(text, V2(width, 0)):
                new = i
            if on:
                imgui.pop_style_color(2)
            if tips:
                _tip(tips[i])
        imgui.pop_id()
        return new

    def _sep_v(self):
        imgui.same_line(0, 10 * self.ui_scale)
        p = imgui.get_cursor_screen_pos()
        h = imgui.get_frame_height()
        imgui.get_window_draw_list().add_line(V2(p.x, p.y + 2), V2(p.x, p.y + h - 2), col32(0.3, 0.31, 0.33), 1.0)
        imgui.dummy(V2(1, h))
        imgui.same_line(0, 10 * self.ui_scale)

    # property grid: label column + widget column, filtered by the panel's search box
    def _section(self, title, labels, default_open=True):
        f = self._flt
        title_hit = bool(f) and f in title.lower()
        if f and not title_hit and not any(f in l.lower() for l in labels):
            return False
        if f:
            imgui.set_next_item_open(True, imgui.Cond_.always)
        elif default_open:
            imgui.set_next_item_open(True, imgui.Cond_.once)
        if not imgui.collapsing_header(title):
            return False
        self._sec_match = title_hit
        T = imgui.TableFlags_
        imgui.begin_table("##t_" + title, 2, T.sizing_stretch_prop | T.pad_outer_x)
        imgui.table_setup_column("label", imgui.TableColumnFlags_.width_fixed, 104 * self.ui_scale)
        imgui.table_setup_column("value", imgui.TableColumnFlags_.width_stretch)
        return True

    def _end_section(self):
        imgui.end_table()
        imgui.spacing()

    def _row(self, label, tip=""):
        f = self._flt
        if f and not self._sec_match and f not in label.lower():
            return False
        imgui.table_next_row()
        imgui.table_set_column_index(0)
        imgui.align_text_to_frame_padding()
        if f and f in label.lower():
            imgui.text_colored(V4(*ACCENT, 1), label)
        else:
            imgui.text(label)
        _tip(tip)
        imgui.table_set_column_index(1)
        imgui.set_next_item_width(-1)
        return True

    def _finish_property_edit(self, cancel=False):
        if getattr(self, "_property_edit_key", None) is not None:
            if self.engine.edit_active:
                (self.engine.cancel_edit if cancel else self.engine.commit_edit)()
            self._property_edit_key = None

    def _edit_value(self, label, obj, attr, value, changed, multi=False, continuous=False, element=None):
        """One document transaction per gesture, including multi-layer controls."""
        eng = self.engine
        targets = self._sel_layers() if multi else [obj]
        if not any(target is obj for target in targets):
            targets = [obj] + targets
        targets = list({id(target): target for target in targets}.values())
        key = (id(obj), attr, label, element)
        active = imgui.is_item_active() if continuous else False
        deactivated = imgui.is_item_deactivated() if continuous else False
        if changed:
            if getattr(self, "_property_edit_key", None) not in (None, key):
                self._finish_property_edit()
            if not eng.edit_active:
                eng.begin_edit(targets, label=label)
            for target in targets:
                updated = copy.deepcopy(value)
                if element is not None:
                    updated = list(getattr(target, attr))
                    updated[element] = value
                eng.set_property(target, attr, updated)
            if continuous:
                self._property_edit_key = key
            else:
                eng.commit_edit()
        if continuous and getattr(self, "_property_edit_key", None) == key:
            if imgui.is_key_pressed(imgui.Key.escape):
                self._finish_property_edit(cancel=True)
            elif deactivated or (changed and not active):
                self._finish_property_edit()

    def _edit_properties(self, label, changes):
        """Commit a discrete compound action using the same engine edit contract."""
        self._finish_property_edit()
        self.engine.begin_edit([obj for obj, _ in changes], label=label)
        try:
            for obj, values in changes:
                self.engine.set_properties(obj, **values)
            return self.engine.commit_edit()
        except Exception:
            self.engine.cancel_edit()
            raise

    def p_slider(self, label, obj, attr, lo=0.0, hi=1.0, fmt="%.2f", dirty=False, log=False, tip="", multi=False):
        if not self._row(label, tip):
            return
        flags = imgui.SliderFlags_.logarithmic if log else 0
        ch, v = imgui.slider_float("##" + label, float(getattr(obj, attr)), lo, hi, fmt, flags)
        if dirty:
            self._edit_value(label, obj, attr, v, ch, multi=multi, continuous=True)
        _tip(tip + ("\n" if tip else "") + "Ctrl+click to type a value.")
        if ch and not dirty:
            setattr(obj, attr, v)
            if multi:
                for l in self._sel_layers():
                    setattr(l, attr, v)

    def p_combo(self, label, obj, attr, items, dirty=True, tip="", multi=False):
        if not self._row(label, tip):
            return
        ch, v = imgui.combo("##" + label, int(getattr(obj, attr)), items)
        if dirty:
            self._edit_value(label, obj, attr, v, ch, multi=multi)
        elif ch:
            setattr(obj, attr, v)
            if multi:
                for l in self._sel_layers():
                    setattr(l, attr, v)

    def p_color(self, label, obj, attr, dirty=False, tip=""):
        if not self._row(label, tip):
            return
        ch, c = imgui.color_edit3("##" + label, list(getattr(obj, attr)), imgui.ColorEditFlags_.no_inputs)
        if dirty:
            self._edit_value(label, obj, attr, list(c), ch, continuous=True)
        elif ch:
            setattr(obj, attr, list(c))

    def p_check(self, label, obj, attr, dirty=True, tip=""):
        if not self._row(label, tip):
            return
        ch, v = imgui.checkbox("##" + label, bool(getattr(obj, attr)))
        if dirty:
            self._edit_value(label, obj, attr, v, ch)
        elif ch:
            setattr(obj, attr, v)

    def p_channels(self, label, obj, dirty, multi=False, tip=""):
        if not self._row(label, tip):
            return
        en = list(obj.enabled)
        w = (imgui.get_content_region_avail().x - 3) / 4
        for i, name in enumerate(CHANNELS):
            if i % 4:
                imgui.same_line(0, 1)
            on = bool(en[i])
            if on:
                imgui.push_style_color(imgui.Col_.button, V4(*SEL_BG, 1.0))
            else:
                imgui.push_style_color(imgui.Col_.text, V4(*TEXT_DIM, 1))
            if imgui.button(f"{name}##ch{i}", V2(w, 0)):
                en[i] = not on
                if dirty:
                    changes = []
                    targets = self._sel_layers() if multi else [obj]
                    if not any(target is obj for target in targets):
                        targets = [obj] + targets
                    for target in targets:
                        enabled = list(target.enabled)
                        enabled[i] = en[i]
                        changes.append((target, {"enabled": enabled}))
                    self._edit_properties("Toggle " + name, changes)
                else:
                    obj.enabled = list(en)
            imgui.pop_style_color()
            _tip(f"{name} channel {'on' if on else 'off'}: click to toggle")

    # ------------------------------------------------------------------ selection
    def _sel_layers(self):
        return [l for l in self.engine.all_layers() if l.uid in self.sel_uids]

    def _sync_selection(self):
        eng = self.engine
        prim = eng.layer
        if (self.material_ui.transform_tool and
                (prim is None or prim.pid != self.material_ui.transform_layer_pid or (not prim.maps and prim.authored is None))):
            self._finish_fill_projection(cancel=True)
            self.material_ui.transform_tool = None
        if prim is None:
            self.sel_uids, self._last_primary = set(), None
            return
        if prim.uid != self._last_primary:
            self.sel_uids = {prim.uid}
            rows = [r[0] for r in self._flat()]
            self._anchor = next((k for k, l in enumerate(rows) if l is prim), -1)
        self.sel_uids &= {l.uid for l in eng.all_layers()}
        self.sel_uids.add(prim.uid)
        self._last_primary = prim.uid

    def _click_layer(self, lay, target=None, rows=None):
        """Select a layer row (Ctrl toggles, Shift selects a range of visible rows)."""
        eng = self.engine
        io = imgui.get_io()
        rows = rows if rows is not None else [r[0] for r in self._flat()]
        i = next((k for k, l in enumerate(rows) if l is lay), -1)
        if io.key_ctrl and target is None:
            if lay.uid in self.sel_uids and len(self.sel_uids) > 1:
                self.sel_uids.discard(lay.uid)
                if lay is eng.layer:
                    eng.select(next(l for l in rows if l.uid in self.sel_uids))
            else:
                self.sel_uids.add(lay.uid)
                eng.select(lay)
        elif io.key_shift and target is None and 0 <= self._anchor < len(rows) and i >= 0:
            a, b = sorted((self._anchor, i))
            self.sel_uids = {rows[j].uid for j in range(a, b + 1)}
            eng.select(lay)
        else:
            self.sel_uids = {lay.uid}
            eng.select(lay)
            self._anchor = i
        self._last_primary = eng.layer.uid if eng.layer is not None else None
        if target is not None:
            eng.brush.target = target
            if target == 1:
                eng.set_mask_paint_target(None)
        eng.dirty = True

    def _editing_context(self):
        """Shared target breadcrumb; display inspection never determines paint writes."""
        eng, b = self.engine, self.engine.brush
        if eng.ts is None:
            return "No project"
        parts = [eng.ts.name]
        if b.target == 2:
            parts.append("Quick mask")
        elif eng.layer is not None:
            parts += [eng.layer.name, "Mask" if b.target == 1 else "Content"]
            effect = eng.active_mask_paint() if b.target == 1 else None
            if effect is not None:
                parts.append(effect.name)
        else:
            parts.append("No layer selected")
        return " > ".join(parts)

    def _writing_channels(self):
        b = self.engine.brush
        if b.target:
            return "Grayscale"
        if b.user_channel:
            return b.user_channel
        return ", ".join(c.value_label or c.label for c in CHANNEL_DESCRIPTORS if b.enabled[c.index]) or "None"

    # ------------------------------------------------------------------ chrome: menu, toolbar, strips
    def _menu_cmd(self, cid, label=None):
        c = self.reg[cid]
        ok, why = c.state()
        checked = c.checked() if c.checked else False
        if imgui.menu_item(label or c.name, self.reg.shortcut(cid), checked, ok)[0]:
            self.reg.run(cid, self.msg)
        if not ok and why:
            _tip(why)

    def menu_bar(self):
        h = 0
        if imgui.begin_main_menu_bar():
            h = imgui.get_window_size().y
            if imgui.begin_menu("File"):
                for cid in ("file.new", "file.open", None, "file.import_spp", "file.import_preset", None,
                            "file.save", "file.save_as", "file.save_portable", "file.resources", "file.recover",
                            "file.autosave", None, "file.export", "file.delivery", None, "file.quit"):
                    imgui.separator() if cid is None else self._menu_cmd(cid)
                imgui.end_menu()
            if imgui.begin_menu("Edit"):
                for cid in ("edit.undo", "edit.redo", None, "edit.settings"):
                    imgui.separator() if cid is None else self._menu_cmd(cid)
                imgui.end_menu()
            if imgui.begin_menu("Mode"):
                self._menu_cmd("mode.paint")
                self._menu_cmd("mode.bake")
                self._menu_cmd("na.render")
                imgui.end_menu()
            if imgui.begin_menu("Layer"):
                self._menu_cmd("layer.add_paint"); self._menu_cmd("layer.add_fill")
                if imgui.begin_menu("Add smart material", self.engine.comp is not None):
                    for n in SMART_MATERIALS:
                        self._menu_cmd("smart." + n, n)
                    imgui.end_menu()
                imgui.separator()
                for cid in ("layer.duplicate", "layer.delete", "layer.up", "layer.down"):
                    self._menu_cmd(cid)
                imgui.separator()
                for cid in ("layer.mask_white", "layer.mask_black", "layer.mask_remove"):
                    self._menu_cmd(cid)
                if imgui.begin_menu("Mask generator", self._lay_ok() is True):
                    for k in range(1, len(GENERATORS)):
                        self._menu_cmd(f"gen.{k}", GENERATORS[k])
                    imgui.end_menu()
                imgui.separator()
                self._menu_cmd("layer.clear")
                imgui.separator()
                self._menu_cmd("layer.authored")
                self._menu_cmd("layer.channels")
                imgui.end_menu()
            if imgui.begin_menu("Viewport"):
                if imgui.begin_menu("Display channel"):
                    for i, n in enumerate(DISPLAY_MODES):
                        self._menu_cmd(f"view.mode{i}", n)
                    imgui.separator()
                    for cid in ("view.material", "view.next_channel", "view.prev_channel", "view.next_map", "view.prev_map"):
                        self._menu_cmd(cid)
                    imgui.end_menu()
                imgui.separator()
                for cid in ("view.split", "view.3d", "view.2d", None, "view.frame", "view.reset_2d", "view.frame_uv_tiles",
                            "view.material_tiles", "view.uv_wire", "view.hide_ui"):
                    imgui.separator() if cid is None else self._menu_cmd(cid)
                imgui.separator()
                self._menu_cmd("win." + W_DISPLAY, "Display settings...")
                imgui.end_menu()
            if imgui.begin_menu("Window"):
                for w in DOCKED:
                    self._menu_cmd("win." + w)
                imgui.separator()
                for w in FLOATING:
                    self._menu_cmd("win." + w)
                imgui.separator()
                self._menu_cmd("win.reset", "Reset layout")
                self._menu_cmd("win.palette", "Command palette...")
                imgui.end_menu()
            extension_menus = {}
            for cid in self.reg.order:
                if cid.startswith("extension."):
                    extension_menus.setdefault(self.reg[cid].category, []).append(cid)
            for category, commands in extension_menus.items():
                if imgui.begin_menu(category):
                    for cid in commands:self._menu_cmd(cid)
                    imgui.end_menu()
            if imgui.begin_menu("Help"):
                self._menu_cmd("help.shortcuts")
                self._menu_cmd("win.palette", "Find any command...")
                imgui.end_menu()
            # right side: command search, Painter users look for it top-right
            label = f"{ICON.search}  Search commands   {self.reg.shortcut('win.palette')}"
            w = imgui.calc_text_size(label).x + 16 * self.ui_scale
            imgui.same_line(imgui.get_window_width() - w - 8 * self.ui_scale)
            imgui.push_style_color(imgui.Col_.button, V4(0.17, 0.18, 0.2, 1))
            if imgui.small_button(label):
                self.palette.request()
            imgui.pop_style_color()
            _tip("Find and run any action, layer operation, material or panel by name.")
            imgui.end_main_menu_bar()
        return h

    def _fixed_window(self, name, x, y, w, h, pad=(6, 5)):
        imgui.set_next_window_pos(V2(x, y))
        imgui.set_next_window_size(V2(w, h))
        W = imgui.WindowFlags_
        flags = (W.no_decoration | W.no_move | W.no_saved_settings | W.no_bring_to_front_on_focus
                 | W.no_docking | W.no_scroll_with_mouse | W.no_nav_focus)
        imgui.push_style_var(imgui.StyleVar_.window_padding, V2(pad[0] * self.ui_scale, pad[1] * self.ui_scale))
        imgui.begin(name, None, flags)
        imgui.pop_style_var()

    def toolbar(self, ww, top):
        """Painter's contextual toolbar: settings of the active tool, always in reach."""
        s = self.ui_scale
        h = round(imgui.get_frame_height() + 10 * s)
        self._fixed_window("##toolbar", 0, top, ww, h)
        eng, b = self.engine, self.engine.brush
        icon, name = self._tool_label()
        imgui.align_text_to_frame_padding()
        imgui.text_colored(V4(*ACCENT, 1), f"{icon}  {name}")
        self._sep_v()
        log = imgui.SliderFlags_.logarithmic
        if self.poly_fill:
            imgui.align_text_to_frame_padding()
            imgui.text_disabled("Fill")
            imgui.same_line()
            imgui.set_next_item_width(120 * s)
            ch, v = imgui.combo("##tb_fill", self.fill_mode, FILL_MODES)
            if ch:
                self.fill_mode = v
            _tip("What one click fills")
            imgui.same_line()
            b.mode = self._seg("tb_fmode", ["Fill", "Erase"], b.mode, ["Fill with the brush material  (4)", "Erase  (2 is the Eraser)"])
            imgui.same_line()
        else:
            _, _, slo, shi, sfmt = self.bsize.spec
            items = [("Size", "@size", slo, shi, sfmt, 104, log,
                      f"Brush size, {self.bsize.spec[0].lower()} space  ([ ]  or Ctrl+Right drag)"),
                     ("Flow", "flow", 0, 1, "%.2f", 70, 0, "Paint per dab  (Ctrl+Left drag)"),
                     ("Hardness", "hardness", 0, 1, "%.2f", 70, 0, "Edge hardness  (Ctrl+Right drag vertically)"),
                     ("Spacing", "spacing", 0.02, 1, "%.2f", 64, 0, "Distance between dabs, relative to size")]
            if b.tool == TOOL_SMUDGE:
                items.append(("Strength", "smudge_strength", 0, 1, "%.2f", 70, 0, "How far paint is dragged"))
            for label, attr, lo, hi, fmt, w, flags, tip in items:
                imgui.align_text_to_frame_padding()
                imgui.text_disabled(label)
                imgui.same_line()
                imgui.set_next_item_width(w * s)
                obj, at = (self.bsize, "value") if attr == "@size" else (b, attr)
                ch, v = imgui.slider_float(f"##tb_{attr}", float(getattr(obj, at)), lo, hi, fmt, flags)
                if ch:
                    setattr(obj, at, v)
                _tip(tip)
                imgui.same_line()
        self._sep_v()
        if self.quick_edit:
            imgui.align_text_to_frame_padding()
            imgui.text_colored(V4(*WARN_COL, 1), f"{ICON.quickmask}  Editing quick mask")
            _tip("U applies it,  I inverts,  Y clears")
            imgui.same_line()
        else:
            imgui.align_text_to_frame_padding()
            imgui.text_disabled("Paint into")
            imgui.same_line()
            t = self._seg("tb_target", [f"{ICON.layers} Layer", f"{ICON.mask} Mask"], min(b.target, 1),
                          ["Paint the layer's content", "Paint the layer's mask (or click the mask thumbnail)"])
            if b.target != t:
                self._set_target(t)
            imgui.same_line()
        if b.target in (1, 2):
            v = self._seg("tb_mval", ["White", "Black"], 0 if b.mask_value > 0.5 else 1,
                          ["Reveal  (X swaps)", "Hide  (X swaps)"])
            b.mask_value = 1.0 if v == 0 else 0.0
        else:
            lay = eng.layer
            if lay is not None and lay.kind == "paint" and b.tool in (TOOL_PAINT,) and not b.mode:
                ch, c = imgui.color_edit3("##tb_color", list(b.color),
                                          imgui.ColorEditFlags_.no_inputs | imgui.ColorEditFlags_.no_label)
                if ch:
                    b.color = list(c)
                _tip("Brush base colour  (P picks it from the model)")
        self._sep_v()
        if self._icon_btn(f"{ICON.sym} Symmetry", "Mirror painting  (L)", active=b.symmetry > 0, size=V2(0, 0)):
            self._toggle_symmetry()
        if b.symmetry:
            imgui.same_line()
            ax = self._seg("tb_axis", ["X", "Y", "Z"], int(b.sym_axis) % 3, ["Mirror across X", "Across Y", "Across Z"])
            b.sym_axis = ax
        imgui.same_line()
        if self._icon_btn(f"{ICON.lazy} Lazy", "Lazy mouse: the brush trails the cursor for smooth lines  (D)",
                          active=b.lazy > 0, size=V2(0, 0)):
            self._toggle_lazy()
        if b.lazy > 0:
            imgui.same_line()
            imgui.set_next_item_width(60 * s)
            ch, v = imgui.slider_float("##tb_lazy", float(b.lazy), 1, 200, "%.0f px")
            if ch:
                b.lazy = v
        # right-aligned: undo / redo / export, when there is room
        fhh = imgui.get_frame_height()
        right_w = fhh * 1.15 * 2 + imgui.calc_text_size(f"{ICON.export}  Export").x + 40 * s
        imgui.same_line()
        if imgui.get_cursor_pos_x() < ww - right_w:
            imgui.set_cursor_pos_x(ww - right_w)
            self._cmd_btn(ICON.undo, "edit.undo")
            imgui.same_line()
            self._cmd_btn(ICON.redo, "edit.redo")
            imgui.same_line()
            self._cmd_btn(ICON.export, "file.export", label="Export")
        else:
            imgui.dummy(V2(1, 1))
        imgui.end()
        return h

    def tool_strip(self, top, bottom):
        s = self.ui_scale
        w = round(42 * s)
        self._fixed_window("##tools", 0, top, w, bottom - top, pad=(4, 6))
        bs = V2(w - 8 * s, w - 8 * s)
        for icon, cid in ((ICON.paint, "tool.paint"), (ICON.erase, "tool.erase"), (ICON.image, "tool.projection"),
                          (ICON.polyfill, "tool.fill"), (ICON.smudge, "tool.smudge"), (ICON.clone, "tool.clone")):
            self._cmd_btn(icon, cid, size=bs)
        imgui.separator()
        self._cmd_btn(ICON.picker, "tool.pick", size=bs, active=False)
        self._cmd_btn(ICON.mask, "tool.target", size=bs)
        self._cmd_btn(ICON.quickmask, "quick.edit", size=bs)
        n_bottom = 3
        y = imgui.get_window_height() - n_bottom * (bs.y + imgui.get_style().item_spacing.y) - 6 * s
        if y > imgui.get_cursor_pos_y():
            imgui.set_cursor_pos_y(y)
        self._cmd_btn(ICON.frame, "view.frame", size=bs)
        self._cmd_btn(ICON.hide, "view.hide_ui", size=bs)
        self._cmd_btn(ICON.search, "win.palette", size=bs)
        imgui.end()
        return w

    def dock_strip(self, ww, top, bottom):
        """Painter's right-edge dock: secondary panels one click away."""
        s = self.ui_scale
        w = round(40 * s)
        self._fixed_window("##dockstrip", ww - w, top, w, bottom - top, pad=(4, 6))
        bs = V2(w - 8 * s, w - 8 * s)
        for icon, win in ((ICON.sun, W_DISPLAY), (ICON.history, W_HISTORY), (ICON.log, W_LOG),
                          (ICON.keys, W_KEYS), (ICON.gear, W_SETTINGS)):
            p = imgui.get_cursor_screen_pos()
            self._strip_btn_pos[win] = (p.x, p.y)
            self._cmd_btn(icon, "win." + win, size=bs)
        imgui.end()
        return w

    # ------------------------------------------------------------------ panels
    def panels(self, ww):
        for name, fn in ((W_ASSETS, self.assets_panel), (W_TSL, self.texset_panel),
                         (W_LAYERS, self.layers_panel), (W_TSS, self.texset_settings_panel),
                         (W_PROPS, self.properties_panel), (W_AI, self.assistant_ui.draw)):
            if not self.show[name]:
                continue
            if (name == W_LAYERS and self._focus_layers
                    and not imgui.is_popup_open("", imgui.PopupFlags_.any_popup_id | imgui.PopupFlags_.any_popup_level)):
                imgui.set_next_window_focus()      # Layer Stack is the front tab, as in Painter
                self._focus_layers -= 1
            if name == W_AI:
                # Add the new tab without resetting a user's saved layout.
                properties = imgui.internal.find_window_by_name(W_PROPS)
                if properties is not None and properties.dock_id:
                    imgui.set_next_window_dock_id(properties.dock_id, imgui.Cond_.first_use_ever)
                imgui.set_next_window_size(V2(370 * self.ui_scale, 430 * self.ui_scale), imgui.Cond_.first_use_ever)
            visible, _ = imgui.begin(name, None)   # docked panels close from the Window menu only
            if name != W_AI or visible:
                fn()
            imgui.end()
        s = self.ui_scale
        sizes = {W_DISPLAY: (330, 330), W_HISTORY: (300, 360), W_LOG: (460, 260), W_KEYS: (560, 600),
                 W_SETTINGS: (360, 260)}
        for i, (name, fn) in enumerate(((W_DISPLAY, self.display_panel), (W_HISTORY, self.history_panel),
                                        (W_LOG, self.log_panel), (W_KEYS, self.keys_panel),
                                        (W_SETTINGS, self.settings_panel))):
            if not self.show[name]:
                continue
            w, h = sizes[name][0] * s, sizes[name][1] * s
            bx, by = self._strip_btn_pos.get(name, (ww - 60 * s, 110 * s))
            imgui.set_next_window_pos(V2(bx - w - 6 * s, by), imgui.Cond_.first_use_ever)
            imgui.set_next_window_size(V2(w, h), imgui.Cond_.first_use_ever)
            vis, opened = imgui.begin(name, True)
            if vis:
                fn()
            imgui.end()
            if not opened:
                self.show[name] = False

    # --- Assets ---------------------------------------------------------------
    def assets_panel(self):
        s = self.ui_scale
        tabs = [("Smart", "smart", "Smart materials: ready-made layer stacks"),
                ("Materials", "mat", "Single materials"),
                ("Generators", "gen", "Mask generators driven by the baked mesh maps"),
                ("Native", "native", "Portable native materials, masks, brushes and export templates"),
                ("Substance", "substance", "Smart materials and smart masks from Substance 3D Painter\n"
                                           "(your shelf and Painter's starter assets)")]
        kind = getattr(self, "asset_tab", "smart")
        req, self.asset_tab_request = getattr(self, "asset_tab_request", None), None
        if imgui.begin_tab_bar("##asset_tabs", imgui.TabBarFlags_.fitting_policy_shrink):
            for label, k, tip in tabs:
                flags = imgui.TabItemFlags_.set_selected if req == k else 0
                if imgui.begin_tab_item(label, None, flags)[0]:
                    kind = k
                    imgui.end_tab_item()
                _tip(tip)
            imgui.end_tab_bar()
        self.asset_tab = kind
        imgui.set_next_item_width(-70 * s)
        _, self.asset_query = imgui.input_text_with_hint("##asearch", f"{ICON.search}  Search", self.asset_query)
        imgui.same_line()
        imgui.set_next_item_width(-1)
        ch, t = imgui.slider_int("##thumb", self.thumb, 40, 140, "")
        if ch:
            self.thumb = t
        if imgui.is_item_deactivated_after_edit():
            self._save_settings()
        _tip("Thumbnail size")
        if kind == "substance":
            self._substance_assets()
            return
        if kind == "native":
            self.native_ui.draw()
            return
        hint = {"smart": "Double-click or drag onto the Layer Stack.",
                "mat": "Click: use for brush / selected fill.  Double-click or drag: new fill layer.",
                "gen": "Double-click, or drag onto a layer, to drive its mask."}[kind]
        imgui.push_text_wrap_pos(0)
        imgui.text_disabled(hint)
        imgui.pop_text_wrap_pos()
        imgui.begin_child("##grid")
        q = self.asset_query.lower().strip()
        items = []
        for gi, (k, key) in enumerate(self._assets):
            if k != kind:
                continue
            label = GENERATORS[key] if k == "gen" else key
            if q and q not in label.lower():
                continue
            items.append((gi, k, key, label))
        t = self.thumb * s
        sp = imgui.get_style().item_spacing.x
        cols = max(1, int((imgui.get_content_region_avail().x + sp) // (t + sp)))
        for n, (gi, k, key, label) in enumerate(items):
            if n % cols:
                imgui.same_line()
            self._asset_tile(gi, k, key, label, t)
        if not items:
            imgui.text_disabled("Nothing matches.")
        imgui.end_child()

    def _substance_assets(self):
        """Assets > Substance: Painter smart materials / masks found on disk, with their thumbnails."""
        s = self.ui_scale
        self._poll_thumbs()
        n_mat = sum(1 for i in self.sp_items if i.kind == "smart_material")
        n_msk = len(self.sp_items) - n_mat
        half = max((imgui.get_content_region_avail().x - 1) / 2, 40 * s)
        self.sp_kind = self._seg("##spkind", [f"Smart materials ({n_mat})", f"Smart masks ({n_msk})"], self.sp_kind,
                                 ["Painter layer presets: double-click or drag onto the Layer Stack",
                                  "Painter mask presets: double-click to apply to the selected layer,\n"
                                  "or drag onto a layer"], width=half)
        if self._icon_btn(ICON.open, "Add a folder with .spsm / .spmsk files"):
            self._add_sp_folder()
        imgui.same_line()
        if self._icon_btn(ICON.refresh, "Rescan folders"):
            self._scan_substance()
        imgui.same_line()
        imgui.push_text_wrap_pos(0)
        imgui.text_disabled("Approximated: Painter's procedural textures become Strata generators and noise.")
        imgui.pop_text_wrap_pos()
        want = "smart_material" if self.sp_kind == 0 else "smart_mask"
        q = self.asset_query.lower().strip()
        items = [(i, it) for i, it in enumerate(self.sp_items) if it.kind == want
                 and (not q or q in it.name.lower() or q in it.category.lower() or q in it.source.lower())]
        imgui.begin_child("##spgrid")
        if not self.sp_items:
            imgui.push_text_wrap_pos(0)
            imgui.text_disabled("No Substance Painter smart materials or masks were found. Painter's starter "
                                "assets and your shelf are picked up automatically when Painter is installed; "
                                "otherwise add a folder, or drag a .spsm / .spmsk / .spp file onto the window.")
            imgui.pop_text_wrap_pos()
            if imgui.button("Add folder...", V2(-1, 0)):
                self._add_sp_folder()
            if imgui.button("Import a file...", V2(-1, 0)):
                self._ask_import_preset()
        t = self.thumb * s
        sp = imgui.get_style().item_spacing.x
        cols = max(1, int((imgui.get_content_region_avail().x + sp) // (t + sp)))
        last_cat = None
        n = 0
        for idx, it in items:
            cat = f"{it.source} / {it.category}" if it.category else it.source
            if cat != last_cat:
                if n:
                    imgui.new_line()
                imgui.text_disabled(cat)
                last_cat, n = cat, 0
            if n % cols:
                imgui.same_line()
            self._sp_tile(idx, it, t)
            n += 1
        if self.sp_items and not items:
            imgui.text_disabled("Nothing matches.")
        imgui.end_child()

    def _sp_tile(self, idx, it, t):
        imgui.push_id(f"sp{idx}")
        p = imgui.get_cursor_screen_pos()
        th = imgui.get_text_line_height()
        clicked = imgui.invisible_button("##tile", V2(t, t + th + 4))
        hovered = imgui.is_item_hovered()
        dbl = hovered and imgui.is_mouse_double_clicked(0)
        dl = imgui.get_window_draw_list()
        sel = self.asset_sel == ("sp", idx)
        dl.add_rect_filled(p, V2(p.x + t, p.y + t), col32(0.2, 0.21, 0.23) if hovered else col32(0.155, 0.16, 0.17), 4)
        # draw the thumbnail once the tile is on screen (lazy loading)
        tex = self._sp_thumb(it.path) if imgui.is_item_visible() else self.sp_thumbs.get(it.path)
        if tex is not None:
            dl.add_image(imgui.ImTextureRef(tex.glo), V2(p.x + 2, p.y + 2), V2(p.x + t - 2, p.y + t - 2))
        else:
            self._ball(dl, p.x + t / 2, p.y + t / 2, t * 0.3, (0.35, 0.36, 0.38), 0.6, 0.0)
        if it.kind == "smart_mask":
            dl.add_text(V2(p.x + 5, p.y + 3), col32(1, 1, 1, 0.8), "mask")
        if sel or hovered:
            dl.add_rect(p, V2(p.x + t, p.y + t), col32(*ACCENT, 1.0 if sel else 0.6), rounding=4, thickness=2)
        name = _ellipsize(it.name, t)
        tw = imgui.calc_text_size(name).x
        dl.add_text(V2(p.x + (t - tw) / 2, p.y + t + 2), imgui.get_color_u32(imgui.Col_.text), name)
        if imgui.begin_drag_drop_source():
            imgui.set_drag_drop_payload_py_id("STRATA_SP", idx)
            imgui.text(it.name)
            imgui.text_disabled("Drop on the Layer Stack" if it.kind == "smart_material" else "Drop on a layer")
            imgui.end_drag_drop_source()
        if clicked:
            self.asset_sel = ("sp", idx)
        if dbl:
            if self.engine.comp is None:
                self.msg("Open or create a project first.")
            elif it.kind == "smart_material":
                self._add_sp_smart(it.path)
            elif self._lay_ok() is True:
                self._apply_sp_mask(it.path)
            else:
                self.msg("Select a layer first, then apply the smart mask to it.")
        if hovered and imgui.begin_item_tooltip():
            imgui.text(it.name)
            imgui.text_disabled(("Smart material" if it.kind == "smart_material" else "Smart mask")
                                + (f"  -  {it.category}" if it.category else "") + f"  -  {it.source}")
            cached = next((v for k, v in self.sp_cache.items() if k[0] == it.path), None)
            if cached is not None and it.kind == "smart_material":
                imgui.text_disabled("Layers: " + ", ".join(il.layer.name for il in cached.layers))
            imgui.text_disabled(it.path)
            imgui.end_tooltip()
        imgui.pop_id()

    def _asset_tile(self, gi, kind, key, label, t):
        imgui.push_id(f"asset{gi}")
        p = imgui.get_cursor_screen_pos()
        th = imgui.get_text_line_height()
        clicked = imgui.invisible_button("##tile", V2(t, t + th + 4))
        hovered = imgui.is_item_hovered()
        dbl = hovered and imgui.is_mouse_double_clicked(0)
        dl = imgui.get_window_draw_list()
        sel = self.asset_sel == gi
        bg = col32(0.2, 0.21, 0.23) if hovered else col32(0.155, 0.16, 0.17)
        dl.add_rect_filled(p, V2(p.x + t, p.y + t), bg, 4)
        self._draw_asset_thumb(dl, kind, key, p, t)
        if sel or hovered:
            dl.add_rect(p, V2(p.x + t, p.y + t), col32(*ACCENT, 1.0 if sel else 0.6), rounding=4, thickness=2)
        name = _ellipsize(label, t)
        tw = imgui.calc_text_size(name).x
        dl.add_text(V2(p.x + (t - tw) / 2, p.y + t + 2), imgui.get_color_u32(imgui.Col_.text), name)
        if imgui.begin_drag_drop_source():
            imgui.set_drag_drop_payload_py_id("STRATA_ASSET", gi)
            imgui.text(label)
            imgui.text_disabled("Drop on the Layer Stack")
            imgui.end_drag_drop_source()
        if clicked:
            self.asset_sel = gi
            if kind == "mat":
                self._use_material(key)
        if dbl:
            if kind == "mat":
                self._add_fill_material(key)
            elif kind == "smart":
                self._add_smart(key)
            elif self._lay_ok() is True:
                self._apply_generator(key)
            else:
                self.msg("Select a layer first, then apply a mask generator to it.")
        if hovered and imgui.begin_item_tooltip():
            imgui.text(label)
            if kind == "smart":
                imgui.text_disabled("Layers: " + ", ".join(l.name for l in self._smart_cache[key]))
            elif kind == "mat":
                c, r, m = MATERIALS[key]
                imgui.text_disabled(f"Roughness {r:.2f}   Metallic {m:.0f}")
            else:
                imgui.text_disabled(GEN_INFO.get(key, ""))
            imgui.end_tooltip()
        imgui.pop_id()

    def _sphere_preview(self, dl, layers, p, t):
        if not hasattr(self, "material_previews"):
            self.material_previews = MaterialPreviews(self.engine)
        try:
            texture = self.material_previews.texture(layers)
            dl.add_image(imgui.ImTextureRef(texture.glo), p, V2(p.x + t, p.y + t), V2(0, 1), V2(1, 0))
        except Exception as error:
            message = f"Material preview failed: {error}"
            if message != getattr(self, "_material_preview_error", None):
                self.msg(message)
                self._material_preview_error = message

    def _ball(self, dl, cx, cy, r, col, rough=0.5, metal=0.0):
        # Also used for the placeholder while a Substance thumbnail loads.
        layer = preset_fill("Preview", "Steel", color=list(col), rough=rough, metal=metal, seed=0.0)
        self._sphere_preview(dl, [layer], V2(cx - r / 0.72, cy - r / 0.72), r * 2 / 0.72)

    def _draw_asset_thumb(self, dl, kind, key, p, t):
        if kind == "mat":
            self._sphere_preview(dl, [preset_fill(key, key, seed=0.0)], p, t)
        elif kind == "smart":
            self._sphere_preview(dl, self._smart_cache[key], p, t)
        else:
            m = t * 0.14
            a, b = V2(p.x + m, p.y + m), V2(p.x + t - m, p.y + t - m)
            W, K = col32(0.92, 0.92, 0.92), col32(0.06, 0.06, 0.06)
            G = col32(0.5, 0.5, 0.5)
            if key == 1:      # edge wear: bright rim
                dl.add_rect_filled(a, b, K, 3)
                dl.add_rect(a, b, W, rounding=3, thickness=t * 0.06)
            elif key == 2:    # dirt: dark corners
                dl.add_rect_filled_multi_color(a, b, K, G, K, W)
            elif key in (3, 5):
                dl.add_rect_filled_multi_color(a, b, W, W, K, K)
            elif key == 4:    # upward facing
                mid = V2(b.x, (a.y + b.y) / 2)
                dl.add_rect_filled(a, mid, W)
                dl.add_rect_filled_multi_color(V2(a.x, mid.y), b, G, G, K, K)
            else:             # noise
                rng = np.random.default_rng(key)
                n = 6
                cs = (b.x - a.x) / n
                for i in range(n):
                    for j in range(n):
                        v = float(rng.uniform(0.05, 0.95))
                        dl.add_rect_filled(V2(a.x + i * cs, a.y + j * cs), V2(a.x + (i + 1) * cs, a.y + (j + 1) * cs),
                                           col32(v, v, v))

    # --- Texture sets ---------------------------------------------------------
    def texset_panel(self):
        eng = self.engine
        for i, ts in enumerate(eng.sets):
            if imgui.button((ICON.eye if ts.visible else ICON.eye_off) + f"##ts_visibility_{i}"):
                ts.visible = not ts.visible
            _tip("Hide in 3D scene" if ts.visible else "Show in 3D scene")
            imgui.same_line()
            label = f"{ICON.box}  {ts.name}##ts{i}"
            if imgui.selectable(label, i == eng.active)[0] and i != eng.active:
                eng.set_active(i)
                self.sel_uids, self._last_primary = set(), None
            if imgui.is_item_hovered():
                self._hover_set = i
            if imgui.begin_popup_context_item("##texture_set_menu" + ts.pid):
                if imgui.menu_item("Isolate this texture set", "Alt+Q", self.isolate and i == eng.active)[0]:
                    eng.set_active(i)
                    self.isolate = not self.isolate
                for text, value in (("Show all texture sets", True), ("Hide all texture sets", False)):
                    if imgui.menu_item(text)[0]:
                        for item in eng.sets:
                            item.visible = value
                        self.isolate = False
                imgui.end_popup()
            _tip("Click to paint this texture set.  Ctrl+Alt+Right click in the viewport picks the set under the cursor.")
            r = f"{ts.res} px"
            imgui.same_line(imgui.get_window_width() - imgui.calc_text_size(r).x - 14 * self.ui_scale)
            imgui.text_disabled(r)
        extra = "  |  isolated (Alt+Q)" if self.isolate else ""
        imgui.text_disabled(f"{len(eng.all_layers())} layers  |  {len(eng.mesh.positions):,} verts{extra}")

    def texset_settings_panel(self):
        eng = self.engine
        self._flt = ""
        if imgui.button("Material tiles..."):
            self.tiles_ui.open = True
        if self._section("Texture set", ["Resolution", "Normal from height"]):
            self.material_ui.texture_set_resolution()
            self.p_slider("Normal from height", eng, "normal_strength", 0.0, 5.0, dirty=True,
                          tip="How strongly the height channel turns into normal-map detail.")
            self._end_section()
        if self._section("Channels", []):
            for channel, i in zip(CHANNEL_DESCRIPTORS, CHANNEL_MODES):
                if self._row(channel.value_label):
                    if imgui.small_button(f"View##ch{i}"):
                        eng.renderer.mode, eng.dirty = i, True
            self._end_section()
        self.bake_ui.mesh_maps()
        if self._section("Mesh maps (baked)", []):
            for name, mode, tip in (("Ambient occlusion", 7, "Drives Dirt / AO generators"),
                                    ("Curvature", 8, "Drives Edge Wear"),
                                    ("World position", None, "Drives Upward Facing / Height Gradient"),
                                    ("World normal", None, ""), ("UV coverage", 9, "Padding / UV checker")):
                if self._row(name, tip):
                    if mode is None:
                        imgui.text_disabled("baked")
                    elif imgui.small_button(f"View##mm{mode}"):
                        eng.renderer.mode, eng.dirty = mode, True
            self._end_section()

    # --- Layer stack ----------------------------------------------------------
    def layers_panel(self):
        eng = self.engine
        s = self.ui_scale
        imgui.set_next_item_width(-1)
        _, self.layer_channel = imgui.combo("##layer_channel", self.layer_channel,
                                          ["All channels"] + [c.value_label for c in CHANNEL_DESCRIPTORS])
        _tip("Inspect blend/opacity for this channel. This does not change brush channel enables or the viewport.")
        self._cmd_btn(ICON.paint, "layer.add_paint")
        imgui.same_line(0, 2)
        self._cmd_btn(ICON.fill, "layer.add_fill")
        imgui.same_line(0, 2)
        self._cmd_btn(ICON.folder, "layer.add_group")
        imgui.same_line(0, 2)
        if self._icon_btn(ICON.smart, "Add smart material..."):
            imgui.open_popup("##smart_pop")
        imgui.same_line(0, 2)
        if self._icon_btn(ICON.mask, "Add mask / mask generator...", eng.layer is not None):
            imgui.open_popup("##mask_pop")
        self._sep_v()
        self._cmd_btn(ICON.copy, "layer.duplicate")
        imgui.same_line(0, 2)
        self._cmd_btn(ICON.up, "layer.up")
        imgui.same_line(0, 2)
        self._cmd_btn(ICON.down, "layer.down")
        imgui.same_line(0, 2)
        self._cmd_btn(ICON.trash, "layer.delete")
        if imgui.begin_popup("##smart_pop"):
            _esc_closes()
            imgui.text_disabled("Smart materials")
            for n in SMART_MATERIALS:
                if imgui.selectable(n, False)[0]:
                    self._add_smart(n)
            imgui.end_popup()
        if imgui.begin_popup("##mask_pop"):
            _esc_closes()
            for cid in ("layer.mask_white", "layer.mask_black", "layer.mask_remove", "layer.mask_toggle"):
                self._menu_cmd(cid)
            imgui.separator()
            imgui.text_disabled("Generator")
            for k in range(1, len(GENERATORS)):
                self._menu_cmd(f"gen.{k}", GENERATORS[k])
            imgui.end_popup()
        n_sel = len(self.sel_uids)
        if n_sel > 1:
            imgui.text_colored(V4(*ACCENT, 1), f"{n_sel} layers selected: Properties edits apply to all")

        imgui.begin_child("##stack", V2(0, 0), imgui.ChildFlags_.borders)
        row_h = round(38 * s)
        ts = row_h - 10 * s
        indent = 16 * s
        dl = imgui.get_window_draw_list()
        rows = self._flat()
        row_layers = [r[0] for r in rows]
        drop_asset = drop_layer = drop_sp = drop_native = None
        io = imgui.get_io()
        for lay, depth, parent in rows:
            imgui.push_id(str(lay.uid))
            p = imgui.get_cursor_screen_pos()
            w = imgui.get_content_region_avail().x
            primary = lay is eng.layer
            selected = lay.uid in self.sel_uids
            imgui.set_next_item_allow_overlap()
            clicked = imgui.invisible_button("##row", V2(w, row_h))
            hovered = imgui.is_item_hovered()
            if imgui.begin_drag_drop_source():
                imgui.set_drag_drop_payload_py_id("STRATA_LAYER", lay.uid)
                imgui.text(lay.name)
                imgui.text_disabled("Drag top/bottom to insert; drop in a folder's center to nest.")
                imgui.end_drag_drop_source()
            if imgui.begin_drag_drop_target():
                fraction = (io.mouse_pos.y - p.y) / row_h
                placement = ("inside" if lay.is_group and .25 <= fraction <= .75
                             else "above" if fraction < .5 else "below")
                if placement != "inside":
                    line_y = p.y if placement == "above" else p.y + row_h
                    dl.add_line(V2(p.x, line_y), V2(p.x + w, line_y), col32(*ACCENT), 2 * s)
                pl = imgui.accept_drag_drop_payload_py_id("STRATA_LAYER")
                if pl is not None:
                    drop_layer = (pl.data_id, lay, placement)
                pl = imgui.accept_drag_drop_payload_py_id("STRATA_ASSET")
                if pl is not None:
                    drop_asset = (pl.data_id, lay)
                pl = imgui.accept_drag_drop_payload_py_id("STRATA_SP")
                if pl is not None:
                    drop_sp = (pl.data_id, lay)
                pl = imgui.accept_drag_drop_payload_py_id("STRATA_NATIVE")
                if pl is not None:
                    drop_native = (pl.data_id, lay)
                imgui.end_drag_drop_target()
            if imgui.begin_popup_context_item("##ctx"):
                _esc_closes()
                if not selected:
                    self._click_layer(lay, rows=row_layers)
                self._layer_context_menu(lay)
                imgui.end_popup()
            if clicked:
                self._click_layer(lay, rows=row_layers)
            if hovered and imgui.is_mouse_double_clicked(0):
                self.renaming, self.rename_buf, self._rename_focus = lay.uid, lay.name, True
            if primary:
                bg = col32(*SEL_BG, 1.0)
            elif selected:
                bg = col32(*SEL_BG_SOFT, 1.0)
            elif hovered:
                bg = col32(1, 1, 1, 0.05)
            else:
                bg = col32(0, 0, 0, 0)
            dl.add_rect_filled(p, V2(p.x + w, p.y + row_h), bg, 3)
            dl.add_line(V2(p.x, p.y + row_h), V2(p.x + w, p.y + row_h), col32(1, 1, 1, 0.05))
            fh = imgui.get_frame_height()
            x = p.x + 3 * s
            # eye
            imgui.set_cursor_screen_pos(V2(x, p.y + (row_h - fh) / 2))
            imgui.push_style_color(imgui.Col_.button, V4(0, 0, 0, 0))
            if imgui.button(ICON.eye if lay.visible else ICON.eye_off, V2(fh, fh)):
                v = not lay.visible
                self._edit_properties("Toggle layer visibility", [
                    (l, {"visible": v}) for l in (self._sel_layers() if selected else [lay])])
            _tip("Show / hide layer")
            x += fh + 2 * s + depth * indent
            # folder: expand arrow
            if lay.is_group:
                imgui.set_cursor_screen_pos(V2(x, p.y + (row_h - fh) / 2))
                if imgui.button(ICON.caret_d if lay.expanded else ICON.caret_r, V2(fh * 0.8, fh)):
                    lay.expanded = not lay.expanded
                _tip("Expand / collapse folder")
                x += fh * 0.8 + 2 * s
            imgui.pop_style_color()
            ty = p.y + (row_h - ts) / 2
            imgui.set_cursor_screen_pos(V2(x, ty))
            if imgui.invisible_button("##content", V2(ts, ts)):
                self._click_layer(lay, target=0, rows=row_layers)
            _tip("Folder" if lay.is_group else "Layer content: click to paint / edit the layer itself")
            self._layer_thumb(dl, lay, x, ty, ts)
            if primary and eng.brush.target == 0:
                dl.add_rect(V2(x - 2, ty - 2), V2(x + ts + 2, ty + ts + 2), col32(1, 1, 1, 0.9), rounding=3, thickness=2)
            x += ts + 4 * s
            has_mask = lay.has_mask or lay.gen.kind or lay.mask_effects
            if has_mask:
                imgui.set_cursor_screen_pos(V2(x, ty))
                if imgui.invisible_button("##mask", V2(ts, ts)):
                    if io.key_alt:
                        self._click_layer(lay, rows=row_layers)
                        r = eng.renderer
                        r.mode, eng.dirty = (0 if r.mode == 6 else 6), True
                    elif io.key_shift:
                        self._toggle_mask(lay)
                    else:
                        self._click_layer(lay, target=1, rows=row_layers)
                _tip("Mask: click to paint it.  Alt+click shows it in the viewport, Shift+click disables it."
                     + (f"\nGenerator: {GENERATORS[lay.gen.kind]}" if lay.gen.kind else ""))
                self._mask_thumb(dl, lay, x, ty, ts)
                if primary and eng.brush.target == 1:
                    dl.add_rect(V2(x - 2, ty - 2), V2(x + ts + 2, ty + ts + 2), col32(1, 1, 1, 0.9), rounding=3, thickness=2)
                x += ts + 6 * s
            ci = self.layer_channel - 1
            blend = lay.blend if ci < 0 or lay.chan_blend[ci] in (None, -1) else lay.chan_blend[ci]
            opacity = lay.opacity if ci < 0 else lay.chan_opacity[ci]
            bname = BLEND_MODES[blend] if 0 <= blend < len(BLEND_MODES) else "?"
            bo = f"{BLEND_SHORT.get(bname, bname[:4])} {int(round(opacity * 100))}"
            bw = imgui.calc_text_size("Ovrl 100").x + imgui.get_style().frame_padding.x * 2 + 4 * s
            bx = p.x + w - bw - 4 * s
            imgui.set_cursor_screen_pos(V2(bx, p.y + (row_h - fh) / 2))
            imgui.push_style_color(imgui.Col_.button, V4(0, 0, 0, 0))
            if imgui.button(bo, V2(bw, fh)):
                self._click_layer(lay, rows=row_layers)
                imgui.open_popup("##blend")
            imgui.pop_style_color()
            _tip("Blend mode and opacity: click to change")
            if imgui.begin_popup("##blend"):
                _esc_closes()
                imgui.set_next_item_width(180 * s)
                modes = ["Inherit layer"] + BLEND_MODES if ci >= 0 else BLEND_MODES
                current = 0 if ci >= 0 and lay.chan_blend[ci] in (None, -1) else blend + (1 if ci >= 0 else 0)
                ch, v = imgui.combo("Blend", current, modes)
                self._edit_value("Layer blend", lay, "chan_blend" if ci >= 0 else "blend",
                                 v - 1 if ci >= 0 else v, ch, multi=True, element=ci if ci >= 0 else None)
                imgui.set_next_item_width(180 * s)
                ch, v = imgui.slider_float("Opacity", opacity, 0, 1, "%.2f")
                self._edit_value("Layer opacity", lay, "chan_opacity" if ci >= 0 else "opacity", v, ch,
                                 multi=True, continuous=True, element=ci if ci >= 0 else None)
                imgui.end_popup()
            name_w = bx - x - 4 * s
            if self.renaming == lay.uid:
                imgui.set_cursor_screen_pos(V2(x, p.y + (row_h - fh) / 2))
                imgui.set_next_item_width(name_w)
                if self._rename_focus:
                    imgui.set_keyboard_focus_here()
                    self._rename_focus = False
                F = imgui.InputTextFlags_
                enter, self.rename_buf = imgui.input_text("##rename", self.rename_buf, F.enter_returns_true | F.auto_select_all)
                if imgui.is_key_pressed(imgui.Key.escape):
                    self.renaming = None
                elif enter or imgui.is_item_deactivated():
                    if self.rename_buf.strip():
                        self._edit_properties("Rename layer", [(lay, {"name": self.rename_buf.strip()})])
                    self.renaming = None
            else:
                tcol = imgui.get_color_u32(imgui.Col_.text) if lay.visible else col32(*TEXT_DIM)
                lh = imgui.get_text_line_height()
                dl.add_text(V2(x, p.y + row_h / 2 - lh + 1), tcol, _ellipsize(lay.name, name_w))
                if lay.is_group:
                    sub, kc = f"Folder | {len(lay.children)} layers", TEXT_DIM
                else:
                    sub = "Paint" if lay.kind == "paint" else "Fill"
                    kc = PAINT_COL if lay.kind == "paint" else FILL_COL
                if lay.gen.kind:
                    sub += " | " + GENERATORS[lay.gen.kind]
                elif lay.has_mask:
                    sub += " | painted mask"
                if has_mask and not lay.mask_enabled:
                    sub += " (mask off)"
                dl.add_text(V2(x, p.y + row_h / 2 + 1), col32(*kc, 0.75), _ellipsize(sub, name_w))
            imgui.set_cursor_screen_pos(V2(p.x, p.y + row_h + 1))
            if primary:
                self.effects_ui.rows(lay, eng.brush.target == 1)
            imgui.pop_id()
        avail = imgui.get_content_region_avail()
        imgui.invisible_button("##drop_bottom", V2(max(avail.x, 1), max(avail.y, row_h)))
        if imgui.begin_drag_drop_target():
            pl = imgui.accept_drag_drop_payload_py_id("STRATA_ASSET")
            if pl is not None:
                drop_asset = (pl.data_id, None)
            pl = imgui.accept_drag_drop_payload_py_id("STRATA_SP")
            if pl is not None:
                drop_sp = (pl.data_id, None)
            pl = imgui.accept_drag_drop_payload_py_id("STRATA_NATIVE")
            if pl is not None:
                drop_native = (pl.data_id, None)
            pl = imgui.accept_drag_drop_payload_py_id("STRATA_LAYER")
            if pl is not None:
                drop_layer = (pl.data_id, None, "below")
            imgui.end_drag_drop_target()
        if not eng.layers:
            imgui.set_cursor_pos(V2(10 * s, 10 * s))
            imgui.text_disabled("Empty. Add a layer with the buttons above,\nor drag a material from Assets.")
        imgui.end_child()
        if drop_layer is not None:
            uid, dst, placement = drop_layer
            src = next((l for l in eng.all_layers() if l.uid == uid), None)
            if src is not None:
                self._drop_layer_on(src, dst, placement)
        if drop_asset is not None:
            gi, dst = drop_asset
            kind, key = self._assets[gi]
            if dst is None:
                parent, index = None, 0
            elif dst.is_group:
                parent, index = dst, len(dst.children)
            else:
                _, i, parent = eng.find(dst)
                index = i + 1
            if kind == "mat":
                self._add_fill_material(key, index=index, parent=parent)
            elif kind == "smart":
                self._add_smart(key, index=index, parent=parent)
            elif dst is not None:
                self._apply_generator(key, layer=dst)
            else:
                self.msg("Drop a mask generator onto a layer.")
        if drop_native is not None:
            self.native_ui.drop(*drop_native)
        if drop_sp is not None and 0 <= drop_sp[0] < len(self.sp_items):
            it, dst = self.sp_items[drop_sp[0]], drop_sp[1]
            if it.kind == "smart_material":
                top = dst                          # imported stacks go in at the top level, above dst's folder
                while top is not None:
                    _, i, par = eng.find(top)
                    if par is None:
                        break
                    top = par
                self._add_sp_smart(it.path, index=0 if top is None else i + 1)
            elif dst is not None:
                eng.select(dst)
                self._sync_selection()
                self._apply_sp_mask(it.path, replace=io.key_ctrl)
            else:
                self.msg("Drop a smart mask onto a layer.")

    def _layer_context_menu(self, lay):
        if imgui.menu_item("Rename", "Double-click", False)[0]:
            self.renaming, self.rename_buf, self._rename_focus = lay.uid, lay.name, True
        if imgui.begin_menu("Add effect"):
            mask = self.engine.brush.target == 1
            for kind in (MASK_EFFECTS if mask else CONTENT_EFFECTS):
                if imgui.menu_item(kind.replace("_", " ").title())[0]:
                    effect = self.engine.add_effect(kind, layer=lay, mask=mask)
                    self.effects_ui.selected[(lay.pid, mask)] = effect.pid
                    self.prop_filter = "Mask effects" if mask else "Content effects"
            imgui.end_menu()
        for cid in ("layer.copy", "layer.cut", "layer.paste", "layer.duplicate", "layer.delete", None,
                    "layer.copy_content", "layer.paste_content", None, "layer.group", "layer.ungroup",
                    "layer.up", "layer.down", None, "layer.mask_white", "layer.mask_black", "layer.mask_remove",
                    "layer.mask_toggle"):
            imgui.separator() if cid is None else self._menu_cmd(cid)
        if imgui.begin_menu("Mask generator"):
            for k in range(1, len(GENERATORS)):
                self._menu_cmd(f"gen.{k}", GENERATORS[k])
            if imgui.menu_item("None", "", lay.gen.kind == 0)[0]:
                self._apply_generator(0)
            imgui.end_menu()
        imgui.separator()
        self._menu_cmd("layer.clear")

    def _layer_thumb(self, dl, lay, x, y, ts):
        a, b = V2(x, y), V2(x + ts, y + ts)
        if lay.is_group:
            dl.add_rect_filled(a, b, col32(0.17, 0.18, 0.2), 3)
            g = ICON.folder_open if lay.expanded else ICON.folder
            gs = imgui.calc_text_size(g)
            dl.add_text(V2(x + (ts - gs.x) / 2, y + (ts - gs.y) / 2), col32(*FILL_COL), g)
        elif lay.kind == "fill":
            dl.add_rect_filled(a, b, col32(0.1, 0.1, 0.11), 3)
            self._sphere_preview(dl, [lay], a, ts)
        else:
            h = ts / 2
            for i in range(2):
                for j in range(2):
                    c = 0.32 if (i + j) % 2 else 0.22
                    dl.add_rect_filled(V2(x + i * h, y + j * h), V2(x + (i + 1) * h, y + (j + 1) * h), col32(c, c, c))
            g = ICON.paint
            gs = imgui.calc_text_size(g)
            dl.add_text(V2(x + (ts - gs.x) / 2, y + (ts - gs.y) / 2), col32(*PAINT_COL), g)
        dl.add_rect(a, b, col32(0, 0, 0, 0.6), 3)
        dl.add_line(V2(x, y + ts + 1), V2(x + ts, y + ts + 1),
                    col32(.85, .25, .23) if lay.effects else col32(.4, .4, .4), 2)

    def _mask_thumb(self, dl, lay, x, y, ts):
        a, b = V2(x, y), V2(x + ts, y + ts)
        W, K, G = col32(0.92, 0.92, 0.92), col32(0.05, 0.05, 0.05), col32(0.5, 0.5, 0.5)
        if lay.gen.kind or lay.mask_effects:
            dl.add_rect_filled_multi_color(a, b, W, G, K, G)
            g = ICON.generator
            gs = imgui.calc_text_size(g)
            dl.add_text(V2(x + (ts - gs.x) / 2, y + (ts - gs.y) / 2), col32(*ACCENT), g)
        else:
            dl.add_rect_filled(a, V2(x + ts / 2, y + ts), W)
            dl.add_rect_filled(V2(x + ts / 2, y), b, K)
        if not lay.mask_enabled:                      # Shift+click: mask bypassed
            dl.add_rect_filled(a, b, col32(0.1, 0.1, 0.1, 0.6))
            dl.add_line(a, b, col32(0.95, 0.35, 0.3), 2)
        dl.add_rect(a, b, col32(0, 0, 0, 0.6), 3)
        dl.add_line(V2(x, y + ts + 1), V2(x + ts, y + ts + 1),
                    col32(.85, .25, .23) if lay.mask_effects else col32(.4, .4, .4), 2)

    # --- Properties -----------------------------------------------------------
    def properties_panel(self):
        if self.workspace_mode == "bake":
            self.bake_ui.workspace()
            return
        eng, b = self.engine, self.engine.brush
        lay = eng.layer
        s = self.ui_scale
        crumb = self._editing_context()
        imgui.text_disabled(_ellipsize(crumb, imgui.get_content_region_avail().x))
        _tip(crumb)
        imgui.text_wrapped("Writes: " + self._writing_channels())
        n_sel = len(self.sel_uids)
        if n_sel > 1:
            imgui.text_colored(V4(*ACCENT, 1), f"{n_sel} layers selected: layer settings apply to all")
        imgui.set_next_item_width(-1)
        _, self.prop_filter = imgui.input_text_with_hint("##pfilter", f"{ICON.search}  Search properties", self.prop_filter)
        self._flt = self.prop_filter.strip().lower()
        imgui.begin_child("##props")
        brush_rel = (lay is None or lay.kind == "paint" or b.target in (1, 2) or self.poly_fill
                     or b.tool != TOOL_PAINT)
        if lay is None:
            imgui.push_text_wrap_pos(0)
            imgui.text_colored(V4(*WARN_COL, 1), "No layer selected. Add a paint layer (Layer Stack, first button) "
                                                 "or double-click a material in Assets.")
            imgui.pop_text_wrap_pos()
        if lay is not None and lay.kind == "fill" and b.target == 0:
            self._props_fill(lay)
        if b.target == 1 and lay is not None:
            self._props_mask_paint()
        if brush_rel:
            self._props_brush()
            if b.target == 0 and (lay is None or lay.kind == "paint"):
                self._props_brush_material()
        if lay is not None:
            self._props_layer(lay)
            self._props_mask(lay)
            self.effects_ui.draw(lay)
        if self._flt and not imgui.is_any_item_hovered() and imgui.get_cursor_pos_y() < 30 * s:
            imgui.text_disabled("No property matches.")
        imgui.end_child()

    def _load_image(self, title):
        if pfd is None:
            self.msg("File dialogs unavailable")
            return ""
        r = pfd.open_file(title, "", ["Images", "*.png *.jpg *.jpeg *.tga *.tif *.tiff *.exr *.hdr *.bmp *.webp"]).result()
        return r[0] if r else ""

    def _load_mesh_file(self, title):
        if pfd is None:
            self.msg("Native file dialog is unavailable.")
            return ""
        result = pfd.open_file(title, "", ["Meshes", "*.obj *.fbx *.gltf *.glb *.ply *.stl"]).result()
        return result[0] if result else ""

    def _load_native_file(self):
        if pfd is None:
            return ""
        result = pfd.open_file("Native asset", "", ["Strata assets", "*.ssmat *.ssmask *.sbrush *.json"]).result()
        return result[0] if result else ""

    def _props_brush(self):
        e, b = self.engine, self.engine.brush
        labels = ["Tool", "Fill mode", "Size", "Hardness", "Flow", "Spacing", "Angle", "Grain", "Grain scale",
                  "Strength", "Clone source", "Lazy mouse", "Symmetry", "Axis", "Copies", "Size space",
                  "Alpha", "Invert alpha", "Stroke opacity", "Alignment", "Backface angle", "Follow angle",
                  "Size jitter", "Flow jitter", "Angle jitter", "Position jitter", "Pressure size", "Pressure flow",
                  "Minimum size", "Minimum flow", "Jitter seed", "Symmetry center", "Tablet input", "2D alignment"]
        if self._section("Brush", labels):
            tools = [("Paint", "tool.paint"), ("Eraser", "tool.erase"), ("Projection", "tool.projection"),
                     ("Polygon fill", "tool.fill"), ("Smudge", "tool.smudge"), ("Clone (relative)", "tool.clone"),
                     ("Clone (absolute)", "tool.clone_abs")]
            if self._row("Tool", "1 Paint, 2 Eraser, 3 Projection, 4 Polygon fill, 5 Smudge, 6 Clone"):
                cur = next((i for i, (_, c) in enumerate(tools) if self.reg[c].checked()), 0)
                ch, v = imgui.combo("##tool", cur, [f"{n}   ({self.reg.shortcut(c)})" for n, c in tools])
                if ch:
                    self.reg.run(tools[v][1], self.msg)
            if not self.poly_fill:
                self._draw_brush_preview()
            if self.poly_fill:
                if self._row("Fill mode", "What one click fills"):
                    _, self.fill_mode = imgui.combo("##fillmode", self.fill_mode, FILL_MODES)
                if e.ts.tiles is not None:
                    imgui.text_wrapped(f"Tiled fill rasterizes this paint target at {e.res}px. Later resizing resamples it.")
            else:
                if self._row("Size space", "World: the brush covers the same area of the mesh at any zoom\n"
                                           "Screen: the brush keeps the same size on screen\n"
                                           "UV: the brush covers the same area of the texture"):
                    names = [n for n, *_ in SIZE_SPACE_UI]
                    ch, v = imgui.combo("##sizespace", int(b.size_space), names)
                    if ch:
                        self._set_size_space(v)
                _, why, slo, shi, sfmt = self.bsize.spec
                self.p_slider("Size", self.bsize, "value", slo, shi, sfmt, log=True,
                              tip=f"Size in {why}\n[ ]  or  Ctrl+Right drag")
                self.p_slider("Hardness", b, "hardness", tip="Ctrl+Right drag vertically")
                self.p_slider("Flow", b, "flow", tip="Ctrl+Left drag")
                self.p_slider("Spacing", b, "spacing", 0.02, 1.0, tip="Distance between dabs, relative to size")
                self._advanced_brush()
                self.p_slider("Angle", b, "angle", 0.0, 360.0, "%.0f deg", tip="Ctrl+Left drag vertically")
                self.p_slider("Grain", b, "grain", tip="Breaks the dab up with noise")
                if b.grain > 0:
                    self.p_slider("Grain scale", b, "grain_scale", 2, 200, "%.0f", log=True)
                if b.tool == TOOL_SMUDGE:
                    self.p_slider("Strength", b, "smudge_strength", tip="How far paint is dragged")
                if b.tool == TOOL_CLONE and self._row("Clone source", "Hold V and click on the model"):
                    imgui.text_disabled("set  (V + click to move it)" if e.clone_source is not None or e.clone_uv_source is not None else "V + click to set")
            if self._row("Lazy mouse", "D toggles. 0 = off"):
                ch, v = imgui.slider_float("##lazy", float(b.lazy), 0, 200, "%.0f px" if b.lazy else "off")
                if ch:
                    b.lazy = v
            self.p_combo("Symmetry", b, "symmetry", SYMMETRY, dirty=False, tip="L toggles")
            if b.symmetry:
                if self._row("Axis"):
                    b.sym_axis = self._seg("p_axis", ["X", "Y", "Z"], int(b.sym_axis) % 3, None,
                                           (imgui.get_content_region_avail().x - 2) / 3)
                if b.symmetry == 2 and self._row("Copies"):
                    _, b.radial_count = imgui.slider_int("##radial", int(b.radial_count), 2, 32)
                if self._row("Symmetry center", "Center in normalized object coordinates"):
                    ch, v = imgui.input_float3("##symcenter", b.sym_center)
                    if ch and all(math.isfinite(x) for x in v):
                        b.sym_center = list(v)
            self._end_section()
        labels = ["Stencil image", "Ignore stencil", "Tiling"]
        if self._section("Stencil", labels, default_open=bool(b.stencil)):
            if self._row("Stencil image", "Masks the brush through a screen-space image. Place it with S + mouse."):
                bw = (imgui.get_content_region_avail().x - 2) / 2
                if imgui.button("Load..." if not b.stencil else os.path.basename(b.stencil)[:18], V2(bw, 0)):
                    p = self._load_image("Stencil image")
                    if p:
                        b.stencil, b.stencil_enabled = p, True
                        b.stencil_xform = [0.5, 0.5, 1.0, 0.0]
                imgui.same_line(0, 2)
                imgui.begin_disabled(not b.stencil)
                if imgui.button("Clear##st", V2(-1, 0)):
                    b.stencil = None
                imgui.end_disabled()
            if b.stencil:
                if self._row("Ignore stencil", "N"):
                    ch, v = imgui.checkbox("##ign", not b.stencil_enabled)
                    if ch:
                        b.stencil_enabled = not v
                self.p_combo("Tiling", b, "stencil_tiling", STENCIL_TILING, dirty=False)
                imgui.text_disabled("S + Left drag rotate, Middle move, Right scale")
            self._end_section()
        if b.tool == TOOL_PROJECTION and not self.poly_fill:
            if self._section("Projection", [c.value_label + " image" for c in CHANNEL_DESCRIPTORS] + ["Tiling"]):
                for channel in CHANNEL_DESCRIPTORS:
                    if not self._row(channel.value_label + " image", "Screen projection. Place it with S + mouse."):
                        continue
                    imgui.push_id("projection_" + channel.key)
                    cur = b.proj_maps.get(channel.key)
                    if imgui.button(os.path.basename(cur)[:18] if cur else "Load..."):
                        p = self._load_image(channel.value_label + " projection")
                        if p:
                            try:
                                e.resources.texture(p, channel.resource_kind)
                                b.proj_maps = {**b.proj_maps, channel.key: p}
                                b.enabled[channel.index] = True
                            except Exception as error:
                                self.msg(f"Projection image failed: {error}")
                    imgui.same_line()
                    if imgui.button("Clear##pj"):
                        b.proj_maps.pop(channel.key, None)
                    imgui.pop_id()
                self.p_combo("Tiling", b, "proj_tiling", STENCIL_TILING, dirty=False)
                imgui.text_disabled("S + Left drag rotate, Middle move, Right scale")
                self._end_section()

    def _advanced_brush(self):
        b = self.engine.brush
        if self._row("Alpha", "Round, built-in shape, or an image file"):
            choices = ["Round"] + BUILTIN_ALPHAS + ["Image..."]
            name = (b.alpha or "").removeprefix("builtin:")
            cur = BUILTIN_ALPHAS.index(name) + 1 if name in BUILTIN_ALPHAS else (len(choices) - 1 if b.alpha else 0)
            ch, v = imgui.combo("##alpha", cur, choices)
            if ch:
                if v == len(choices) - 1:
                    path = self._load_image("Brush alpha")
                    if path:
                        try:
                            self.engine.resources.alpha(path)
                            b.alpha = path
                        except Exception as error:
                            self.msg(f"Alpha image failed: {error}")
                else:
                    b.alpha = "builtin:" + choices[v] if v else None
            if b.alpha and cur == len(choices) - 1:
                imgui.text_disabled(os.path.basename(b.alpha))
        self.p_check("Invert alpha", b, "alpha_invert", dirty=False)
        if b.tool in (TOOL_SMUDGE, TOOL_CLONE):
            if self._row("Stroke opacity"):
                imgui.text_wrapped("Use Flow for clone/smudge; stroke opacity applies to paint/projection.")
        else:
            self.p_slider("Stroke opacity", b, "stroke_opacity")
        if self._row("2D alignment"):
            imgui.text_wrapped("UV strokes align in texture space. Object symmetry and polygon fill use 3D.")
        self.p_combo("Alignment", b, "alignment", ALIGNMENTS, dirty=False, tip="3D alignment; 2D strokes always align in UV space")
        self.p_slider("Backface angle", b, "backface", 1, 180, "%.0f deg")
        self.p_check("Follow angle", b, "follow_path", dirty=False)
        for label, attr in (("Size jitter", "size_jitter"), ("Flow jitter", "flow_jitter"),
                            ("Angle jitter", "angle_jitter"), ("Position jitter", "pos_jitter")):
            self.p_slider(label, b, attr)
        if self._row("Jitter seed", "Same seed and samples reproduce the same jitter; frozen at stroke start"):
            ch, value = imgui.input_int("##seed", int(b.seed))
            if ch:
                b.seed = value % (2 ** 31)
        self.p_check("Pressure size", b, "pressure_size", dirty=False)
        self.p_slider("Minimum size", b, "min_size", tip="Size fraction at zero pressure")
        self.p_check("Pressure flow", b, "pressure_flow", dirty=False)
        self.p_slider("Minimum flow", b, "min_flow", tip="Flow fraction at zero pressure")
        if self._row("Tablet input"):
            imgui.text_wrapped(self.tablet.status)
            imgui.text_disabled(f"{self.tablet.source}: {self.tablet.pressure:.2f}")

    def _draw_brush_preview(self):
        if not hasattr(self, "brush_preview"):
            self.brush_preview = BrushPreview()
        try:
            texture = self.brush_preview.update(self.engine)
        except (OSError, ValueError, MemoryError) as error:
            imgui.text_disabled("Brush preview unavailable")
            _tip(str(error))
            return
        width = max(1, min(imgui.get_content_region_avail().x, self.brush_preview.SIZE * self.ui_scale))
        crop = self.brush_preview.CROP
        imgui.image(imgui.ImTextureRef(texture.glo), V2(width, width * (1 - 2 * crop)),
                    V2(0, 1 - crop), V2(1, crop))
        _tip("Brush tip and sample stroke on a flat surface, with rising pressure. "
             "Preview size is fitted to this panel.")

    def _props_brush_material(self):
        b = self.engine.brush
        labels = ["Preview", "Channels"] + [channel.value_label for channel in CHANNEL_DESCRIPTORS]
        labels += [channel.value_label + " map" for channel in CHANNEL_DESCRIPTORS]
        if not self._section("Material (brush)", labels):
            return
        if self._row("Preview"):
            size = min(64 * self.ui_scale, imgui.get_content_region_avail().x)
            if size > 0:
                p = imgui.get_cursor_screen_pos()
                imgui.dummy(V2(size, size))
                imgui.get_window_draw_list().add_circle_filled(
                    V2(p.x + size / 2, p.y + size / 2), size / 2, col32(*b.color))
        self.p_channels("Channels", b, False, tip="Which channels the brush paints")
        self._material_channels(b, dirty=False)
        for channel in CHANNEL_DESCRIPTORS:
            if not self._row(channel.value_label + " map", "Image stamped by the Paint tool."):
                continue
            key = channel.key
            path = b.maps.get(key)
            imgui.push_id("brush_map_" + key)
            if path:
                imgui.text_wrapped(os.path.basename(path))
                _tip(path)
            if imgui.button("Replace..." if path else "Load..."):
                replacement = self._load_image(channel.value_label + " brush map")
                if replacement:
                    try:
                        self.engine.resources.texture(replacement, channel.resource_kind)
                        b.maps = {**b.maps, key: replacement}
                        b.enabled[channel.index] = True
                    except Exception as error:
                        self.msg(f"Brush map failed: {error}")
            if path:
                imgui.same_line()
                if imgui.button("Clear"):
                    b.maps = {k: value for k, value in b.maps.items() if k != key}
            imgui.pop_id()
        self._end_section()

    def _material_channels(self, obj, dirty):
        for channel in CHANNEL_DESCRIPTORS:
            tip = channel.semantic
            if channel.key == "H":
                tip = "0.5 = flat, above 0.5 raised, below carved"
            elif channel.key == "N":
                tip = "Encoded tangent-space normal: (0.5, 0.5, 1) is flat"
            elif channel.key == "O":
                tip = "Opacity channel value; layer opacity controls the whole layer separately"
            imgui.begin_disabled(bool(getattr(obj, "maps", {}).get(channel.key)))
            if channel.value_components == 3:
                self.p_color(channel.value_label, obj, channel.attribute, dirty=dirty, tip=tip)
            else:
                self.p_slider(channel.value_label, obj, channel.attribute, dirty=dirty, tip=tip)
            imgui.end_disabled()

    def _props_mask_paint(self):
        b = self.engine.brush
        if not self._section("Mask painting", ["Paint value"]):
            return
        if self._row("Paint value", "X swaps white and black"):
            v = self._seg("p_mval", ["White (show)", "Black (hide)"], 0 if b.mask_value > 0.5 else 1,
                          ["Reveal the layer  (X)", "Hide the layer  (X)"], (imgui.get_content_region_avail().x - 1) / 2)
            b.mask_value = 1.0 if v == 0 else 0.0
        self._end_section()

    def _props_fill(self, lay):
        labels = [channel.value_label for channel in CHANNEL_DESCRIPTORS]
        if self._section("Fill material", labels):
            self._material_channels(lay, dirty=True)
            self._end_section()
            if lay.maps:
                imgui.text_wrapped("Bitmap maps override matching constants. Clear a bitmap slot to edit its constant.")
        labels = ["Color / rough noise", "Height noise", "Noise scale", "Random seed"]
        if self._section("Variation", labels):
            self.p_slider("Color / rough noise", lay, "variation", dirty=True)
            self.p_slider("Height noise", lay, "bump", dirty=True)
            self.p_slider("Noise scale", lay, "var_scale", 0.1, 20, dirty=True, log=True)
            if self._row("Random seed"):
                if imgui.button("New seed", V2(-1, 0)):
                    import random
                    self._edit_properties("Randomize material", [(lay, {"seed": random.random()})])
            self._end_section()

        self.material_ui.draw(lay)

    def _props_layer(self, lay):
        eng = self.engine
        labels = ["Name", "Blend", "Opacity", "Height blend", "Channels", "Painting"]
        if not self._section("Layer", labels):
            self.material_ui.channel_blending(lay)
            return
        if self._row("Name", "Double-click the layer to rename it in place"):
            ch, name = imgui.input_text("##name", lay.name)
            self._edit_value("Rename layer", lay, "name", name, ch, continuous=True)
        self.p_combo("Blend", lay, "blend", BLEND_MODES, multi=True)
        self.p_slider("Opacity", lay, "opacity", dirty=True, multi=True)
        self.p_combo("Height blend", lay, "hblend", HEIGHT_BLEND, multi=True,
                     tip="Normal replaces height; Add stacks it on top of the layers below")
        self.p_channels("Channels", lay, True, multi=True, tip="Which channels this layer affects")
        if lay.kind == "paint" and self._row("Painting"):
            if imgui.button("Clear painting", V2(-1, 0)):
                eng.clear_paint()
        self._end_section()
        self.material_ui.channel_blending(lay)

    def _props_mask(self, lay):
        eng = self.engine
        g = lay.gen
        labels = ["Painted mask", "Generator", "Level", "Softness", "Noise breakup", "Noise scale", "Invert", "Preview"]
        if not self._section("Mask", labels):
            return
        if self._row("Painted mask", "A paintable black/white mask. Combines with the generator."):
            bw = (imgui.get_content_region_avail().x - 2) / 3
            if not lay.has_mask:
                if imgui.button("Add white", V2(bw * 1.5, 0)):
                    eng.add_mask(1.0)
                imgui.same_line(0, 2)
                if imgui.button("Add black", V2(-1, 0)):
                    eng.add_mask(0.0)
            else:
                if imgui.button("Fill white", V2(bw, 0)):
                    eng.fill_mask(1.0)
                imgui.same_line(0, 1)
                if imgui.button("Fill black", V2(bw, 0)):
                    eng.fill_mask(0.0)
                imgui.same_line(0, 1)
                if imgui.button("Remove", V2(-1, 0)):
                    eng.remove_mask()
        self.p_combo("Generator", g, "kind", GENERATORS,
                     tip="Procedural mask from the baked mesh maps. Also: drag one from Assets.")
        if g.kind:
            self.p_slider("Level", g, "level", dirty=True)
            self.p_slider("Softness", g, "softness", 0.0, 0.5, dirty=True)
            if g.kind != 6:
                self.p_slider("Noise breakup", g, "noise_amount", 0.0, 1.5, dirty=True)
            self.p_slider("Noise scale", g, "noise_scale", 0.1, 10, dirty=True, log=True)
            self.p_check("Invert", g, "invert")
        if self._row("Preview"):
            on = eng.renderer.mode == 6
            if imgui.button("Back to material view" if on else "Show mask in viewport", V2(-1, 0)):
                eng.renderer.mode, eng.dirty = (0 if on else 6), True
        self._end_section()

    # --- secondary panels -----------------------------------------------------
    def display_panel(self):
        eng, r = self.engine, self.engine.renderer
        self._flt = ""
        if self._section("Color workflow", ["Working space", "Display transform", "Tangent basis"]):
            if self._row("Working space"):
                imgui.text_wrapped("Linear Rec.709 (managed)" if eng.color.managed else "Legacy encoded RGB")
            if self._row("Display transform"):
                imgui.text_wrapped("sRGB / Un-tone-mapped" if eng.color.managed else "Legacy ACES-style curve")
            if self._row("Tangent basis"):
                basis = eng.mesh.extra.get("tangent_basis", {})
                imgui.text_wrapped(basis.get("name", "Legacy") + (" / Blender " + basis["version"] if basis.get("backend") == "Blender" else ""))
            self._end_section()
        if self._section("View", ["Display", "Layout"]):
            before_mode = r.mode
            self.p_combo("Display", r, "mode", DISPLAY_MODES, dirty=False, tip="C cycles through the channels")
            if r.mode != before_mode:
                eng.dirty = True
            if self._row("Layout", "F1 split, F2 3D, F3 2D"):
                mode = [VIEW_3D, VIEW_SPLIT, VIEW_2D].index(self.view_mode)
                v = self._seg("lay", ["3D", "3D + 2D", "2D"], mode, ["F2", "F1", "F3"],
                              (imgui.get_content_region_avail().x - 2) / 3)
                self.view_mode = [VIEW_3D, VIEW_SPLIT, VIEW_2D][v]
            self._end_section()
        if self._section("Lighting", ["Exposure", "Light rotation", "Baked AO"]):
            if self._row("Environment"):
                if imgui.button("Load environment..."):
                    path = self._load_image("Environment image")
                    if path:
                        try:
                            eng.set_environment(path)
                        except Exception as error:
                            self.msg(f"Environment failed: {error}")
                if r.env_path:
                    imgui.text_wrapped(os.path.basename(r.env_path))
                    if imgui.button("Use studio environment"):
                        eng.set_environment(None)
            self.p_slider("Exposure", r, "exposure", 0.1, 4.0)
            self.p_slider("Light rotation", r, "env_rot", -3.1416, 3.1416, tip="Shift + Right drag in the viewport")
            self.p_slider("Emissive intensity", r, "emissive_intensity", 0., 20.)
            self.p_check("Alpha test", r, "alpha_test", dirty=False)
            if self._row("Baked AO", "Darken with the baked ambient occlusion"):
                ch, v = imgui.checkbox("##ao", r.use_ao)
                if ch:
                    r.use_ao = v
            self._end_section()
        if self._section("Camera", ["Frame"]):
            if self._row("Frame"):
                if imgui.button("Frame mesh  (F)", V2(-1, 0)):
                    eng.camera.frame(eng.mesh.center, eng.mesh.radius)
            self._end_section()

    def history_panel(self):
        eng = self.engine
        undo, redo = eng.undo_stack, eng.redo_stack

        def label(e):
            if e[0] == "stack":
                return f"{ICON.layers}  Layer stack change"
            if e[0] in ("properties", "resources", "bakes"):
                return f"{ICON.layers}  {e[3]}"
            if e[0] == "mask":
                return f"{ICON.paint}  Mask change on {e[1].name}"
            kind = "Mask paint" if "mask" in e[2] else "Paint"
            return f"{ICON.paint}  {kind} on {e[1].name}"

        imgui.text_disabled(f"Click a step to go back to it. Keeps {len(undo)} of max {eng.history_limit} steps.")
        imgui.text_disabled(f"History {eng.history_usage() / 1024**2:.1f} MiB / {eng.history_budget_bytes / 1024**2:.0f} MiB")
        target = None
        if imgui.selectable("Oldest kept state", len(undo) == 0)[0]:
            target = 0
        for k, e in enumerate(undo):
            if imgui.selectable(f"{label(e)}##u{k}", k == len(undo) - 1)[0]:
                target = k + 1
        for k, e in enumerate(reversed(redo)):
            imgui.push_style_color(imgui.Col_.text, V4(*TEXT_DIM, 1))
            if imgui.selectable(f"{label(e)}##r{k}", False)[0]:
                target = len(undo) + k + 1
            imgui.pop_style_color()
        if target is not None:
            while len(eng.undo_stack) > target:
                eng.undo()
            while len(eng.undo_stack) < target and eng.redo_stack:
                eng.redo()

    def log_panel(self):
        if imgui.small_button("Clear"):
            self.log.clear()
        imgui.begin_child("##logc")
        for t, m in self.log:
            imgui.text_disabled(t)
            imgui.same_line()
            imgui.text_wrapped(m)
        if imgui.get_scroll_y() >= imgui.get_scroll_max_y() - 4:
            imgui.set_scroll_here_y(1.0)
        imgui.end_child()

    def keys_panel(self):
        s = self.ui_scale
        imgui.set_next_item_width(-1)
        _, self.keys_filter = imgui.input_text_with_hint("##kf", f"{ICON.search}  Filter", self.keys_filter)
        f = self.keys_filter.lower().strip()
        imgui.begin_child("##keys")
        if imgui.collapsing_header("Mouse and viewport", imgui.TreeNodeFlags_.default_open):
            if imgui.begin_table("##mouse", 2, imgui.TableFlags_.row_bg):
                for a, b in MOUSE_HELP:
                    if f and f not in (a + b).lower():
                        continue
                    imgui.table_next_row()
                    imgui.table_next_column(); imgui.text(a)
                    imgui.table_next_column(); imgui.text_disabled(b)
                imgui.end_table()
        if imgui.collapsing_header("Commands (click a shortcut to change it)", imgui.TreeNodeFlags_.default_open):
            if self.rebind:
                imgui.text_colored(V4(*WARN_COL, 1), f"Press the new shortcut for '{self.reg[self.rebind].name}'. "
                                                     "Esc cancels, Backspace clears.")
            T = imgui.TableFlags_
            if imgui.begin_table("##cmds", 3, T.row_bg | T.sizing_stretch_prop):
                imgui.table_setup_column("cmd", imgui.TableColumnFlags_.width_stretch)
                imgui.table_setup_column("key", imgui.TableColumnFlags_.width_fixed, 150 * s)
                imgui.table_setup_column("reset", imgui.TableColumnFlags_.width_fixed, 50 * s)
                last_cat = None
                for cid in self.reg.order:
                    c = self.reg[cid]
                    if c.category == "Assets" or c.id.startswith("view.mode"):
                        continue
                    if f and f not in f"{c.category} {c.name} {self.reg.all_shortcuts(cid)}".lower():
                        continue
                    if c.category != last_cat:
                        imgui.table_next_row()
                        imgui.table_next_column()
                        imgui.text_colored(V4(*ACCENT, 1), c.category)
                        last_cat = c.category
                    imgui.table_next_row()
                    imgui.table_next_column()
                    imgui.align_text_to_frame_padding()
                    if c.category == NA:
                        imgui.text_disabled(c.name)
                        _tip(c.state()[1])
                    else:
                        imgui.text(c.name)
                    imgui.table_next_column()
                    sc = "press keys..." if self.rebind == cid else (self.reg.all_shortcuts(cid) or "-")
                    if imgui.button(f"{sc}##{cid}", V2(-1, 0)):
                        self.rebind = cid
                    imgui.table_next_column()
                    if cid in self.reg.overrides:
                        if imgui.small_button(f"Reset##{cid}"):
                            del self.reg.overrides[cid]
                            self._save_settings()
                imgui.end_table()
            if self.reg.overrides and imgui.button("Reset all shortcuts to default"):
                self.reg.overrides.clear()
                self._save_settings()
        imgui.end_child()

    def _capture_rebind(self, io):
        if imgui.is_key_pressed(imgui.Key.escape):
            self.rebind = None
            return
        if imgui.is_key_pressed(imgui.Key.backspace):
            self.reg.overrides[self.rebind] = []
            self.rebind = None
            self._save_settings()
            return
        for name, k in capturable_keys():
            if name == "Backspace":
                continue
            if imgui.is_key_pressed(k, False):
                chord = Chord(name, io.key_ctrl, io.key_shift, io.key_alt)
                for other in self.reg.conflicts(chord, self.rebind):
                    left = [str(c) for c in self.reg.bindings(other) if c != chord]
                    self.reg.overrides[other] = left
                    self.msg(f"{chord} was used by '{self.reg[other].name}'; removed it there.")
                self.reg.overrides[self.rebind] = [str(chord)]
                self.msg(f"'{self.reg[self.rebind].name}' is now {chord}")
                self.rebind = None
                self._save_settings()
                return

    def settings_panel(self):
        self._flt = ""
        self.project_ui.settings()
        self.memory_ui.draw()
        if self._section("Interface", ["UI scale"]):
            if self._row("UI scale", "Size of all text and controls. Defaults to your Windows display scaling."):
                pct = getattr(self, "_scale_edit", int(round(self.ui_scale * 100)))
                ch, pct = imgui.slider_int("##scale", pct, 75, 200, "%d%%")
                self._scale_edit = pct
                if imgui.is_item_deactivated_after_edit():
                    self._set_ui_scale(pct / 100.0)
                    del self._scale_edit
            self._end_section()
        if self._section("Layout", ["Panels"]):
            if self._row("Panels", "Drag panel tabs to rearrange; this puts them back."):
                if imgui.button("Reset layout", V2(-1, 0)):
                    self._reset_layout()
            self._end_section()
        if self._section("Substance Painter assets", ["Folders"]):
            if self._row("Folders", "Where Assets > Substance looks for .spsm / .spmsk files.\n"
                                    "Painter's own folders are found automatically."):
                if imgui.button("Add folder...", V2(-1, 0)):
                    self._add_sp_folder()
            extra = self.settings.get("substance_folders", [])
            for f in self.sp_folders:
                imgui.text_disabled(("  " if f not in extra else "+ ") + _ellipsize(f, imgui.get_content_region_avail().x - 40 * self.ui_scale))
                _tip(f)
            for i, f in enumerate(list(extra)):
                imgui.push_id(f"xf{i}")
                if imgui.small_button("Remove"):
                    extra.remove(f)
                    self._save_settings()
                    self._scan_substance()
                imgui.same_line()
                imgui.text(_ellipsize(f, imgui.get_content_region_avail().x))
                imgui.pop_id()
            imgui.text_disabled(f"{len(self.sp_items)} smart materials and masks found")
            self._end_section()
        imgui.text_disabled(f"Settings are stored in {CONFIG_DIR}")

    # ------------------------------------------------------------------ viewport overlay, status
    def _xform(self):
        b = self.engine.brush
        return b.proj_xform if (b.tool == TOOL_PROJECTION and not self.poly_fill) else b.stencil_xform

    def _image_overlay(self, path, kind, xform, alpha, rect=None):
        """Draw a stencil / projection image where the brush will sample it."""
        e = self.engine
        vx, vy, vw, vh = self.vp_rect if rect is None else rect
        if vw < 2 or not path:
            return
        try:
            tex = e.resources.texture(path, kind)
        except Exception:
            return
        if tex is None:
            return
        sx, sy = self.fb_scale
        Mi = np.linalg.inv(stencil_matrix(xform, tex.size, (vw * sx, vh * sy)))
        pts = []
        for u, v in ((0, 0), (1, 0), (1, 1), (0, 1)):
            px, py, _ = Mi @ np.array([u, v, 1.0])
            pts.append(V2(vx + px / sx, vy + vh - py / sy))
        dl = imgui.get_background_draw_list()
        dl.push_clip_rect(V2(vx, vy), V2(vx + vw, vy + vh))
        dl.add_image_quad(imgui.ImTextureRef(tex.glo), pts[0], pts[1], pts[2], pts[3],
                          V2(0, 0), V2(1, 0), V2(1, 1), V2(0, 1), col32(1, 1, 1, alpha))
        dl.add_polyline(pts, col32(*ACCENT, 0.8), 1.5, int(imgui.ImDrawFlags_.closed))
        dl.pop_clip_rect()

    def viewport_overlay(self, vp):
        # Foreground guides must not draw over modal dialogs or quick-property popups.
        if imgui.is_popup_open("", imgui.PopupFlags_.any_popup_id | imgui.PopupFlags_.any_popup_level):
            return
        s = self.ui_scale
        x, y, w, h = vp
        eng, r, b = self.engine, self.engine.renderer, self.engine.brush
        if b.tool == TOOL_PROJECTION and not self.poly_fill and b.proj_maps:
            self._image_overlay(next(iter(b.proj_maps.values())), "color", b.proj_xform, 0.55)
            self._image_overlay(next(iter(b.proj_maps.values())), "color", b.proj_xform, 0.55, self.uv_rect)
        if b.stencil and b.stencil_enabled:
            self._image_overlay(b.stencil, "gray", b.stencil_xform, 0.35)
            self._image_overlay(b.stencil, "gray", b.stencil_xform, 0.35, self.uv_rect)
        self._draw_gizmo()
        if w < 200 * s or h < 80 * s:
            return
        imgui.set_next_window_pos(V2(x + 8 * s, y + 8 * s))
        imgui.set_next_window_bg_alpha(0.72)
        W = imgui.WindowFlags_
        flags = (W.no_decoration | W.always_auto_resize | W.no_saved_settings | W.no_focus_on_appearing
                 | W.no_nav | W.no_docking | W.no_move)
        imgui.push_style_var(imgui.StyleVar_.window_rounding, 4 * s)
        imgui.begin("##vp_overlay", None, flags)
        imgui.pop_style_var()
        mode = 1 if self.workspace_mode == "bake" else 0
        chosen = self._seg("workspace_mode", ["Painting", "Baking"], mode, ["Painting (F9)", "Baking (F8)"])
        if chosen != mode:
            self._set_workspace_mode("bake" if chosen else "paint")
        imgui.set_next_item_width(150 * s)
        ch, v = imgui.combo("##disp", r.mode, DISPLAY_MODES)
        if ch:
            r.mode, eng.dirty = v, True
        _tip("Display channel.  M material,  C / Shift+C channels,  B / Shift+B mesh maps")
        imgui.same_line()
        mode = [VIEW_3D, VIEW_SPLIT, VIEW_2D].index(self.view_mode)
        v = self._seg("vp_lay", [ICON.cube, ICON.split, ICON.image], mode,
                      ["3D view  (F2)", "3D + 2D views  (F1,  F4 swaps)", "2D view  (F3)"])
        self.view_mode = [VIEW_3D, VIEW_SPLIT, VIEW_2D][v]
        imgui.same_line()
        cam = self._seg("vp_cam", ["Persp", "Ortho"], int(eng.camera.ortho),
                        ["Perspective camera  (F5)", "Orthographic camera  (F6)"])
        eng.camera.ortho = bool(cam)
        imgui.same_line()
        self._cmd_btn(ICON.frame, "view.frame")
        if self.ui_hidden:
            imgui.same_line()
            self._cmd_btn(ICON.hide, "view.hide_ui", label="Show panels")
        chips = []
        if self.material_ui.transform_tool and eng.layer is not None:
            chips.append(f"{self.material_ui.transform_tool.title()} fill projection: left-drag, Esc cancels")
        if self.quick_edit:
            chips.append("Editing quick mask (U applies)")
        elif eng.quick_mask_enabled and eng.ts is not None and eng.ts.quick is not None:
            chips.append("Quick mask on")
        if self.paused:
            chips.append("Engine paused (Shift+Esc)")
        if self.isolate:
            chips.append(f"Isolated: {eng.ts.name} (Alt+Q)")
        if b.symmetry:
            chips.append(f"Symmetry {'XYZ'[int(b.sym_axis) % 3]} (L)")
        if b.lazy > 0:
            chips.append(f"Lazy {b.lazy:.0f} px (D)")
        if self._resume:
            chips.append("Next stroke resumes the last one (A)")
        imgui.text_disabled(_ellipsize(self._editing_context(), 440 * s))
        _tip(self._editing_context() + "\nWrites: " + self._writing_channels())
        if chips:
            imgui.text_colored(V4(*ACCENT, 1), "   ".join(chips))
        why = self._paint_block_reason(uv=self.view_mode == VIEW_2D or self._over(self.uv_rect), polygon=self.poly_fill)
        if why:
            imgui.push_text_wrap_pos(imgui.get_cursor_pos_x() + 360 * s)
            imgui.text_colored(V4(*WARN_COL, 1), why)
            imgui.pop_text_wrap_pos()
        if any(ts.tiles is not None for ts in self.engine.sets):
            imgui.text_disabled("3D tile preview: up to 512 px; authored/export resolution is unchanged.")
        imgui.end()
        ux, uy, uw, uh = self.uv_rect
        if uw > 1:
            fg = imgui.get_foreground_draw_list()
            fg.push_clip_rect(V2(ux, uy), V2(ux + uw, uy + uh))
            tiled = eng.ts is not None and eng.ts.tiles is not None
            label = f"2D  |  {DISPLAY_MODES[r.mode]}" + ("  |  tile preview up to 512 px" if tiled else "")
            fg.add_text(V2(ux + 10 * s, uy + uh - 42 * s), col32(*TEXT_DIM), label)
            fg.add_text(V2(ux + 10 * s, uy + uh - 23 * s), col32(*TEXT_DIM),
                        "Left: paint   Alt+Left: rotate   Alt+Middle: pan   Alt+Right: zoom")
            if tiled:
                _, mapping = self._uv_input()
                sx, sy = self.fb_scale
                for address in eng.ts.tile_addresses:
                    pixel = mapping.pixel(address.to_list())
                    fg.add_text(V2(ux + pixel[0] / sx + 5 * s, uy + uh - pixel[1] / sy - 22 * s),
                                col32(*TEXT_DIM), str(address.udim))
            if self._over(self.uv_rect) or self.view_mode == VIEW_2D:
                reason = ("Polygon fill: use 3D." if self.poly_fill else (
                    "Symmetry: use 3D or turn it off." if b.symmetry else (
                    eng.uv_tool_reason())))
                if reason:
                    fg.add_text(V2(ux + 10 * s, uy + uh - 63 * s), col32(*WARN_COL), reason)
            fg.pop_clip_rect()
        hint = {"size": f"Size {self.bsize.text()}   Hardness {b.hardness:.2f}",
                "flow": f"Flow {b.flow:.2f}   Angle {b.angle:.0f}",
                "st_rot": f"Rotate {self._xform()[3]:.0f} deg" + ("  (snapped)" if imgui.get_io().key_shift else ""),
                "st_move": "Move", "st_zoom": f"Scale {self._xform()[2]:.2f}",
                "snaporbit": f"{self._axis_view_name()} view  (Alt+Shift drag steps between axis views)",
                "split": "Drag to resize the 3D and 2D views  (double-click: half and half)"}.get(self.drag)
        if hint:
            mx, my = imgui.get_io().mouse_pos
            fg = imgui.get_foreground_draw_list()
            sz = imgui.calc_text_size(hint)
            fg.add_rect_filled(V2(mx + 14, my - sz.y - 12), V2(mx + 22 + sz.x, my - 4), col32(0, 0, 0, 0.7), 3)
            fg.add_text(V2(mx + 18, my - sz.y - 8), col32(1, 1, 1), hint)

    def _paint_block_reason(self, uv=False, polygon=False):
        eng, b = self.engine, self.engine.brush
        if not uv and eng.shader_workflow["displacement_meters"]:
            return "Displaced surface preview: edit in 2D, or set displacement range to zero for 3D painting."
        if b.target == 0 and b.user_channel and b.tool != TOOL_PAINT:
            return "User channels support Paint and Erase. Select the Paint tool."
        if not polygon and eng.ts is not None and eng.ts.tiles is not None and (b.tool in (TOOL_CLONE, TOOL_SMUDGE) or b.target == 2 or eng.quick_mask_enabled):
            return "Tiled clone, smudge and quick-mask strokes are not integrated yet."
        if eng.ts is not None and eng.ts.tiles is not None and polygon and (b.target == 2 or eng.quick_mask_enabled):
            return "Tiled quick-mask polygon fill is not integrated yet."
        lay = eng.layer
        if b.target == 2:
            return ""
        if lay is None:
            return "No layer selected: add a paint layer to start painting."
        if lay.is_group and b.target == 0:
            return "A folder is selected: select a paint layer inside it, or paint the folder's mask."
        if not lay.visible:
            return "The selected layer is hidden: show it (eye icon) to paint."
        parent = eng.find(lay)[2]
        while parent is not None:
            if not parent.visible:
                return "The selected layer's folder is hidden: show the folder to paint."
            parent = eng.find(parent)[2]
        if self.workspace_mode == "bake" and lay.pid not in (
                eng.ts.bake_settings.ray_correction_pid, eng.ts.bake_settings.distance_correction_pid):
            return "Baking mode: select a correction field in Properties, or press F9 to paint materials."
        if not eng.ts.visible:
            return "The active texture set is hidden: show it in Texture Set List to paint."
        if b.target == 1 and not lay.mask_enabled:
            return "The selected mask is disabled: Shift+click its thumbnail to enable it."
        if b.target == 0 and not b.user_channel and not any(b.enabled):
            return "No paint channels enabled: enable material channels in Properties."
        if b.target == 0 and lay.kind != "paint":
            return "Fill layer selected: paint its mask (mask thumbnail) or add a paint layer."
        if not self.poly_fill and b.tool == TOOL_CLONE and eng.clone_source is None and not (self._over(self.uv_rect) or self.view_mode == VIEW_2D):
            return "Clone: hold V and click on the model to set the source first."
        if not self.poly_fill and b.tool == TOOL_PROJECTION and not b.proj_maps:
            return "Projection: load an image in Properties > Projection first."
        return ""

    def status_bar(self, ww, wh, h):
        self._fixed_window("##status", 0, wh - h, ww, h, pad=(8, 3))
        imgui.align_text_to_frame_padding()
        tip = ("LMB paint  |  Alt+LMB orbit  |  Alt+MMB pan  |  Alt+RMB zoom  |  RMB brush menu  |  "
               "Ctrl+RMB size  |  Ctrl+K find any command")
        recent = time.time() - self.status_t < 6
        right = ""
        eng = self.engine
        if eng.comp is not None:
            right = f"{self._tool_label()[1]}: {self._editing_context()}     {eng.res} px     {self.fps:4.0f} fps"
            right = _ellipsize(right, max(ww * .58, 1))
        rw = imgui.calc_text_size(right).x
        text = self.status if recent and self.status else tip
        if recent and self.status:
            imgui.text(_ellipsize(text, ww - rw - 40))
        else:
            imgui.text_disabled(_ellipsize(text, ww - rw - 40))
        imgui.same_line(ww - rw - 14)
        imgui.text_disabled(right)
        imgui.end()

    def busy_overlay(self, ww, wh):
        imgui.set_next_window_pos(V2(ww / 2, wh / 2), 0, V2(0.5, 0.5))
        imgui.begin("##busy", None, imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.always_auto_resize)
        imgui.text(self.pending[0])
        if self.busy_detail:
            imgui.text_disabled(self.busy_detail)
        imgui.end()

    def quick_brush(self):
        """Right-click in the viewport: the brush settings at the cursor (Painter-style quick menu)."""
        s = self.ui_scale
        if self.quick_open:
            imgui.open_popup("##quick_brush")
            self.quick_open = False
        self.quick_is_open = imgui.begin_popup("##quick_brush")
        if not self.quick_is_open:
            return
        _esc_closes()
        b = self.engine.brush
        imgui.text_colored(V4(*ACCENT, 1), "Brush")
        b.mode = self._seg("q_tool", [f"{ICON.paint} Paint", f"{ICON.erase} Erase"], b.mode, ["1", "2"])
        imgui.same_line()
        b.target = self._seg("q_tgt", ["Layer", "Mask"], b.target, ["", "M"])
        log = imgui.SliderFlags_.logarithmic
        _, _, slo, shi, sfmt = self.bsize.spec
        for label, attr, lo, hi, fmt, fl in (("Size", "@size", slo, shi, sfmt, log), ("Hardness", "hardness", 0, 1, "%.2f", 0),
                                             ("Flow", "flow", 0, 1, "%.2f", 0), ("Spacing", "spacing", 0.02, 1, "%.2f", 0)):
            obj, at = (self.bsize, "value") if attr == "@size" else (b, attr)
            imgui.set_next_item_width(200 * s)
            ch, v = imgui.slider_float(label, float(getattr(obj, at)), lo, hi, fmt, fl)
            if ch:
                setattr(obj, at, v)
        if b.target == 0:
            imgui.set_next_item_width(200 * s)
            ch, c = imgui.color_edit3("Color", list(b.color), imgui.ColorEditFlags_.no_inputs)
            if ch:
                b.color = list(c)
        else:
            v = self._seg("q_mv", ["White", "Black"], 0 if b.mask_value > 0.5 else 1, ["X", "X"])
            b.mask_value = 1.0 if v == 0 else 0.0
        imgui.text_disabled("More in Properties.")
        imgui.end_popup()

    # ------------------------------------------------------------------ viewport input
    def _mouse_vp(self):
        """Mouse position in 3D-view framebuffer pixels, origin bottom-left."""
        return tuple(ViewInput(self.vp_rect, self.fb_scale).pixel(imgui.get_io().mouse_pos))

    def _uv_input(self):
        view = ViewInput(self.uv_rect, self.fb_scale)
        return view, self.uv.mapping(*view.size)

    def _mouse_uv(self):
        view, mapping = self._uv_input()
        return mapping.uv(view.pixel(imgui.get_io().mouse_pos))

    def _uv_target_key(self):
        e = self.engine
        effect = e.active_mask_paint()
        return (id(e.mesh), e.ts.pid, e.layer.pid if e.layer else None,
                e.brush.target, effect.pid if effect else None, e.brush.user_channel)

    def _uv_straight_line(self, snap=False):
        e = self.engine
        if self._last_uv_hit is None or self._last_uv_hit[0] != self._uv_target_key():
            self.msg("Paint a UV stroke on this target before drawing a straight line.")
            return
        reason = self._paint_block_reason(uv=True) or e.uv_tool_reason()
        if reason or self.poly_fill:
            self.msg(reason or "Choose Paint for a UV straight line.")
            return
        _, mapping = self._uv_input()
        start, end = np.asarray(self._last_uv_hit[1]), self._mouse_uv()
        if snap:
            a, b = mapping.pixel(start), mapping.pixel(end)
            delta = b - a
            angle = round(math.atan2(delta[1], delta[0]) / (math.pi / 12)) * math.pi / 12
            end = mapping.uv(a + np.linalg.norm(delta) * np.array((math.cos(angle), math.sin(angle))))
        if e.pick_uv(end) is None:
            return
        try:
            if e.begin_uv_stroke(start, mapping, pressure=self.tablet.pressure):
                e.stroke_uv_to(end, pressure=self.tablet.pressure, mapping=mapping)
                e.end_stroke()
                self._last_uv_hit = (self._uv_target_key(), tuple(end))
        except (ValueError, OSError) as error:
            e.cancel_stroke()
            self.msg("UV line failed: " + str(error))

    def _begin_uv_paint(self):
        e = self.engine
        why = self._paint_block_reason(uv=True) or e.uv_tool_reason()
        if self.poly_fill:
            why = "Polygon fill uses the 3D view; choose Paint for UV strokes."
        if why or not e.can_paint():
            self.msg(why or "This layer can't be painted.")
            return
        if e.brush.tool == TOOL_CLONE and self.clone_absolute:
            e.clone_uv_offset = None
        _, mapping = self._uv_input()
        try:
            uv = self._mouse_uv()
            previous = self._last_uv_hit
            resume = self._resume and previous is not None and previous[0] == self._uv_target_key()
            start = previous[1] if resume else uv
            if e.begin_uv_stroke(start, mapping, pressure=self.tablet.pressure):
                if resume:
                    e.stroke_uv_to(uv, pressure=self.tablet.pressure, mapping=mapping)
                self._resume = False
                self.drag = "uvpaint"
                self._last_uv_hit = (self._uv_target_key(), tuple(uv))
        except (ValueError, OSError) as error:
            e.cancel_stroke()
            self.drag = None
            self.msg("UV stroke failed: " + str(error))

    def _paint_uv_at_cursor(self):
        # Capture stays in the originating view; leaving it makes a gap.
        uv = self._mouse_uv() if self._over(self.uv_rect) else (-1., -1.)
        _, mapping = self._uv_input()
        try:
            self.engine.stroke_uv_to(uv, pressure=self.tablet.pressure, mapping=mapping)
            if self.engine.pick_uv(uv) is not None:
                self._last_uv_hit = (self._uv_target_key(), tuple(uv))
        except (ValueError, OSError) as error:
            self.engine.cancel_stroke()
            self.drag = None
            self.msg("UV stroke failed: " + str(error))

    def _draw_uv_cursor(self):
        if not self._over(self.uv_rect) or self.material_ui.transform_tool or self.poly_fill:
            return
        e = self.engine
        info = e.pick_uv(self._mouse_uv())
        if info is None:
            return
        _, mapping = self._uv_input()
        radius = e.uv_brush_radius(info["tri"], mapping) / mapping.units_per_pixel
        mx, my = imgui.get_io().mouse_pos
        sx, sy = self.fb_scale
        points = [V2(mx + math.cos(t) * radius / sx, my + math.sin(t) * radius / sy)
                  for t in np.linspace(0, 2 * math.pi, 65)]
        x, y, w, h = self.uv_rect
        draw = imgui.get_background_draw_list()
        draw.push_clip_rect(V2(x, y), V2(x + w, y + h))
        draw.add_polyline(points, col32(1, 1, 1, .9), 1., int(imgui.ImDrawFlags_.closed))
        draw.pop_clip_rect()

    # ------------------------------------------------------------------ axis gizmo
    _AXES = (("x", 0, (0.86, 0.36, 0.36)), ("y", 1, (0.52, 0.78, 0.38)), ("z", 2, (0.38, 0.58, 0.90)))
    _VIEW_NAMES = {"+z": "Front", "-z": "Back", "+x": "Right", "-x": "Left", "+y": "Top", "-y": "Bottom"}

    def _draw_gizmo(self):
        """World-axis gizmo in the 3D view's bottom-right corner. Clicking an axis end views along it."""
        self._gizmo = None
        vx, vy, vw, vh = self.vp_rect
        s = self.ui_scale
        rad = 34 * s
        if vw < 4 * rad or vh < 4 * rad:
            return
        cx, cy = vx + vw - rad - 16 * s, vy + vh - rad - 16 * s
        rot = self.engine.camera.view()[:3, :3]
        dl = imgui.get_background_draw_list()
        mx, my = imgui.get_io().mouse_pos
        hover = self._gizmo_axis_at(mx, my) if self._over(self.vp_rect) else None
        if hover is not None or self.drag == "snaporbit":
            dl.add_circle_filled(V2(cx, cy), rad + 10 * s, col32(1, 1, 1, 0.06), 32)
        ends = []
        for name, i, col in self._AXES:
            d = rot[:, i]                       # world axis in camera space: x right, y up, z towards viewer
            for sign in (1, -1):
                ends.append((sign * d[2], f"{'+' if sign > 0 else '-'}{name}", sign, col,
                             cx + sign * d[0] * rad, cy - sign * d[1] * rad))
        ends.sort(key=lambda t: t[0])          # far ends first
        r_pos, r_neg = 8.5 * s, 6 * s
        hit = []
        for depth, axis, sign, col, ex, ey in ends:
            hov = self._gizmo_hover_axis == axis
            if sign > 0:
                dl.add_line(V2(cx, cy), V2(ex, ey), col32(*col, 0.9), 2 * s)
                dl.add_circle_filled(V2(ex, ey), r_pos, col32(*col, 1.0), 20)
                if hov:
                    dl.add_circle(V2(ex, ey), r_pos + 1.5 * s, col32(1, 1, 1, 0.95), 20, 1.5 * s)
                lab = axis[1].upper()
                ts = imgui.calc_text_size(lab)
                dl.add_text(V2(ex - ts.x / 2, ey - ts.y / 2), col32(0.08, 0.08, 0.09), lab)
                hit.append((axis, ex, ey, r_pos + 2 * s))
            else:
                dl.add_circle_filled(V2(ex, ey), r_neg, col32(*col, 0.35 if not hov else 0.7), 20)
                dl.add_circle(V2(ex, ey), r_neg, col32(*col, 0.8), 20, 1.0 * s)
                hit.append((axis, ex, ey, r_neg + 2 * s))
        self._gizmo = hit
        self._gizmo_hover_axis = None
        if hover is not None:
            self._gizmo_hover_axis = hover
            imgui.set_tooltip(f"{self._VIEW_NAMES[hover]} view ({hover.upper()})\n"
                              "Alt+Shift+Left drag snaps between axis views")

    _gizmo_hover_axis = None

    def _gizmo_axis_at(self, mx, my):
        """Axis end of the gizmo under the mouse ('+x', '-y', ...) or None."""
        best = None
        for axis, ex, ey, r in reversed(self._gizmo or []):      # nearest ends were drawn last
            if (mx - ex) ** 2 + (my - ey) ** 2 <= r * r:
                best = axis
                break
        return best

    def _axis_view_name(self):
        """'Front', 'Top', ... when the camera looks straight along an axis, else 'Free'."""
        cam = self.engine.camera
        q = math.pi / 2
        if abs(abs(cam.pitch) - q) < 1e-3:
            return "Top" if cam.pitch > 0 else "Bottom"
        if abs(cam.pitch) > 1e-3 or abs(cam.yaw / q - round(cam.yaw / q)) > 1e-3:
            return "Free"
        return {0: "Front", 1: "Right", 2: "Back", 3: "Left"}[int(round(cam.yaw / q)) % 4]

    def _set_size_space(self, space):
        """Switch the brush size space, keeping the circle the same size on screen right now."""
        px = self.bsize.value / self._size_units_per_px()
        self.engine.brush.size_space = int(space)
        self.bsize.value = px * self._size_units_per_px()
        self.settings["brush_space"] = int(space)
        self._save_settings()

    def _size_units_per_px(self):
        """How much the size value changes per screen pixel of brush diameter, under the cursor
        (or at the middle of the mesh)."""
        e, b = self.engine, self.engine.brush
        sp = int(b.size_space)
        if sp == 0 or e.mesh is None:
            return 1.0
        hit = self.cursor[0] if self.cursor is not None else e.camera.target
        wpp = e.camera.world_per_pixel(hit, max(e.view_size[1], 1))
        if sp == 1:                                  # diameter = 2 * size_obj * mesh radius
            return 100 * wpp / (2 * e.mesh.radius)
        tri = (e._last_pick or {}).get("tri", -1)    # UV: diameter = size_uv * world-per-UV
        topo = e.mesh.topology
        per_uv = topo.uv_scale(tri) if 0 <= tri < topo.n_tris else e.mesh.radius
        return 100 * wpp / max(per_uv, 1e-9)

    def _over(self, rect):
        io = imgui.get_io()
        mx, my = io.mouse_pos
        x, y, w, h = rect
        return w > 1 and h > 1 and x <= mx < x + w and y <= my < y + h and not io.want_capture_mouse

    def _over_viewport(self):
        return self._over(self.vp_rect)

    def _pick_cursor(self):
        if not (self._over_viewport() or self.drag == "paint"):
            return None
        hit = self.engine.pick(*self._mouse_vp())
        if hit is not None and self.engine._set_of_tri(self.engine._last_pick["tri"]) != self.engine.active:
            return None
        return hit

    def _cursor_visible(self):
        return (self.cursor is not None and not imgui.get_io().key_alt and self._gizmo_hover_axis is None
                and not self.material_ui.transform_tool)

    def _paint_at_cursor(self):
        hit = self.engine.pick(*self._mouse_vp())
        if hit is not None:
            try:
                self.engine.stroke_to(hit[0], pressure=self.tablet.pressure)
            except (ValueError, OSError) as error:
                self.engine.cancel_stroke()
                self.drag = None
                self.msg("3D stroke failed: " + str(error))
                return
            self._last_hit = hit[0]

    def _begin_paint(self):
        eng, b = self.engine, self.engine.brush
        why = self._paint_block_reason()
        if why or not eng.can_paint():
            self.msg(why or "This layer can't be painted.")
            return
        hit = eng.pick(*self._mouse_vp())
        if hit is None:
            return
        if eng._set_of_tri(eng._last_pick["tri"]) != eng.active:
            self.msg("This surface belongs to another texture set. Ctrl+Alt+Right click selects it.")
            return
        if b.tool == TOOL_CLONE and self.clone_absolute:
            eng.clone_offset = None            # absolute source: every stroke starts at the source
        if self._resume and self._last_hit is not None:
            self._resume = False
            if self._line_from_last(end=False):
                self.drag = "paint"
                return
        try:
            started = eng.begin_stroke(hit[0], pressure=self.tablet.pressure)
        except (ValueError, OSError) as error:
            self.msg("3D stroke failed: " + str(error))
            return
        if started:
            self.drag = "paint"
            self._last_hit = hit[0]

    def _line_from_last(self, snap=False, end=True):
        """Painter's Shift+click: a straight stroke from the end of the last one to the cursor."""
        eng, b = self.engine, self.engine.brush
        p0 = eng._view().project(self._last_hit)
        if p0 is None:
            return False
        x1, y1 = self._mouse_vp()
        dx, dy = x1 - p0[0], y1 - p0[1]
        if snap:
            length, step = math.hypot(dx, dy), math.pi / 12
            ang = round(math.atan2(dy, dx) / step) * step
            dx, dy = length * math.cos(ang), length * math.sin(ang)
        if b.tool == TOOL_CLONE and self.clone_absolute:
            eng.clone_offset = None
        if not eng.begin_stroke(self._last_hit, pressure=self.tablet.pressure):
            return False
        n = max(2, int(math.hypot(dx, dy) / 2))
        for k in range(1, n + 1):
            t = k / n
            hit = eng.pick(p0[0] + dx * t, p0[1] + dy * t)
            if hit is not None:
                eng.stroke_to(hit[0], pressure=self.tablet.pressure)
                self._last_hit = hit[0]
        if end:
            eng.end_stroke()
        return True

    def _straight_line(self, snap):
        why = self._paint_block_reason()
        if why or not self.engine.can_paint():
            self.msg(why or "This layer can't be painted.")
            return
        if self._last_hit is None:
            self.msg("Shift+click draws a straight line from the end of the last stroke: paint a stroke first.")
            return
        self._line_from_last(snap=snap)

    def _poly_fill_click(self):
        eng, b = self.engine, self.engine.brush
        why = self._paint_block_reason(polygon=True)
        if why:
            self.msg(why)
            return
        tris = eng.select_triangles(*self._mouse_vp(), self.fill_mode)
        if len(tris) == 0:
            return
        try:
            filled = eng.polygon_fill(tris, erase=b.mode == 1)
        except (ValueError, OSError) as error:
            self.msg("Polygon fill failed: " + str(error))
            return
        if filled:
            self.msg(f"{'Erased' if b.mode else 'Filled'} {FILL_MODES[self.fill_mode].lower()}  ({len(tris)} triangles)")

    def _pick_texture_set(self):
        eng = self.engine
        info = eng.pick_info(*self._mouse_vp())
        if info is None or info.get("set", -1) < 0:
            self.msg("No texture set under the cursor.")
            return
        eng.set_active(info["set"])
        self.sel_uids, self._last_primary = set(), None
        self.msg(f"Texture set: {eng.ts.name}")

    def _finish_fill_projection(self, cancel=False):
        gesture = getattr(self, "_fill_projection_drag", None)
        if gesture is not None:
            if self.engine._edit_transaction is gesture["transaction"]:
                (self.engine.cancel_edit if cancel else self.engine.commit_edit)()
            self._fill_projection_drag = None
            if self.drag == "fill_projection":
                self.drag = None

    def _fill_projection_input(self, over3, over2):
        """Edit the same projection properties as numeric controls in one gesture."""
        io = imgui.get_io()
        ui, eng = self.material_ui, self.engine
        gesture = self._fill_projection_drag
        lay = eng.layer
        valid = (lay is not None and lay.kind == "fill" and eng.brush.target == 0
                 and (bool(lay.maps) or lay.authored is not None) and lay.pid == ui.transform_layer_pid and ui.transform_tool is not None)
        if gesture is not None:
            if not valid or self.engine._edit_transaction is not gesture["transaction"]:
                self._finish_fill_projection(cancel=True)
                return True
            if imgui.is_key_pressed(imgui.Key.escape):
                self._finish_fill_projection(cancel=True)
                return True
            mx, my = io.mouse_pos
            dx, dy = mx - gesture["mouse"][0], my - gesture["mouse"][1]
            original = gesture["original"]
            if gesture["tool"] == "translate":
                w, h = gesture["size"]
                values = {"offset": [original["offset"][0] - dx / w,
                                     original["offset"][1] + dy / h]}
            elif gesture["tool"] == "warp":
                corners=[list(point) for point in original["warp"]]
                index=gesture["corner"];w,h=gesture["size"]
                corners[index]=[corners[index][0]+dx/w,corners[index][1]-dy/h]
                values={"warp":corners}
            elif gesture["tool"] == "rotate":
                angle = original["rotation"] + dx * .5
                values = {"rotation": round(angle / 15) * 15 if io.key_shift else angle}
            else:
                factor = math.exp(float(np.clip(dx * .006, -8, 8)))
                values = {"scale": [float(np.sign(value) * np.clip(abs(value) * factor, .001, 1000))
                                    for value in original["scale"]]}
            try:
                eng.set_projection(lay, **values)
            except Exception as error:
                self._finish_fill_projection(cancel=True)
                self.msg(f"Projection edit failed: {error}")
                return True
            if not imgui.is_mouse_down(0):
                self._finish_fill_projection()
            return True
        if not valid or io.key_alt or io.key_ctrl or self.drag:
            return False
        if imgui.is_key_pressed(imgui.Key.escape):
            ui.transform_tool = None
            return True
        if not (over3 or over2):
            return False
        imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all)
        if imgui.is_mouse_clicked(0):
            self._finish_property_edit()
            rect = self.vp_rect if over3 else self.uv_rect
            transaction = eng.begin_edit(lay.proj, label=ui.transform_tool.title() + " fill projection")
            self._fill_projection_drag = {
                "transaction": transaction, "tool": ui.transform_tool,
                "mouse": tuple(io.mouse_pos), "size": (max(rect[2], 1), max(rect[3], 1)),
                "corner":ui.warp_corner,
                "original": {"warp":lay.proj.warp or [[0.,0.],[1.,0.],[1.,1.],[0.,1.]],"offset": list(lay.proj.offset), "scale": list(lay.proj.scale),
                             "rotation": lay.proj.rotation}}
            self.drag = "fill_projection"
            return True
        return False

    def viewport_input(self):
        io = imgui.get_io()
        eng, b = self.engine, self.engine.brush
        if io.want_text_input or imgui.is_popup_open("", imgui.PopupFlags_.any_popup_id):
            if self.drag in ("paint", "uvpaint"):
                eng.end_stroke()
            self.drag = None
            return
        if getattr(eng, "_tile_stroke", None) is not None and imgui.is_key_pressed(imgui.Key.escape):
            eng.cancel_stroke()
            self.drag = None
            return
        over3, over2 = self._over(self.vp_rect), self._over(self.uv_rect)
        if self.authored_ui.input(over3,over2):return
        if self._fill_projection_input(over3, over2):
            return
        if self.effects_ui.pick():
            return
        alt, ctrl, shift = io.key_alt, io.key_ctrl, io.key_shift
        typing = io.want_text_input
        s_held = imgui.is_key_down(imgui.Key.s) and not typing
        v_held = imgui.is_key_down(imgui.Key.v) and not typing
        mx, my = io.mouse_pos
        has_image = bool(b.stencil) or (b.tool == TOOL_PROJECTION and bool(b.proj_maps))
        if not self.drag and imgui.is_mouse_clicked(0) and self._over_split():
            if imgui.is_mouse_double_clicked(0):
                self.split_frac = 0.5
                self._save_settings()
            else:
                self.drag = "split"
        if not self.drag and over3 and imgui.is_mouse_clicked(0) and not alt:
            axis = self._gizmo_axis_at(mx, my)
            if axis is not None:
                eng.camera.snap_to_axis(axis)
                self.msg(f"{self._axis_view_name()} view")
                return
        if not self.drag:
            if over3:
                if s_held and not has_image and any(imgui.is_mouse_clicked(k) for k in (0, 1, 2)):
                    self.msg("S + mouse moves the stencil or projection image: load one in Properties first.")
                elif imgui.is_mouse_clicked(0):
                    if alt and shift:
                        self.drag, self.drag_start = "snaporbit", (mx, my, eng.camera.yaw, eng.camera.pitch)
                    elif alt and ctrl:
                        self.drag = "pan_l"
                    elif alt:
                        self.drag = "orbit"
                    elif s_held:
                        self.drag, self.drag_start = "st_rot", (mx, my, list(self._xform()))
                    elif v_held:
                        eng.set_clone_source(*self._mouse_vp())
                        self.msg("Clone source set. Paint with the Clone tool (6).")
                    elif shift:
                        self._straight_line(snap=ctrl)
                    elif ctrl:
                        self.drag, self.drag_start = "flow", (mx, my, b.flow, b.angle)
                    elif self.poly_fill:
                        self._poly_fill_click()
                    else:
                        self._begin_paint()
                elif imgui.is_mouse_clicked(1):
                    if ctrl and alt:
                        self._pick_texture_set()
                    elif s_held:
                        self.drag, self.drag_start = "st_zoom", (mx, my, list(self._xform()))
                    elif alt:
                        self.drag = "zoom"
                    elif ctrl:
                        self.drag, self.drag_start = "size", (mx, my, self.bsize.value, b.hardness,
                                                              self._size_units_per_px())
                    elif shift:
                        self.drag = "light"
                    else:
                        self.drag, self.drag_start = "rmb", (mx, my, 0, 0)
                elif imgui.is_mouse_clicked(2):
                    if s_held:
                        self.drag, self.drag_start = "st_move", (mx, my, list(self._xform()))
                    else:
                        self.drag = "pan"
                if io.mouse_wheel:
                    if ctrl:
                        self.bsize.scale(1.1 ** io.mouse_wheel)
                    else:
                        eng.camera.zoom(io.mouse_wheel)
            elif over2:
                if s_held and has_image and any(imgui.is_mouse_clicked(k) for k in (0, 1, 2)):
                    kind = "st_rot" if imgui.is_mouse_clicked(0) else ("st_zoom" if imgui.is_mouse_clicked(1) else "st_move")
                    self._image_view = "uv"
                    self.drag, self.drag_start = kind, (mx, my, list(self._xform()))
                elif imgui.is_mouse_clicked(0) and alt and not ctrl:
                    view, mapping = self._uv_input()
                    pixel = view.pixel((mx, my))
                    self.drag = "uvrotate"
                    self.drag_start = (mx, my, self.uv.rotation, mapping.uv(pixel), pixel, view.size, shift)
                elif imgui.is_mouse_clicked(0) and alt and ctrl:
                    self.drag, self.drag_start = "uvpan", 0
                elif imgui.is_mouse_clicked(0) and not alt:
                    if v_held:
                        self.msg("UV clone source set." if eng.set_uv_clone_source(self._mouse_uv()) else "Choose a UV island for the clone source.")
                    elif shift:
                        self._uv_straight_line(snap=ctrl)
                    elif ctrl:
                        self.drag, self.drag_start = "flow", (mx, my, b.flow, b.angle)
                    else:
                        self._begin_uv_paint()
                elif imgui.is_mouse_clicked(1):
                    if alt:
                        view, mapping = self._uv_input()
                        pixel = view.pixel((mx, my))
                        self.drag, self.drag_start = "uvzoom", (mx, my, self.uv.zoom, mapping.uv(pixel), pixel, view.size, False)
                    elif ctrl:
                        self.drag, self.drag_start = "size", (mx, my, self.bsize.value, b.hardness, self._size_units_per_px())
                    elif shift:
                        self.drag = "light"
                    else:
                        self.drag, self.drag_start = "uvrmb", (mx, my)
                elif imgui.is_mouse_clicked(2):
                    self.drag, self.drag_start = "uvpan", 2
                if io.mouse_wheel:
                    if ctrl:
                        self.bsize.scale(1.1 ** io.mouse_wheel)
                    else:
                        view, mapping = self._uv_input()
                        pixel = view.pixel((mx, my))
                        self.uv.zoom_by(io.mouse_wheel)
                        self.uv.anchor(mapping.uv(pixel), pixel, view.size)
        if self.drag:
            d = self.drag
            if d in ("paint", "uvpaint", "flow", "snaporbit", "pan_l", "st_rot", "split", "uvrotate"):
                held = imgui.is_mouse_down(0)
            elif d == "orbit":
                held = imgui.is_mouse_down(0) or imgui.is_mouse_down(1)
            elif d in ("zoom", "size", "light", "rmb", "st_zoom", "uvzoom", "uvrmb", "uvpan_r"):
                held = imgui.is_mouse_down(1)
            elif d == "uvpan":
                held = imgui.is_mouse_down(self.drag_start)
            else:
                held = imgui.is_mouse_down(2)
            dx, dy = io.mouse_delta
            vw, vh = max(self.vp_rect[2], 1), max(self.vp_rect[3], 1)
            if d == "orbit":
                eng.camera.orbit(dx, dy)
            elif d == "split":
                _, _, _, x0, w0 = self._split_hit or (0, 0, 0, 0, 1)
                self.split_frac = float(np.clip((mx - x0) / max(w0, 1), 0.15, 0.85))
            elif d == "snaporbit":
                x0, y0, yaw0, p0 = self.drag_start
                q = math.pi / 2
                eng.camera.yaw = round((yaw0 - (mx - x0) * 0.008) / q) * q
                eng.camera.pitch = float(np.clip(round((p0 + (my - y0) * 0.008) / q) * q, -q, q))
            elif d in ("pan", "pan_l"):
                eng.camera.pan(dx, dy, self.vp_rect[3])
            elif d == "zoom":
                eng.camera.zoom(-dy * 0.03)
            elif d == "light":
                eng.renderer.env_rot = float((eng.renderer.env_rot + dx * 0.01 + np.pi) % (2 * np.pi) - np.pi)
            elif d == "size":
                x0, y0, s0, h0, upp = self.drag_start
                self.bsize.value = s0 + (mx - x0) * upp          # the circle grows with the mouse
                b.hardness = float(np.clip(h0 - (my - y0) * 0.004, 0, 1))
            elif d == "flow":
                x0, y0, f0, a0 = self.drag_start
                b.flow = float(np.clip(f0 + (mx - x0) * 0.004, 0, 1))
                b.angle = float((a0 + (my - y0) * 0.5) % 360)
            elif d in ("st_rot", "st_move", "st_zoom"):
                if getattr(self, "_image_view", None) == "uv":
                    vw, vh = self.uv_rect[2:]
                x0, y0, xf0 = self.drag_start
                xf = self._xform()
                if d == "st_rot":
                    rot = xf0[3] + (mx - x0) * 0.5
                    xf[3] = round(rot / 15) * 15 if shift else rot
                elif d == "st_move":
                    xf[0] = xf0[0] + (mx - x0) / vw
                    xf[1] = xf0[1] - (my - y0) / vh
                else:
                    xf[2] = float(np.clip(xf0[2] * math.exp((mx - x0) * 0.006), 0.02, 20))
            elif d == "rmb":
                x0, y0, _, _ = self.drag_start
                if abs(mx - x0) + abs(my - y0) > 4:
                    self.drag = "orbit"          # right drag still orbits
            elif d == "uvpan":
                self.uv.pan(dx, dy, self.uv_rect[2], self.uv_rect[3])
            elif d == "uvpan_r":
                self.uv.pan(dx, dy, self.uv_rect[2], self.uv_rect[3])
            elif d in ("uvrotate", "uvzoom"):
                x0, y0, original, anchor, pixel, size, snap = self.drag_start
                if d == "uvrotate":
                    angle = original + (mx - x0) * .008
                    self.uv.rotation = round(angle / (math.pi / 2)) * (math.pi / 2) if shift or snap else angle
                else:
                    self.uv.zoom = float(np.clip(original * math.exp((my - y0) * .03), self.uv.min_zoom, 32.))
                self.uv.anchor(anchor, pixel, size)
            elif d == "uvrmb":
                x0, y0 = self.drag_start
                if abs(mx - x0) + abs(my - y0) > 4:
                    self.drag = "uvpan_r"
            if not held:
                if d in ("paint", "uvpaint"):
                    if d == "uvpaint":
                        self._paint_uv_at_cursor()
                    eng.end_stroke()
                if d in ("st_rot", "st_move", "st_zoom"):
                    self._image_view = None
                if d in ("rmb", "uvrmb"):
                    self.quick_open = True
                if d == "split":
                    self._save_settings()
                self.drag = None

    def shortcuts(self):
        io = imgui.get_io()
        if self.rebind:
            self._capture_rebind(io)
            return
        if io.want_text_input:
            return
        if imgui.is_popup_open("", imgui.PopupFlags_.any_popup_id):
            return
        self.reg.dispatch(io, self.msg)

    # ------------------------------------------------------------------ dialogs
    def extra_dialogs(self):
        self.authored_ui.draw()
        self.channels_ui.draw()
        self.delivery_ui.draw()
        self.import_ui.draw()
        self.project_ui.dialogs()
        s = self.ui_scale
        e = self.engine
        center = imgui.get_main_viewport().get_center()
        auto = imgui.WindowFlags_.always_auto_resize
        if self.open_bake:
            imgui.open_popup("Bake Mesh Maps")
            self.open_bake = False
        if self.open_close:
            imgui.open_popup("Close Project")
            self.open_close = False
            self._close_unsaved = e.modified
        if self.open_quit:
            imgui.open_popup("Unsaved Changes")
            self.open_quit = False
        imgui.set_next_window_pos(center, imgui.Cond_.appearing, V2(0.5, 0.5))
        if imgui.begin_popup_modal("Bake Mesh Maps", None, auto)[0]:
            bs = self.bake_settings
            imgui.text_disabled(f"Texture set: {e.ts.name}  ({e.ts.res} px).  Bakes AO, curvature, thickness, ID, "
                                "position and normal maps.")
            samples = [32, 64, 96, 192, 256]
            iw = 220 * s
            imgui.set_next_item_width(iw)
            idx = min(range(len(samples)), key=lambda i: abs(samples[i] - bs.ao_samples))
            ch, idx = imgui.combo("AO samples", idx, [f"{n}  ({'draft' if n < 96 else 'default' if n == 96 else 'high'})"
                                                     for n in samples])
            bs.ao_samples = samples[idx]
            imgui.set_next_item_width(iw)
            _, bs.ao_spread = imgui.slider_float("AO spread", float(bs.ao_spread), 10, 90, "%.0f deg")
            imgui.set_next_item_width(iw)
            _, bs.ao_max_distance = imgui.slider_float("AO max distance", float(bs.ao_max_distance), 0, 1,
                                                       "%.2f" if bs.ao_max_distance else "unlimited")
            _, bs.ground_plane = imgui.checkbox("Ground plane (AO)", bool(bs.ground_plane))
            imgui.set_next_item_width(iw)
            _, bs.thickness_max_distance = imgui.slider_float("Thickness distance", float(bs.thickness_max_distance),
                                                              0.05, 1.0, "%.2f")
            _, bs.curv_from_normal = imgui.checkbox("Add normal-map detail to curvature", bool(bs.curv_from_normal))
            imgui.set_next_item_width(iw)
            _, bs.dilation = imgui.slider_int("Dilation (px)", int(bs.dilation), 0, 64)
            self.bake_ui.source_controls(bs)
            if len(e.sets) > 1:
                _, self.bake_all = imgui.checkbox("Bake every texture set", self.bake_all)
            if imgui.button("Bake", V2(120 * s, 0)):
                settings = BakeSettings.from_dict(copy.deepcopy(bs.to_dict()))
                all_sets = bool(self.bake_all and len(e.sets) > 1)
                def job():
                    self.bake_ui.run(settings, all_sets)
                self._run_busy("Baking mesh maps...", job)
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", V2(120 * s, 0)) or imgui.is_key_pressed(imgui.Key.escape):
                imgui.close_current_popup()
            imgui.end_popup()

        imgui.set_next_window_pos(center, imgui.Cond_.appearing, V2(0.5, 0.5))
        if imgui.begin_popup_modal("Close Project", None, auto)[0]:
            imgui.text("Close the current project?")
            if self._close_unsaved:
                imgui.text_disabled("Changes since the last save will be lost unless you save.")
            if imgui.button("Save and close", V2(130 * s, 0)):
                if self._save():
                    self._close_project()
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Close", V2(100 * s, 0)):
                self._close_project()
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", V2(100 * s, 0)) or imgui.is_key_pressed(imgui.Key.escape):
                imgui.close_current_popup()
            imgui.end_popup()

        imgui.set_next_window_pos(center, imgui.Cond_.appearing, V2(0.5, 0.5))
        if imgui.begin_popup_modal("Unsaved Changes", None, auto)[0]:
            name = os.path.basename(self.project_path) if self.project_path else "this project"
            imgui.text(f"Save changes to {name} before closing?")
            imgui.text_disabled("Your changes will be lost if you don't save them.")
            imgui.spacing()
            if imgui.button("Save", V2(110 * s, 0)) or imgui.is_key_pressed(imgui.Key.enter):
                imgui.close_current_popup()
                if self._save():
                    self._quit_now()
            _tip("Save the project, then quit. Cancelling the file dialog keeps Strata open.")
            imgui.same_line()
            if imgui.button("Don't Save", V2(110 * s, 0)):
                imgui.close_current_popup()
                self._quit_now()
            _tip("Quit and discard the unsaved changes.")
            imgui.same_line()
            if imgui.button("Cancel", V2(110 * s, 0)) or imgui.is_key_pressed(imgui.Key.escape):
                imgui.close_current_popup()
            _tip("Keep working.")
            imgui.end_popup()

    def _export_template(self):
        return self.export_custom_template or texture_exporter.OUTPUT_TEMPLATES[self.export_templates[self.export_preset]]

    def _export_manifest(self, template=None, overrides=None):
        if self.export_set_identity != id(self.engine.mesh):
            self.export_sets = {i: True for i in range(len(self.engine.sets))}
            self.export_set_identity = id(self.engine.mesh)
        if template is None:
            template = self.export_custom_template or self.export_templates[self.export_preset]
        return texture_exporter.build_export_manifest(
            self.engine, self.export_dir, template=template, file_format=self.export_format or None,
            depth=self.export_depth or None, size=self.export_size, padding=self.export_padding,
            dilation=self.export_dilation, texture_sets=[i for i, on in self.export_sets.items() if on],
            project=self.export_name or None, overrides=self.export_overrides if overrides is None else overrides)

    def _export_files(self, manifest=None):
        manifest = manifest or self._export_manifest()
        return [(os.path.basename(e.path), f"{e.set_name} | {e.format.upper()} {e.depth} | {e.resolution} x {e.resolution}")
                for e in manifest.entries]

    def _export_options(self):
        """Export UI only; evaluation and naming live in the shared manifest."""
        s = self.ui_scale
        changed, choice = imgui.combo("Output template", self.export_preset, self.export_templates)
        if changed:
            self.export_preset, self.export_custom_template = choice, None
            self.export_template_json, self.export_overrides = "", {}
        if self.export_custom_template is not None:
            imgui.text_disabled("Custom: " + self.export_custom_template.get("name", "Unnamed"))
        _, self.export_name = imgui.input_text("Project name token", self.export_name)
        _tip("Replaces $project in templates that use it. Texture set names keep multiset outputs distinct.")
        _, self.export_dir = imgui.input_text("Folder", self.export_dir)
        imgui.same_line()
        if imgui.button("Browse") and pfd is not None:
            p = pfd.select_folder("Export folder", self.export_dir).result()
            if p:
                self.export_dir = p
        formats = [""] + list(texture_exporter.FORMATS)
        _, v = imgui.combo("File format", formats.index(self.export_format), ["Based on template"] + formats[1:])
        self.export_format = formats[v]
        depths = [""] + sorted({d for values in texture_exporter.FORMATS.values() for d in values})
        _, v = imgui.combo("Bit depth", depths.index(self.export_depth), ["Based on template"] + depths[1:])
        self.export_depth = depths[v]
        sizes = texture_exporter.SIZES
        _, v = imgui.combo("Output size", sizes.index(self.export_size), ["Texture set size"] + [str(n) for n in sizes[1:]])
        self.export_size = sizes[v]
        _, v = imgui.combo("Padding", texture_exporter.PADDING.index(self.export_padding), texture_exporter.PADDING)
        self.export_padding = texture_exporter.PADDING[v]
        if self.export_padding not in ("none", "infinite"):
            _, self.export_dilation = imgui.slider_int("Dilation (px)", self.export_dilation, 0, 128)
        # Reset per-project selections even when the user has deselected all sets.
        if self.export_set_identity != id(self.engine.mesh):
            self.export_sets = {i: True for i in range(len(self.engine.sets))}
            self.export_set_identity = id(self.engine.mesh)
        if imgui.collapsing_header("Texture sets"):
            for i, ts in enumerate(self.engine.sets):
                _, self.export_sets[i] = imgui.checkbox(f"{ts.name} ({ts.res})##export-set{i}", self.export_sets.get(i, True))
        if imgui.collapsing_header("Output maps"):
            for i, m in enumerate(self._export_template().get("maps", [])):
                name = m.get("name", f"Unnamed {i}")
                ov = self.export_overrides.setdefault(name, {})
                _, enabled = imgui.checkbox(f"{name}##export-map{i}", ov.get("enabled", m.get("enabled", True)))
                ov["enabled"] = enabled
                fmts = [""] + list(texture_exporter.FORMATS)
                current = ov.get("format", "")
                _, fv = imgui.combo(f"Format##export-map-fmt{i}", fmts.index(current), ["Template / global"] + fmts[1:])
                ov["format"] = fmts[fv]
                current = ov.get("depth", "")
                _, dv = imgui.combo(f"Depth##export-map-depth{i}", depths.index(current), ["Template / global"] + depths[1:])
                ov["depth"] = depths[dv]
        if imgui.collapsing_header("Template editor"):
            if not self.export_template_json:
                self.export_template_json = json.dumps(self._export_template(), indent=2)
            imgui.text_disabled("Edit map names, channel packing and defaults. Apply to update the preview.")
            _, self.export_template_json = imgui.input_text_multiline(
                "##export-template-json", self.export_template_json, V2(600 * s, 180 * s))
            if imgui.button("Apply template"):
                try:
                    candidate = json.loads(self.export_template_json)
                    # A manifest validates the editable template before accepting it.
                    self._export_manifest(template=candidate, overrides={})
                    self.export_custom_template, self.export_overrides = candidate, {}
                except Exception as ex:
                    self.msg(f"Template not applied: {ex}")
            imgui.same_line()
            if imgui.button("Load JSON...") and pfd is not None:
                paths = pfd.open_file("Load export template", "", ["JSON template", "*.json"]).result()
                if paths:
                    try:
                        candidate = texture_exporter.load_template(paths[0])
                        self._export_manifest(template=candidate, overrides={})
                        self.export_custom_template, self.export_overrides = candidate, {}
                        self.export_template_json = json.dumps(candidate, indent=2)
                    except Exception as ex:
                        self.msg(f"Template not loaded: {ex}")
            imgui.same_line()
            if imgui.button("Save JSON...") and pfd is not None:
                path = pfd.save_file("Save export template", "template.json", ["JSON template", "*.json"]).result()
                if path:
                    try:
                        template = copy.deepcopy(self._export_template())
                        for m in template["maps"]:
                            m.update({k: v for k, v in self.export_overrides.get(m["name"], {}).items() if v != ""})
                        texture_exporter.save_template(template, path)
                    except Exception as ex:
                        self.msg(f"Template not saved: {ex}")

    def dialogs(self):
        s = self.ui_scale
        center = imgui.get_main_viewport().get_center()
        if self.open_new:
            imgui.open_popup("New Project")
            self.open_new = False
        if self.open_export and self.engine.comp is None:
            self.open_export = False
            self.msg("Nothing to export yet: create or open a project first.")
        if self.open_spp:
            imgui.open_popup("Import Substance Painter Project")
            self.open_spp = False
        if self.open_report:
            imgui.open_popup("Import Report")
            self.open_report = False
        if self.open_export:
            imgui.open_popup("Export Textures")
            self.open_export = False
            if not self.export_name and self.engine.mesh is not None:
                self.export_name = self.engine.mesh.name
        auto = imgui.WindowFlags_.always_auto_resize

        imgui.set_next_window_pos(center, imgui.Cond_.appearing, V2(0.5, 0.5))
        if imgui.begin_popup_modal("New Project", None, auto)[0]:
            names = list(BUILTIN_MESHES) + ["From file..."]
            imgui.set_next_item_width(260 * s)
            ch, self.new_mesh_idx = imgui.combo("Mesh", self.new_mesh_idx, names)
            from_file = self.new_mesh_idx == len(BUILTIN_MESHES)
            if from_file:
                imgui.set_next_item_width(260 * s)
                _, self.new_path = imgui.input_text("Path", self.new_path)
                imgui.same_line()
                if imgui.button("Browse"):
                    p = self._ask_mesh()
                    if p:
                        self.new_path = p
                imgui.text_disabled("OBJ works out of the box. FBX/glTF need: pip install assimp-py")
            imgui.set_next_item_width(260 * s)
            _, self.new_res_idx = imgui.combo("Document resolution", self.new_res_idx, [str(r) for r in RESOLUTIONS])
            _, self.new_color_mode = imgui.combo("Color workflow", self.new_color_mode, ["Legacy", "Managed linear (OpenColorIO)"])
            _, self.new_tangent_basis = imgui.combo("Tangent basis", self.new_tangent_basis, ["Legacy", "MikkTSpace (external Blender)"])
            _, self.new_unit = imgui.combo("Source units", self.new_unit, ["Unspecified", "Meters", "Centimeters", "Millimeters", "Inches", "Feet"])
            _, self.new_auto_uv = imgui.checkbox("Prepare missing UVs (Blender)", self.new_auto_uv)
            if self.new_auto_uv:
                _, self.new_uv_regenerate = imgui.checkbox("Regenerate valid UVs too", self.new_uv_regenerate)
                _, self.new_uv_method = imgui.combo("Unwrap method", self.new_uv_method, ["Smart project / angle seams", "Angle based / dihedral seams"])
                _, self.new_uv_padding = imgui.slider_int("UV padding (pixels)", self.new_uv_padding, 0, 32)
                _, self.new_uv_angle = imgui.slider_float("UV seam angle", self.new_uv_angle, 1., 89., "%.1f deg")
                _, self.new_uv_rotate = imgui.checkbox("Allow UV island rotation", self.new_uv_rotate)
                _, self.new_uv_tiles = imgui.slider_int("UV tile budget per material", self.new_uv_tiles, 1, 64)
                imgui.text_wrapped("Angle-seam charts are distributed across up to this many UDIM tiles. Valid UVs stay fixed; generated multi-tile materials enable tiled painting automatically.")
            if from_file and self.new_path and imgui.button("Inspect UV availability"):
                def inspect_uvs():
                    from .uvprep import uv_status
                    candidate = load_mesh(self.new_path, require_uvs=False)
                    valid = uv_status(candidate)
                    self.new_uv_info = f"{int(valid.sum())} valid / {int((~valid).sum())} missing or degenerate UV triangles; {len(candidate.material_names)} materials"
                self._run_busy("Inspecting UV availability...", inspect_uvs)
            if self.new_uv_info:
                imgui.text_wrapped(self.new_uv_info)
            imgui.text_wrapped("Existing projects retain their saved workflow. Managed pickers use sRGB colors; scalar maps and normals are data.")
            imgui.text_disabled("Mesh maps (AO, curvature, position, normal) are baked automatically.\n"
                                "Starts a fresh layer stack: unsaved changes are lost.")
            ok = not from_file or bool(self.new_path)
            if not ok:
                imgui.begin_disabled()
            if imgui.button("OK", V2(120 * s, 0)):
                res = RESOLUTIONS[self.new_res_idx]
                if from_file:
                    path = self.new_path

                    def job():
                        self._new_project(load_mesh(path, require_uvs=not self.new_auto_uv), res)
                    self._run_busy(f"Loading {os.path.basename(path)}...", job)
                else:
                    name = names[self.new_mesh_idx]
                    self._run_busy(f"Baking {name}...", lambda: self._new_project(name, res))
                imgui.close_current_popup()
            if not ok:
                imgui.end_disabled()
                _tip("Choose a mesh file first.")
            imgui.same_line()
            if imgui.button("Cancel", V2(120 * s, 0)) or imgui.is_key_pressed(imgui.Key.escape):
                imgui.close_current_popup()
            imgui.end_popup()

        imgui.set_next_window_pos(center, imgui.Cond_.appearing, V2(0.5, 0.5))
        if imgui.begin_popup_modal("Import Substance Painter Project", None, auto)[0]:
            info = self.spp_info
            imgui.text(os.path.basename(info.path))
            imgui.text_disabled(f"Saved with Substance 3D Painter {info.version or '(unknown version)'}")
            imgui.spacing()
            sets = info.texture_sets
            if len(sets) > 1:
                imgui.text("Texture sets")
                _tip("Every texture set is imported. The one you select opens first.")
            if imgui.begin_table("##sets", 4, imgui.TableFlags_.row_bg | imgui.TableFlags_.borders_outer):
                for h in ("Texture set", "Resolution", "Layers", "Strokes"):
                    imgui.table_setup_column(h)
                imgui.table_headers_row()
                for ts in sets:
                    imgui.table_next_row()
                    imgui.table_next_column()
                    if imgui.selectable(f"{ts.name}##ts{ts.index}", self.spp_set == ts.index,
                                        imgui.SelectableFlags_.span_all_columns)[0]:
                        self.spp_set = ts.index
                    imgui.table_next_column(); imgui.text(f"{ts.resolution}")
                    imgui.table_next_column(); imgui.text(f"{ts.layer_count}")
                    imgui.table_next_column(); imgui.text(f"{ts.stroke_count}")
                imgui.end_table()
            imgui.push_text_wrap_pos(420 * s)
            imgui.text_disabled("Brings in the mesh, the layer stack and the recorded paint strokes, which are "
                                "replayed with Strata's brush. Painter's procedural materials, filters and "
                                "generators are approximated with Strata's own; a report lists what changed. "
                                "Starts a new Strata project: unsaved changes are lost.")
            imgui.pop_text_wrap_pos()
            self.import_ui.budgets()
            if imgui.button("Import", V2(120 * s, 0)):
                self._import_spp(info, self.spp_set)
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", V2(120 * s, 0)) or imgui.is_key_pressed(imgui.Key.escape):
                imgui.close_current_popup()
            imgui.end_popup()

        imgui.set_next_window_pos(center, imgui.Cond_.appearing, V2(0.5, 0.5))
        if imgui.begin_popup_modal("Import Report", None, auto)[0]:
            title, summary, lines, layer_names = self.report
            imgui.text(title)
            imgui.text_disabled(summary)
            imgui.spacing()
            if layer_names:
                imgui.text("Layers (top first)")
                imgui.begin_child("##replayers", V2(460 * s, min(len(layer_names), 8) * imgui.get_text_line_height_with_spacing() + 8 * s), imgui.ChildFlags_.borders)
                for n in layer_names:
                    imgui.text(n)
                imgui.end_child()
            imgui.text("Approximations" if lines else "Nothing had to be approximated.")
            if lines:
                imgui.begin_child("##repnotes", V2(460 * s, min(len(lines), 10) * imgui.get_text_line_height_with_spacing() * 1.4 + 8 * s), imgui.ChildFlags_.borders)
                for n in lines:
                    imgui.bullet()
                    imgui.same_line()
                    imgui.text_wrapped(n)
                imgui.end_child()
            imgui.text_disabled("Also in Window > Log.")
            if imgui.button("Close", V2(120 * s, 0)) or imgui.is_key_pressed(imgui.Key.escape):
                imgui.close_current_popup()
            imgui.end_popup()

        imgui.set_next_window_pos(center, imgui.Cond_.appearing, V2(0.5, 0.5))
        imgui.set_next_window_pos(center, imgui.Cond_.always, V2(.5, .5))
        screen = imgui.get_main_viewport().size
        imgui.set_next_window_size_constraints(V2(240, 0), V2(max(screen.x - 24, 240), max(screen.y - 24, 240)))
        if imgui.begin_popup_modal("Export Textures", None, auto)[0]:
            screen = imgui.get_main_viewport().size
            export_width = min(880 * s, max(screen.x - 80 * s, 220))
            body_budget = max(screen.y - 220 * s, 160)
            options_height = min(390 * s, body_budget * .65)
            preview_height = min(150 * s, body_budget * .22)
            if imgui.begin_tab_bar("##export-tabs"):
                if imgui.begin_tab_item("Export settings")[0]:
                    imgui.begin_child("##export-options", V2(export_width, options_height), imgui.ChildFlags_.borders)
                    self._export_options()
                    imgui.end_child()
                    imgui.end_tab_item()
                if imgui.begin_tab_item("Output templates")[0]:
                    imgui.begin_child("##visual-template", V2(export_width, options_height), imgui.ChildFlags_.borders)
                    self.export_ui.draw()
                    imgui.end_child()
                    imgui.end_tab_item()
                flags = imgui.TabItemFlags_.set_selected if self.export_results_requested else 0
                if imgui.begin_tab_item("List of exports", None, flags)[0]:
                    self.export_results_requested = False
                    imgui.begin_child("##export-results", V2(export_width, options_height), imgui.ChildFlags_.borders)
                    for result in self.export_results:
                        imgui.text_wrapped(result)
                    if not self.export_results:
                        imgui.text_disabled("No textures exported in this session.")
                    imgui.end_child()
                    imgui.end_tab_item()
                imgui.end_tab_bar()
            manifest, problem = None, None
            try:
                manifest = self._export_manifest()
            except Exception as ex:
                problem = str(ex)
            imgui.spacing()
            imgui.text("Files that will be written")
            imgui.begin_child("##export-preview", V2(export_width, preview_height), imgui.ChildFlags_.borders)
            if manifest and imgui.begin_table("##files", 2, imgui.TableFlags_.row_bg | imgui.TableFlags_.borders_outer):
                for fn, what in self._export_files(manifest):
                    imgui.table_next_row()
                    imgui.table_next_column(); imgui.text(fn)
                    imgui.table_next_column(); imgui.text_disabled(what)
                imgui.end_table()
            if problem:
                imgui.text_wrapped(problem)
            imgui.end_child()
            imgui.text_wrapped("Larger outputs regenerate procedural fills and supported native paint. Legacy/imported raster bases and clone/smudge checkpoints are resampled.")
            if sys.platform == "win32":
                _, self.export_open_folder = imgui.checkbox("Open the folder when done", self.export_open_folder)
            imgui.begin_disabled(manifest is None)
            if imgui.button("Export", V2(120 * s, 0)):
                try:
                    settings = self.export_ui.snapshot()
                    files = texture_exporter.write_export_manifest(self.engine, manifest)
                    self._edit_properties("Save export settings", [(self.engine, {"export_settings": settings})])
                    self.export_results = ["Written: " + str(path) for path in files]
                    self.export_results_requested = True
                    self.msg(f"Exported {len(files)} maps to {self.export_dir}")
                    if self.export_open_folder and sys.platform == "win32":
                        os.startfile(self.export_dir)  # noqa
                except Exception as e:
                    traceback.print_exc()
                    self.export_results = ["Export failed: " + str(e)]
                    self.export_results_requested = True
                    self.msg(f"Export failed: {e}")
            imgui.end_disabled()
            imgui.same_line()
            imgui.begin_disabled(manifest is None)
            if imgui.button("Save settings"):
                self.export_ui.save_settings()
            imgui.end_disabled()
            imgui.same_line()
            if imgui.button("Cancel", V2(120 * s, 0)) or imgui.is_key_pressed(imgui.Key.escape):
                imgui.close_current_popup()
            imgui.end_popup()


def main():
    app = App()
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".strata"):
        path = sys.argv[1]
        app._run_busy("Opening project...", lambda: app._open(path))
    elif len(sys.argv) > 1 and sys.argv[1].lower().endswith(".spp"):
        app._begin_spp(sys.argv[1])
    app.run()


if __name__ == "__main__":
    main()
