"""Desktop front end: GLFW window, Dear ImGui panels, viewport input."""
from __future__ import annotations

import os
import sys
import time
import traceback

import glfw
import moderngl
import numpy as np
from imgui_bundle import imgui
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer

from .engine import Engine
from .exporter import EXPORT_PRESETS, export
from .layers import BLEND_MODES, CHANNELS, GENERATORS, HEIGHT_BLEND
from .mesh import BUILTIN_MESHES, load_mesh
from .presets import MATERIALS, SMART_MATERIALS
from .renderer import DISPLAY_MODES

try:
    from imgui_bundle import portable_file_dialogs as pfd
except Exception:  # pragma: no cover
    pfd = None

APP = "Strata"
LEFT_W, RIGHT_W, STATUS_H = 290, 330, 26
RESOLUTIONS = [512, 1024, 2048, 4096]
MESH_EXTS = ["*.obj", "*.fbx", "*.gltf", "*.glb"]
V2 = imgui.ImVec2


def _apply_theme():
    s = imgui.get_style()
    s.window_rounding = 0.0
    s.frame_rounding = 3.0
    s.grab_rounding = 3.0
    s.window_border_size = 1.0
    s.frame_padding = V2(6, 4)
    s.item_spacing = V2(6, 5)
    s.scrollbar_size = 12
    C = imgui.Col_
    acc = imgui.ImVec4(0.18, 0.62, 0.62, 1.0)
    acc_h = imgui.ImVec4(0.24, 0.72, 0.72, 1.0)
    pal = {
        C.window_bg: (0.13, 0.135, 0.145, 1.0), C.child_bg: (0.12, 0.125, 0.135, 1.0),
        C.popup_bg: (0.14, 0.145, 0.155, 0.98), C.menu_bar_bg: (0.10, 0.105, 0.115, 1.0),
        C.border: (0.22, 0.23, 0.25, 1.0), C.frame_bg: (0.19, 0.2, 0.215, 1.0),
        C.frame_bg_hovered: (0.24, 0.25, 0.27, 1.0), C.frame_bg_active: (0.27, 0.28, 0.3, 1.0),
        C.title_bg: (0.10, 0.105, 0.115, 1.0), C.title_bg_active: (0.10, 0.105, 0.115, 1.0),
        C.header: (0.18, 0.40, 0.42, 0.8), C.header_hovered: (0.22, 0.48, 0.5, 0.9),
        C.header_active: (0.24, 0.55, 0.57, 1.0), C.button: (0.21, 0.22, 0.24, 1.0),
        C.button_hovered: (0.26, 0.40, 0.42, 1.0), C.button_active: (0.18, 0.55, 0.56, 1.0),
        C.tab: (0.16, 0.17, 0.18, 1.0), C.tab_hovered: (0.22, 0.48, 0.5, 1.0),
        C.tab_selected: (0.18, 0.40, 0.42, 1.0), C.separator: (0.22, 0.23, 0.25, 1.0),
        C.text: (0.88, 0.89, 0.9, 1.0), C.text_disabled: (0.5, 0.52, 0.55, 1.0),
    }
    for k, v in pal.items():
        s.set_color_(k, imgui.ImVec4(*v))
    s.set_color_(C.modal_window_dim_bg, imgui.ImVec4(0.0, 0.0, 0.0, 0.45))
    s.set_color_(C.check_mark, acc)
    s.set_color_(C.slider_grab, acc)
    s.set_color_(C.slider_grab_active, acc_h)


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

        imgui.create_context()
        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.nav_enable_keyboard
        io.set_ini_filename("")
        self._load_font()
        _apply_theme()
        self.impl = GlfwRenderer(self.window)
        glfw.set_drop_callback(self.window, self._on_drop)

        self.engine = Engine(self.ctx)
        self.project_path = None
        self.status, self.status_t = "", 0.0
        self.pending = None          # (label, callable) run after a 'working' frame is shown
        self._pending_shown = 0
        self.drag = None
        self.cursor = None
        self.vp_rect = (0, 0, 1, 1)
        self.fb_scale = (1.0, 1.0)
        # dialogs
        self.open_new = False
        self.open_export = False
        self.open_help = False
        self.new_mesh_idx, self.new_res_idx, self.new_path = 0, 2, ""
        self.export_preset, self.export_dir = 0, os.path.abspath("export")
        self.fps = 0.0

        self._run_busy("Baking Rounded Cube...", lambda: self._new_project("Rounded Cube", 2048))

    # ------------------------------------------------------------------ helpers
    def _load_font(self):
        import imgui_bundle
        base = os.path.join(os.path.dirname(imgui_bundle.__file__), "assets", "fonts")
        for p in (os.path.join(base, "Roboto", "Roboto-Regular.ttf"), os.path.join(base, "DroidSans.ttf")):
            if os.path.exists(p):
                imgui.get_io().fonts.add_font_from_file_ttf(p, 15.0)
                return

    def msg(self, text):
        self.status, self.status_t = text, time.time()
        print(text)

    def _run_busy(self, label, fn):
        self.pending = (label, fn)
        self._pending_shown = 0

    def _new_project(self, mesh, res):
        t = time.time()
        self.engine.new_project(mesh, res)
        self.project_path = None
        name = mesh if isinstance(mesh, str) else mesh.name
        self.msg(f"New project: {name} @ {res}px  (baked in {time.time() - t:.1f}s)")
        uv = self.engine.mesh.uvs
        if uv.min() < -1e-3 or uv.max() > 1.001:
            self.msg("Warning: this mesh has UVs outside 0-1; those parts can't be painted.")

    def _on_drop(self, window, paths):
        if not paths:
            return
        p = paths[0]
        ext = os.path.splitext(p)[1].lower()
        if ext == ".strata":
            self._run_busy("Opening project...", lambda: self._open(p))
        elif ext in (".obj", ".fbx", ".gltf", ".glb"):
            self.new_path, self.new_mesh_idx = p, len(BUILTIN_MESHES)
            self.open_new = True

    def _open(self, path):
        self.engine.load(path)
        self.project_path = path
        self.msg(f"Opened {os.path.basename(path)}")

    def _save(self, save_as=False):
        path = self.project_path
        if save_as or not path:
            if pfd is None:
                self.msg("File dialogs unavailable"); return
            path = pfd.save_file("Save project", "untitled.strata", ["Strata project", "*.strata"]).result()
            if not path:
                return
            if not path.lower().endswith(".strata"):
                path += ".strata"
        try:
            self.engine.save(path)
            self.project_path = path
            self.msg(f"Saved {path}")
        except Exception as e:
            self.msg(f"Save failed: {e}")

    def _ask_open(self):
        if pfd is None:
            self.msg("File dialogs unavailable"); return
        r = pfd.open_file("Open project", "", ["Strata project", "*.strata"]).result()
        if r:
            self._run_busy("Opening project...", lambda: self._open(r[0]))

    def _ask_mesh(self):
        if pfd is None:
            return ""
        r = pfd.open_file("Import mesh", "", ["Meshes", " ".join(MESH_EXTS)]).result()
        return r[0] if r else ""

    # ------------------------------------------------------------------ main loop
    def run(self):
        last = time.time()
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
        self._drain_gl_errors()
        try:
            self.impl.shutdown()
        except Exception:
            pass
        glfw.terminate()

    def frame(self):
        imgui.new_frame()
        io = imgui.get_io()
        ww, wh = glfw.get_window_size(self.window)
        fw, fh = glfw.get_framebuffer_size(self.window)
        self.fb_scale = (fw / max(ww, 1), fh / max(wh, 1))
        menu_h = self.menu_bar()
        has_project = self.engine.comp is not None
        vx, vy, vw, vh = LEFT_W, menu_h, max(ww - LEFT_W - RIGHT_W, 1), max(wh - menu_h - STATUS_H, 1)
        self.vp_rect = (vx, vy, vw, vh)
        if has_project:
            self.left_panel(menu_h, wh)
            self.right_panel(ww, menu_h, wh)
        self.status_bar(ww, wh)
        self.dialogs()
        if self.pending:
            self.busy_overlay(ww, wh)
            self._pending_shown += 1
        if has_project and not self.pending:
            self.shortcuts()
            self.viewport_input()

        self.ctx.screen.use()
        self.ctx.viewport = (0, 0, fw, fh)
        self.ctx.clear(0.08, 0.085, 0.09)
        if has_project:
            sx, sy = self.fb_scale
            rect = (int(vx * sx), int((wh - vy - vh) * sy), int(vw * sx), int(vh * sy))
            self.engine.update_view(rect[2], rect[3])
            if self.drag == "paint":      # stroke follows the cursor every frame
                self._paint_at_cursor()
            self.cursor = self._pick_cursor() if self.drag in (None, "paint") else None
            self.ctx.screen.use()
            self.engine.render(rect, cursor=self.cursor if self._cursor_visible() else None)
        self.ctx.screen.use()
        self.ctx.viewport = (0, 0, fw, fh)
        imgui.render()
        self._drain_gl_errors()
        self.impl.render(imgui.get_draw_data())

    def _drain_gl_errors(self):
        # moderngl never checks glGetError, but the PyOpenGL-based ImGui backend does, so a
        # stale flag from a harmless driver query would surface there as an exception.
        for _ in range(16):
            if self.ctx.error == "GL_NO_ERROR":
                break

    # ------------------------------------------------------------------ viewport input
    def _mouse_vp(self):
        """Mouse position in viewport framebuffer pixels, origin bottom-left."""
        mx, my = imgui.get_io().mouse_pos
        vx, vy, vw, vh = self.vp_rect
        sx, sy = self.fb_scale
        return (mx - vx) * sx, (vy + vh - my) * sy

    def _over_viewport(self):
        io = imgui.get_io()
        mx, my = io.mouse_pos
        vx, vy, vw, vh = self.vp_rect
        return vx <= mx < vx + vw and vy <= my < vy + vh and not io.want_capture_mouse

    def _pick_cursor(self):
        if not (self._over_viewport() or self.drag == "paint"):
            return None
        return self.engine.pick(*self._mouse_vp())

    def _cursor_visible(self):
        return self.cursor is not None and not imgui.get_io().key_alt

    def _paint_at_cursor(self):
        hit = self.engine.pick(*self._mouse_vp())
        if hit is not None:
            self.engine.stroke_to(hit[0])

    def viewport_input(self):
        io = imgui.get_io()
        eng = self.engine
        over = self._over_viewport()
        alt = io.key_alt
        if over and not self.drag:
            if imgui.is_mouse_clicked(0):
                if alt:
                    self.drag = "orbit"
                else:
                    hit = eng.pick(*self._mouse_vp())
                    if not eng.can_paint():
                        lay = eng.layer
                        self.msg("Select a paint layer to paint (or switch the brush target to Mask)."
                                 if lay is None or lay.kind != "paint" or lay.visible else "Layer is hidden.")
                    elif hit is not None and eng.begin_stroke(hit[0]):
                        self.drag = "paint"
            elif imgui.is_mouse_clicked(1):
                self.drag = "zoom" if alt else "orbit"
            elif imgui.is_mouse_clicked(2):
                self.drag = "pan"
            if io.mouse_wheel:
                if io.key_ctrl:
                    eng.brush.size_px = float(np.clip(eng.brush.size_px * (1.1 ** io.mouse_wheel), 2, 1000))
                else:
                    eng.camera.zoom(io.mouse_wheel)
        if self.drag:
            button = {"paint": 0, "orbit": None, "zoom": 1, "pan": 2}[self.drag]
            if self.drag == "orbit":
                held = imgui.is_mouse_down(0) or imgui.is_mouse_down(1)
            else:
                held = imgui.is_mouse_down(button)
            dx, dy = io.mouse_delta
            if self.drag == "orbit":
                eng.camera.orbit(dx, dy)
            elif self.drag == "pan":
                eng.camera.pan(dx, dy, self.vp_rect[3])
            elif self.drag == "zoom":
                eng.camera.zoom(-dy * 0.03)
            if not held:
                if self.drag == "paint":
                    eng.end_stroke()
                self.drag = None

    def shortcuts(self):
        io = imgui.get_io()
        if io.want_text_input:
            return
        eng, K = self.engine, imgui.Key
        ctrl, shift = io.key_ctrl, io.key_shift
        pressed = lambda k: imgui.is_key_pressed(k, False)
        if ctrl and pressed(K.z):
            eng.redo() if shift else eng.undo()
        elif ctrl and pressed(K.y):
            eng.redo()
        elif ctrl and pressed(K.s):
            self._save(save_as=shift)
        elif ctrl and pressed(K.o):
            self._ask_open()
        elif ctrl and pressed(K.n):
            self.open_new = True
        elif ctrl and pressed(K.e):
            self.open_export = True
        elif not ctrl:
            if imgui.is_key_pressed(K.left_bracket):
                eng.brush.size_px = max(2.0, eng.brush.size_px / 1.15)
            if imgui.is_key_pressed(K.right_bracket):
                eng.brush.size_px = min(1000.0, eng.brush.size_px * 1.15)
            if pressed(K.f):
                eng.camera.frame(eng.mesh.center, eng.mesh.radius)
            if pressed(K.e):
                eng.brush.mode = 1 - eng.brush.mode
            if pressed(K.m):
                eng.brush.target = 1 - eng.brush.target
            if pressed(K.x):
                eng.brush.mask_value = 1.0 - eng.brush.mask_value
            if pressed(K.c):
                eng.renderer.mode = (eng.renderer.mode + 1) % len(DISPLAY_MODES)
                eng.dirty = True
            if pressed(K.delete) and eng.layer is not None:
                eng.delete_layer()
            if pressed(K.f1):
                self.open_help = True

    # ------------------------------------------------------------------ panels
    def menu_bar(self):
        h = 0
        eng = self.engine
        if imgui.begin_main_menu_bar():
            h = imgui.get_window_size().y
            if imgui.begin_menu("File"):
                if imgui.menu_item("New Project...", "Ctrl+N", False)[0]:
                    self.open_new = True
                if imgui.menu_item("Open...", "Ctrl+O", False)[0]:
                    self._ask_open()
                if imgui.menu_item("Save", "Ctrl+S", False, eng.comp is not None)[0]:
                    self._save()
                if imgui.menu_item("Save As...", "Ctrl+Shift+S", False, eng.comp is not None)[0]:
                    self._save(save_as=True)
                imgui.separator()
                if imgui.menu_item("Export Textures...", "Ctrl+E", False, eng.comp is not None)[0]:
                    self.open_export = True
                imgui.separator()
                if imgui.menu_item("Quit", "", False)[0]:
                    glfw.set_window_should_close(self.window, True)
                imgui.end_menu()
            if imgui.begin_menu("Edit"):
                if imgui.menu_item("Undo", "Ctrl+Z", False, bool(eng.undo_stack))[0]:
                    eng.undo()
                if imgui.menu_item("Redo", "Ctrl+Y", False, bool(eng.redo_stack))[0]:
                    eng.redo()
                imgui.end_menu()
            if imgui.begin_menu("View"):
                for i, name in enumerate(DISPLAY_MODES):
                    if imgui.menu_item(name, "", eng.renderer.mode == i)[0]:
                        eng.renderer.mode = i
                        eng.dirty = True
                imgui.separator()
                if imgui.menu_item("Frame Mesh", "F", False)[0] and eng.mesh is not None:
                    eng.camera.frame(eng.mesh.center, eng.mesh.radius)
                imgui.end_menu()
            if imgui.begin_menu("Help"):
                if imgui.menu_item("Controls", "F1", False)[0]:
                    self.open_help = True
                imgui.end_menu()
            imgui.end_main_menu_bar()
        return h

    def _panel(self, name, x, y, w, h):
        imgui.set_next_window_pos(V2(x, y))
        imgui.set_next_window_size(V2(w, h))
        flags = (imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_resize |
                 imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_bring_to_front_on_focus)
        imgui.begin(name, None, flags)

    def left_panel(self, top, wh):
        eng = self.engine
        self._panel("Layers", 0, top, LEFT_W, wh - top - STATUS_H)
        bw = (imgui.get_content_region_avail().x - 12) / 3
        if imgui.button("+ Paint", V2(bw, 0)):
            eng.add_layer("paint")
        imgui.same_line()
        if imgui.button("+ Fill", V2(bw, 0)):
            eng.add_layer("fill")
        imgui.same_line()
        if imgui.button("Smart...", V2(bw, 0)):
            imgui.open_popup("smart_mats")
        if imgui.begin_popup("smart_mats"):
            for name in SMART_MATERIALS:
                if imgui.selectable(name, False)[0]:
                    eng.add_smart_material(name)
            imgui.end_popup()
        n = len(eng.layers)
        sel = eng.selected
        if imgui.button("Up", V2(bw * 0.75, 0)) and sel >= 0:
            eng.move_layer(sel, +1)
        imgui.same_line()
        if imgui.button("Down", V2(bw * 0.75, 0)) and sel >= 0:
            eng.move_layer(sel, -1)
        imgui.same_line()
        if imgui.button("Dup", V2(bw * 0.7, 0)) and sel >= 0:
            eng.duplicate_layer()
        imgui.same_line()
        if imgui.button("Del", V2(-1, 0)) and sel >= 0:
            eng.delete_layer()
        imgui.separator()
        imgui.begin_child("layer_list", V2(0, -170))
        for i in reversed(range(n)):            # top of stack first
            lay = eng.layers[i]
            imgui.push_id(str(lay.uid))
            ch, vis = imgui.checkbox("##vis", lay.visible)
            if ch:
                lay.visible = vis
                eng.dirty = True
            imgui.same_line()
            tag = "P" if lay.kind == "paint" else "F"
            col = imgui.ImVec4(0.45, 0.8, 0.8, 1) if lay.kind == "paint" else imgui.ImVec4(0.85, 0.7, 0.4, 1)
            imgui.text_colored(col, tag)
            imgui.same_line()
            swatch = imgui.ImVec4(*lay.color, 1.0)
            imgui.color_button("##sw", swatch, imgui.ColorEditFlags_.no_tooltip, V2(14, 14))
            imgui.same_line()
            label = lay.name + ("   [mask]" if lay.has_mask or lay.gen.kind else "")
            if imgui.selectable(label, i == eng.selected)[0]:
                eng.selected = i
                eng.dirty = True
            imgui.pop_id()
        imgui.end_child()
        imgui.separator()
        imgui.text_disabled("Materials (click: set brush / fill)")
        imgui.begin_child("mats", V2(0, 0))
        for name, (col, r, m) in MATERIALS.items():
            imgui.color_button(f"##{name}", imgui.ImVec4(*col, 1.0), imgui.ColorEditFlags_.no_tooltip, V2(14, 14))
            imgui.same_line()
            if imgui.selectable(name, False)[0]:
                lay = eng.layer
                if lay is not None and lay.kind == "fill":
                    lay.color, lay.rough, lay.metal = list(col), r, m
                    eng.dirty = True
                else:
                    eng.brush.color, eng.brush.rough, eng.brush.metal = list(col), r, m
        imgui.end_child()
        imgui.end()

    def right_panel(self, ww, top, wh):
        self._panel("Properties", ww - RIGHT_W, top, RIGHT_W, wh - top - STATUS_H)
        if imgui.begin_tab_bar("props"):
            if imgui.begin_tab_item_simple("Brush"):
                self.brush_tab()
                imgui.end_tab_item()
            if imgui.begin_tab_item_simple("Layer"):
                self.layer_tab()
                imgui.end_tab_item()
            if imgui.begin_tab_item_simple("Viewport"):
                self.viewport_tab()
                imgui.end_tab_item()
            imgui.end_tab_bar()
        imgui.end()

    def _slider(self, obj, attr, label, lo=0.0, hi=1.0, fmt="%.2f", dirty=False, flags=0):
        ch, v = imgui.slider_float(label, float(getattr(obj, attr)), lo, hi, fmt, flags)
        if ch:
            setattr(obj, attr, v)
            if dirty:
                self.engine.dirty = True
        return ch

    def _channels(self, obj, dirty):
        en = list(obj.enabled)
        for i, name in enumerate(CHANNELS):
            if i:
                imgui.same_line()
            ch, v = imgui.checkbox(name, bool(en[i]))
            if ch:
                en[i] = v
                obj.enabled = en
                if dirty:
                    self.engine.dirty = True

    def brush_tab(self):
        eng = self.engine
        b = eng.brush
        imgui.spacing()
        if imgui.radio_button("Paint", b.mode == 0):
            b.mode = 0
        imgui.same_line()
        if imgui.radio_button("Erase (E)", b.mode == 1):
            b.mode = 1
        imgui.text_disabled("Target")
        imgui.same_line()
        if imgui.radio_button("Layer", b.target == 0):
            b.target = 0
        imgui.same_line()
        if imgui.radio_button("Mask (M)", b.target == 1):
            b.target = 1
        if b.target == 1:
            imgui.text_disabled("Mask value (X swaps)")
            imgui.same_line()
            if imgui.radio_button("White", b.mask_value > 0.5):
                b.mask_value = 1.0
            imgui.same_line()
            if imgui.radio_button("Black", b.mask_value <= 0.5):
                b.mask_value = 0.0
        imgui.separator()
        log = imgui.SliderFlags_.logarithmic
        self._slider(b, "size_px", "Size  [ ]", 2, 800, "%.0f px", flags=log)
        self._slider(b, "hardness", "Hardness")
        self._slider(b, "flow", "Flow")
        self._slider(b, "spacing", "Spacing", 0.02, 1.0)
        self._slider(b, "grain", "Grain")
        if b.grain > 0:
            self._slider(b, "grain_scale", "Grain scale", 2, 200, "%.0f", flags=log)
        if b.target == 0:
            imgui.separator()
            imgui.text("Channels")
            self._channels(b, False)
            ch, c = imgui.color_edit3("Color", list(b.color))
            if ch:
                b.color = c
            self._slider(b, "rough", "Roughness")
            self._slider(b, "metal", "Metallic")
            self._slider(b, "height", "Height")
            imgui.text_disabled("Height: 0.5 = flat, >0.5 raised")
        lay = eng.layer
        if lay is not None and b.target == 0 and lay.kind != "paint":
            imgui.spacing()
            imgui.text_colored(imgui.ImVec4(0.95, 0.7, 0.35, 1), "Selected layer is a fill layer.\n"
                               "Add a paint layer, or paint its mask.")

    def layer_tab(self):
        eng = self.engine
        lay = eng.layer
        if lay is None:
            imgui.text_disabled("No layer selected.")
            return
        d = True
        ch, name = imgui.input_text("Name", lay.name)
        if ch:
            lay.name = name
        ch, v = imgui.combo("Blend", lay.blend, BLEND_MODES)
        if ch:
            lay.blend, eng.dirty = v, True
        self._slider(lay, "opacity", "Opacity", dirty=d)
        ch, v = imgui.combo("Height blend", lay.hblend, HEIGHT_BLEND)
        if ch:
            lay.hblend, eng.dirty = v, True
        imgui.separator()
        imgui.text("Channels")
        self._channels(lay, True)
        if lay.kind == "fill":
            ch, c = imgui.color_edit3("Color", list(lay.color))
            if ch:
                lay.color, eng.dirty = c, True
            self._slider(lay, "rough", "Roughness", dirty=d)
            self._slider(lay, "metal", "Metallic", dirty=d)
            self._slider(lay, "height", "Height", dirty=d)
            imgui.separator()
            imgui.text("Variation")
            self._slider(lay, "variation", "Color/rough noise", dirty=d)
            self._slider(lay, "bump", "Height noise", dirty=d)
            self._slider(lay, "var_scale", "Noise scale", 0.1, 20, "%.2f", dirty=d, flags=imgui.SliderFlags_.logarithmic)
        else:
            if imgui.button("Clear painting"):
                eng.clear_paint()
        if imgui.button("New random seed"):
            import random
            lay.seed, eng.dirty = random.random(), True

        imgui.separator()
        imgui.text("Mask")
        if not lay.has_mask:
            if imgui.button("Add white mask"):
                eng.add_mask(1.0)
            imgui.same_line()
            if imgui.button("Add black mask"):
                eng.add_mask(0.0)
        else:
            if imgui.button("Fill white"):
                eng.fill_mask(1.0)
            imgui.same_line()
            if imgui.button("Fill black"):
                eng.fill_mask(0.0)
            imgui.same_line()
            if imgui.button("Remove"):
                eng.remove_mask()
        g = lay.gen
        ch, v = imgui.combo("Generator", g.kind, GENERATORS)
        if ch:
            g.kind, eng.dirty = v, True
        if g.kind:
            self._slider(g, "level", "Level", dirty=d)
            self._slider(g, "softness", "Softness", 0.0, 0.5, dirty=d)
            if g.kind != 6:
                self._slider(g, "noise_amount", "Noise breakup", 0.0, 1.5, dirty=d)
            self._slider(g, "noise_scale", "Noise scale", 0.1, 10, dirty=d, flags=imgui.SliderFlags_.logarithmic)
            ch, v = imgui.checkbox("Invert", g.invert)
            if ch:
                g.invert, eng.dirty = v, True
        if imgui.button("Preview mask in viewport"):
            eng.renderer.mode, eng.dirty = 6, True

    def viewport_tab(self):
        eng = self.engine
        r = eng.renderer
        ch, v = imgui.combo("Display (C)", r.mode, DISPLAY_MODES)
        if ch:
            r.mode, eng.dirty = v, True
        self._slider(r, "exposure", "Exposure", 0.1, 4.0)
        self._slider(r, "env_rot", "Light rotation", -3.1416, 3.1416)
        ch, v = imgui.checkbox("Use baked AO", r.use_ao)
        if ch:
            r.use_ao = v
        self._slider(eng, "normal_strength", "Height -> normal", 0.0, 5.0, dirty=True)
        if imgui.button("Frame mesh (F)"):
            eng.camera.frame(eng.mesh.center, eng.mesh.radius)
        imgui.separator()
        m = eng.mesh
        imgui.text_disabled(f"Mesh: {m.name}\n{len(m.positions):,} verts, {len(m.indices):,} tris\n"
                            f"Texture set: {eng.res} x {eng.res}")

    def status_bar(self, ww, wh):
        imgui.set_next_window_pos(V2(0, wh - STATUS_H))
        imgui.set_next_window_size(V2(ww, STATUS_H))
        flags = (imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_move |
                 imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.no_bring_to_front_on_focus)
        imgui.push_style_var(imgui.StyleVar_.window_padding, V2(8, 4))
        imgui.begin("##status", None, flags)
        tip = "LMB paint | Alt+LMB / RMB orbit | MMB pan | wheel zoom | Ctrl+wheel or [ ] brush size | F1 help"
        recent = time.time() - self.status_t < 6
        imgui.text(self.status if recent and self.status else tip)
        imgui.same_line(ww - 90)
        imgui.text_disabled(f"{self.fps:5.0f} fps")
        imgui.end()
        imgui.pop_style_var()

    def busy_overlay(self, ww, wh):
        imgui.set_next_window_pos(V2(ww / 2, wh / 2), 0, V2(0.5, 0.5))
        imgui.begin("##busy", None, imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.always_auto_resize)
        imgui.text(self.pending[0])
        imgui.text_disabled("Baking AO and curvature on the GPU")
        imgui.end()

    # ------------------------------------------------------------------ dialogs
    def dialogs(self):
        center = imgui.get_main_viewport().get_center()
        if self.open_new:
            imgui.open_popup("New Project")
            self.open_new = False
        if self.open_export:
            imgui.open_popup("Export Textures")
            self.open_export = False
        if self.open_help:
            imgui.open_popup("Controls")
            self.open_help = False
        auto = imgui.WindowFlags_.always_auto_resize

        imgui.set_next_window_pos(center, imgui.Cond_.appearing, V2(0.5, 0.5))
        if imgui.begin_popup_modal("New Project", None, auto)[0]:
            names = list(BUILTIN_MESHES) + ["From file..."]
            ch, self.new_mesh_idx = imgui.combo("Mesh", self.new_mesh_idx, names)
            from_file = self.new_mesh_idx == len(BUILTIN_MESHES)
            if from_file:
                _, self.new_path = imgui.input_text("Path", self.new_path)
                imgui.same_line()
                if imgui.button("Browse"):
                    p = self._ask_mesh()
                    if p:
                        self.new_path = p
                imgui.text_disabled("OBJ works out of the box. FBX/glTF need: pip install assimp-py")
            _, self.new_res_idx = imgui.combo("Resolution", self.new_res_idx, [str(r) for r in RESOLUTIONS])
            imgui.text_disabled("Starts a fresh layer stack (unsaved changes are lost).")
            if imgui.button("Create", V2(120, 0)):
                res = RESOLUTIONS[self.new_res_idx]
                if from_file:
                    path = self.new_path

                    def job():
                        self._new_project(load_mesh(path), res)
                    self._run_busy(f"Loading {os.path.basename(path)}...", job)
                else:
                    name = names[self.new_mesh_idx]
                    self._run_busy(f"Baking {name}...", lambda: self._new_project(name, res))
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", V2(120, 0)):
                imgui.close_current_popup()
            imgui.end_popup()

        imgui.set_next_window_pos(center, imgui.Cond_.appearing, V2(0.5, 0.5))
        if imgui.begin_popup_modal("Export Textures", None, auto)[0]:
            _, self.export_preset = imgui.combo("Preset", self.export_preset, EXPORT_PRESETS)
            _, self.export_dir = imgui.input_text("Folder", self.export_dir)
            imgui.same_line()
            if imgui.button("Browse") and pfd is not None:
                p = pfd.select_folder("Export folder", self.export_dir).result()
                if p:
                    self.export_dir = p
            if imgui.button("Export", V2(120, 0)):
                try:
                    files = export(self.engine, self.export_dir, self.export_preset)
                    self.msg(f"Exported {len(files)} maps to {self.export_dir}")
                except Exception as e:
                    traceback.print_exc()
                    self.msg(f"Export failed: {e}")
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", V2(120, 0)):
                imgui.close_current_popup()
            imgui.end_popup()

        imgui.set_next_window_pos(center, imgui.Cond_.appearing, V2(0.5, 0.5))
        if imgui.begin_popup_modal("Controls", None, auto)[0]:
            rows = [
                ("Paint", "Left mouse"), ("Orbit", "Alt+Left drag  or  Right drag"),
                ("Pan", "Middle drag"), ("Zoom", "Wheel  or  Alt+Right drag"),
                ("Brush size", "[  ]  or  Ctrl+Wheel"), ("Toggle eraser", "E"),
                ("Paint layer / mask", "M"), ("Swap mask white/black", "X"),
                ("Cycle display channel", "C"), ("Frame mesh", "F"),
                ("Undo / Redo", "Ctrl+Z / Ctrl+Y"), ("Save / Open", "Ctrl+S / Ctrl+O"),
                ("Export textures", "Ctrl+E"), ("Delete layer", "Delete"),
                ("Open file", "Drag .obj/.fbx/.strata onto the window"),
            ]
            if imgui.begin_table("keys", 2):
                for a, b in rows:
                    imgui.table_next_row()
                    imgui.table_next_column(); imgui.text(a)
                    imgui.table_next_column(); imgui.text_disabled(b)
                imgui.end_table()
            if imgui.button("Close", V2(120, 0)):
                imgui.close_current_popup()
            imgui.end_popup()


def main():
    app = App()
    if len(sys.argv) > 1 and sys.argv[1].endswith(".strata"):
        path = sys.argv[1]
        app._run_busy("Opening project...", lambda: app._open(path))
    app.run()


if __name__ == "__main__":
    main()
