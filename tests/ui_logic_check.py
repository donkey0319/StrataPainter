"""Exercise the UI's actions and input handling in the real window and check the results.

    xvfb-run -s "-screen 0 1600x960x24" python tests/ui_logic_check.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = os.environ["USERPROFILE"] = tempfile.mkdtemp(prefix="strata_logic_")

import glfw  # noqa: E402
from imgui_bundle import imgui  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strata import app as A  # noqa: E402

K = imgui.Key
fails = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


class Logic(A.App):
    def __init__(self):
        self.n, self.script = 0, []
        super().__init__(1600, 960)
        self._run_busy("Baking...", lambda: self._new_project("Rounded Cube", 512))
        self.steps = self.build()

    # input helpers: queued before the next imgui.new_frame()
    def key(self, k, mods=()):
        io = imgui.get_io()
        for m in mods:
            io.add_key_event(m, True)
        io.add_key_event(k, True)
        self.later(lambda: (io.add_key_event(k, False), [io.add_key_event(m, False) for m in mods]))

    def later(self, fn):
        self.script.append(fn)

    def mouse(self, x, y, button=None, down=None):
        io = imgui.get_io()
        io.add_mouse_pos_event(x, y)
        if button is not None:
            io.add_mouse_button_event(button, down)

    def frame(self):
        while self.script:
            self.script.pop(0)()
        if self.engine.comp is not None and not self.pending:
            step = self.steps.pop(0) if self.steps else None
            if step is None:
                glfw.set_window_should_close(self.window, True)
            else:
                step()
        super().frame()

    def build(self):
        e = self.engine
        vx = lambda: self.vp_rect[0] + self.vp_rect[2] * 0.5
        vy = lambda: self.vp_rect[1] + self.vp_rect[3] * 0.5
        S = []
        S += [lambda: None] * 3

        # every command a menu, button or shortcut list names must be registered
        def names_exist():
            import re
            src = open(A.__file__, encoding="utf-8").read()
            ids = set(re.findall(r'_menu_cmd\(\s*"([\w.]+)"', src))
            ids |= set(re.findall(r'_cmd_btn\([^\n]*?"([a-z_]+\.[\w.]+)"', src))
            for tup in re.findall(r'for cid in \(([^)]*)\)', src):
                ids |= set(re.findall(r'"([\w.]+)"', tup))
            missing = sorted(i for i in ids if i not in self.reg.cmds and not i.endswith("."))   # "win." + name etc.
            check(not missing, f"all {len(ids)} commands used by menus and buttons exist" + (f" (missing {missing})" if missing else ""))
        S += [names_exist]
        # keyboard shortcuts through the registry
        S += [lambda: self.key(K._2), lambda: None, lambda: check(e.brush.mode == 1, "key 2 selects Eraser")]
        S += [lambda: self.key(K._1), lambda: None, lambda: check(e.brush.mode == 0, "key 1 selects Paint")]
        r = e.renderer
        S += [lambda: self.key(K.c), lambda: None, lambda: check(r.mode == 1, "C shows the next channel (Base Color)")]
        S += [lambda: self.key(K.c, (K.mod_shift,)), lambda: None,
              lambda: check(r.mode == 11, "Shift+C shows the previous channel (wraps to Opacity)")]
        S += [lambda: self.key(K.m), lambda: None, lambda: check(r.mode == 0, "M shows the material")]
        S += [lambda: self.key(K.b), lambda: None, lambda: check(r.mode == 7, "B shows the next mesh map (AO)")]
        S += [lambda: self.key(K.b, (K.mod_shift,)), lambda: None,
              lambda: check(r.mode == 15, "Shift+B shows the previous mesh map")]
        S += [lambda: self.key(K.m), lambda: None]
        for key, tool, mode, name in ((K._3, A.TOOL_PROJECTION, 0, "3 selects Projection"),
                                      (K._5, A.TOOL_SMUDGE, 0, "5 selects Smudge"),
                                      (K._6, A.TOOL_CLONE, 0, "6 selects Clone")):
            S += [lambda key=key: self.key(key), lambda: None,
                  lambda tool=tool, name=name: check(self._tool_is(tool), name)]
        S += [lambda: self.key(K._6, (K.mod_ctrl,)), lambda: None,
              lambda: check(self._tool_is(A.TOOL_CLONE) and self.clone_absolute, "Ctrl+6 selects Clone (absolute)")]
        S += [lambda: self.key(K._4), lambda: None, lambda: check(self.poly_fill, "4 selects Polygon fill")]
        S += [lambda: self.key(K._1), lambda: None,
              lambda: check(self._tool_is(A.TOOL_PAINT, 0) and not self.poly_fill, "1 goes back to Paint")]
        S += [lambda: self.key(K.l), lambda: None, lambda: check(e.brush.symmetry == 1, "L turns symmetry on"),
              lambda: self.key(K.l), lambda: None, lambda: check(e.brush.symmetry == 0, "L turns it off")]
        S += [lambda: self.key(K.d), lambda: None, lambda: check(e.brush.lazy > 0, "D turns lazy mouse on"),
              lambda: self.key(K.d), lambda: None, lambda: check(e.brush.lazy == 0, "D turns it off")]
        S += [lambda: self.key(K.f5), lambda: None, lambda: self.key(K.f6), lambda: None,
              lambda: check(e.camera.ortho, "F6 orthographic camera"),
              lambda: self.key(K.f5), lambda: None, lambda: check(not e.camera.ortho, "F5 perspective camera")]
        S += [lambda: self.key(K.escape, (K.mod_shift,)), lambda: None, lambda: check(self.paused, "Shift+Esc pauses"),
              lambda: self.key(K.escape, (K.mod_shift,)), lambda: None, lambda: check(not self.paused, "and resumes")]
        S += [lambda: self.key(K.q, (K.mod_alt,)), lambda: None,
              lambda: check(not self.isolate and "single texture set" in self.status, "Alt+Q explains a single set")]
        S += [lambda: self.key(K.w), lambda: None,
              lambda: check("manipulator" in self.status, "W (manipulator) explains it isn't available")]
        # quick mask U / I / Y
        def qvals():
            q = e.ts.quick
            return float(e.gpu.read(q).mean()) if q is not None else None
        S += [lambda: self.key(K.u), lambda: None,
              lambda: check(self.quick_edit and e.brush.target == 2, "U starts editing the quick mask"),
              lambda: self.key(K.i), lambda: None, lambda: check(qvals() < 0.01, "I inverts the quick mask"),
              lambda: self.key(K.y), lambda: None, lambda: check(qvals() > 0.99, "Y clears it"),
              lambda: self.key(K.u), lambda: None,
              lambda: check(not self.quick_edit and e.quick_mask_enabled and e.brush.target == 0,
                            "U applies it and returns to the layer"),
              lambda: setattr(e, "quick_mask_enabled", False)]
        S += [lambda: self.key(K.f1), lambda: None, lambda: check(self.view_mode == A.VIEW_SPLIT, "F1 = 3D + 2D")]
        S += [lambda: self.key(K.f2), lambda: None, lambda: check(self.view_mode == A.VIEW_3D, "F2 = 3D only")]
        S += [lambda: self.key(K.tab), lambda: None, lambda: check(self.ui_hidden, "Tab hides panels")]
        S += [lambda: self.key(K.tab), lambda: None, lambda: check(not self.ui_hidden, "Tab shows panels")]
        n0 = {}
        S += [lambda: n0.setdefault("n", len(e.layers)), lambda: self.key(K.d, (K.mod_ctrl,)), lambda: None,
              lambda: check(len(e.layers) == n0["n"] + 1, "Ctrl+D duplicates the layer")]
        S += [lambda: self.key(K.z, (K.mod_ctrl,)), lambda: None,
              lambda: check(len(e.layers) == n0["n"], "Ctrl+Z undoes it")]
        S += [lambda: self.key(K.k, (K.mod_ctrl,)), lambda: None,
              lambda: check(self.palette.is_open, "Ctrl+K opens the command palette")]
        S += [lambda: self.key(K.escape), lambda: None, lambda: None,
              lambda: check(not self.palette.is_open, "Esc closes it")]
        # registry run (as the palette / menus do)
        S += [lambda: self.reg.run("smart.Rusty Iron"), lambda: check("Rust" in [l.name for l in e.layers],
                                                                       "palette command adds a smart material")]
        # materials: click on fill vs paint
        def mat_on_fill():
            e.select(e.layers[[l.name for l in e.layers].index("Iron base")])
            self._sync_selection()
            e.brush.target = 0
            self._use_material("Gold")
            check(list(e.layer.color) == list(A.MATERIALS["Gold"][0]), "material click sets the selected fill layer")
        S += [mat_on_fill]
        # drag-drop equivalents: asset dropped above a row, layer moved
        def drop_mat():
            n = len(e.layers)
            self._add_fill_material("Copper", index=1)
            check(len(e.layers) == n + 1 and e.layers[1].name == "Copper", "dropping a material inserts a fill layer there")
        S += [drop_mat]
        def move():
            top = e.layers[-1]
            self._drop_layer_on(top, None)
            check(e.layers[0] is top and e.layer is top, "dragging a layer moves it")
            self.key(K.z, (K.mod_ctrl,))
        S += [move, lambda: None, lambda: check(e.layers[-1].name == "Paint layer", "and Ctrl+Z puts it back")]
        # multi-select + shared edit + multi delete
        def multi():
            e.select(e.layers[0])
            self._sync_selection()
            self.sel_uids = {e.layers[0].uid, e.layers[1].uid}
            for l in self._sel_layers():
                l.opacity = 0.5
            check(all(l.opacity == 0.5 for l in e.layers[:2]), "multi-selection edits apply to all selected")
            n = len(e.layers)
            self._delete_selected()
            check(len(e.layers) == n - 2, "Delete removes every selected layer")
            e.undo()
            check(len(e.layers) == n, "in one undo step")
        S += [multi, lambda: None]
        # generator from Assets onto a layer
        def gen():
            self._apply_generator(1, layer=e.layers[0])
            check(e.layers[0].gen.kind == 1, "dropping a generator on a layer sets its mask generator")
        S += [gen]
        # viewport mouse: Ctrl+RMB drag changes size; RMB click opens quick brush
        size0 = {}
        S += [lambda: self.mouse(vx(), vy()), lambda: None,
              lambda: (size0.update(s=self.bsize.value, upp=self._size_units_per_px()),
                       imgui.get_io().add_key_event(K.mod_ctrl, True), self.mouse(vx(), vy(), 1, True)),
              lambda: self.mouse(vx() + 40, vy()), lambda: None,
              lambda: (self.mouse(vx() + 40, vy(), 1, False), imgui.get_io().add_key_event(K.mod_ctrl, False)),
              lambda: None,
              lambda: check(e.brush.size_space == 1 and abs(self.bsize.value - size0["s"] - 40 * size0["upp"]) < 1e-3
                            * max(size0["s"], 1), "Ctrl+Right drag grows the (world-size) brush by 40 px on screen"),
              lambda: self.mouse(vx() + 20, vy() + 10), lambda: None, lambda: None,
              lambda: check(self.cursor is not None and self._cur_cursor == imgui.MouseCursor_.none,
                            "the system cursor hides over the mesh (the brush circle shows)")]
        # world size: zooming out keeps the brush the same size on the mesh
        def zoom_world():
            hit = self.cursor[0]
            r0 = e.brush_radius(hit)
            e.camera.zoom(-3)
            check(abs(e.brush_radius(hit) - r0) < 1e-9, "world-size brush stays the same size on the mesh when zooming")
            e.camera.zoom(3)
        S += [zoom_world]
        # switching size space keeps the on-screen size
        def space_switch():
            hit = self.cursor[0]
            r0 = e.brush_radius(hit)
            self._set_size_space(0)
            r_screen = e.brush_radius(hit)
            self._set_size_space(1)
            check(abs(r_screen - r0) < r0 * 0.01 and abs(e.brush_radius(hit) - r0) < r0 * 0.01,
                  "switching World / Screen size keeps the circle's size")
        S += [space_switch]
        S += [lambda: self.mouse(vx(), vy(), 1, True), lambda: None, lambda: self.mouse(vx(), vy(), 1, False),
              lambda: None, lambda: None,
              lambda: check(self.quick_is_open, "Right click opens the quick brush menu"),
              lambda: self.key(K.escape), lambda: None, lambda: None,
              lambda: check(not self.quick_is_open, "Esc closes the quick brush menu")]
        # painting with the mouse still works
        def paint_setup():
            e.select(e.layers[-1])
            self._sync_selection()
            e.brush.target, e.brush.mode = 0, 0
            check(e.layer.kind == "paint", "top layer is a paint layer")
            n0["u"] = len(e.undo_stack)
            self.mouse(vx() - 30, vy(), 0, True)
        S += [paint_setup, lambda: self.mouse(vx(), vy() + 10), lambda: self.mouse(vx() + 30, vy() + 20),
              lambda: self.mouse(vx() + 30, vy() + 20, 0, False), lambda: None,
              lambda: check(len(e.undo_stack) == n0["u"] + 1, "Left drag paints a stroke (one undo step)")]
        # Shift+click: straight line from the end of the last stroke; Ctrl+Shift+click snapped
        S += [lambda: n0.__setitem__("u", len(e.undo_stack)),
              lambda: (imgui.get_io().add_key_event(K.mod_shift, True), self.mouse(vx() - 60, vy() + 40, 0, True)),
              lambda: None, lambda: (self.mouse(vx() - 60, vy() + 40, 0, False), imgui.get_io().add_key_event(K.mod_shift, False)),
              lambda: None,
              lambda: check(len(e.undo_stack) == n0["u"] + 1, "Shift+click paints a straight line")]
        # P picks the material under the cursor
        S += [lambda: setattr(e.brush, "color", [0.0, 0.0, 1.0]), lambda: self.mouse(vx() + 60, vy() - 40), lambda: None,
              lambda: self.key(K.p), lambda: None,
              lambda: check(list(e.brush.color) != [0.0, 0.0, 1.0], "P picks the material under the cursor")]
        # Alt+Shift+Left drag snaps the camera to 90 degrees
        S += [lambda: (imgui.get_io().add_key_event(K.mod_alt, True), imgui.get_io().add_key_event(K.mod_shift, True),
                       self.mouse(vx(), vy(), 0, True)),
              lambda: self.mouse(vx() + 150, vy() + 20), lambda: None,
              lambda: (self.mouse(vx() + 150, vy() + 20, 0, False), imgui.get_io().add_key_event(K.mod_alt, False),
                       imgui.get_io().add_key_event(K.mod_shift, False)), lambda: None,
              lambda: check(abs((e.camera.yaw / (3.14159265 / 2)) - round(e.camera.yaw / (3.14159265 / 2))) < 1e-6,
                            "Alt+Shift+Left drag snaps the orbit to 90 degrees")]
        S += [lambda: (imgui.get_io().add_key_event(K.mod_alt, True), imgui.get_io().add_key_event(K.mod_shift, True),
                       self.mouse(vx(), vy(), 0, True)),
              lambda: self.mouse(vx(), vy() + 300), lambda: None,
              lambda: (self.mouse(vx(), vy() + 300, 0, False), imgui.get_io().add_key_event(K.mod_alt, False),
                       imgui.get_io().add_key_event(K.mod_shift, False)), lambda: None,
              lambda: check(self._axis_view_name() == "Top", "Alt+Shift+Left drag reaches the exact top view")]

        # axis gizmo: click the +X end to look from the right
        def gizmo_at(axis):
            g = next(t for t in (self._gizmo or []) if t[0] == axis)
            return g[1], g[2]
        S += [lambda: self.mouse(*gizmo_at("+x")), lambda: None,
              lambda: self.mouse(*gizmo_at("+x"), 0, True), lambda: self.mouse(*gizmo_at("+x"), 0, False), lambda: None,
              lambda: check(self._axis_view_name() == "Right", "clicking the gizmo's X views from the right"),
              lambda: self.mouse(*gizmo_at("-y")), lambda: None,
              lambda: self.mouse(*gizmo_at("-y"), 0, True), lambda: self.mouse(*gizmo_at("-y"), 0, False), lambda: None,
              lambda: check(self._axis_view_name() == "Bottom", "clicking the gizmo's -Y views from below"),
              lambda: setattr(e.camera, "pitch", 0.4)]

        # 3D / 2D divider drag
        def split_x():
            return self._split_hit[0], self._split_hit[1] + 200
        S += [lambda: self.key(K.f1), lambda: None, lambda: None,
              lambda: self.mouse(*split_x()), lambda: None,
              lambda: self.mouse(*split_x(), 0, True), lambda: None,
              lambda: self.mouse(split_x()[0] - 250, split_x()[1]), lambda: None,
              lambda: self.mouse(split_x()[0], split_x()[1], 0, False), lambda: None,
              lambda: check(self.split_frac < 0.45 and self.vp_rect[2] < self.uv_rect[2],
                            f"dragging the divider resizes the views ({self.split_frac:.2f})"),
              lambda: self.mouse(*split_x()), lambda: None, lambda: None,
              lambda: check(self._cur_cursor == imgui.MouseCursor_.resize_ew
                            and self._glfw_cursors.get("resize_ew") is not None,
                            "hovering the divider shows the left-right resize cursor"),
              lambda: self.mouse(self.vp_rect[0] - 1, self.vp_rect[1] + 300), lambda: None, lambda: None,
              lambda: check(self._cur_cursor == imgui.MouseCursor_.resize_ew,
                            "hovering a panel splitter shows the resize cursor"),
              lambda: self.mouse(self.vp_rect[0] + 12, self.vp_rect[1] + self.vp_rect[3] - 12), lambda: None, lambda: None,
              lambda: check(self._cur_cursor == imgui.MouseCursor_.arrow, "off the mesh the cursor goes back to the arrow"),
              lambda: self.key(K.f2), lambda: None]

        # polygon fill shows the wireframe and the face under the cursor
        S += [lambda: self.key(K._4), lambda: self.mouse(vx() + 30, vy() + 30), lambda: None, lambda: None,
              lambda: check(bool(e.renderer._wire) and e.renderer._wire_hl is not None and e.renderer._wire_hl[3] > 0,
                            "polygon fill draws the wireframe and the hovered face"),
              lambda: self.key(K._1), lambda: None]
        # S + Left drag rotates the stencil
        def stencil():
            import numpy as np
            from PIL import Image
            path = os.path.join(tempfile.mkdtemp(), "stencil.png")
            Image.fromarray((np.random.rand(64, 64) * 255).astype("uint8")).save(path)
            e.brush.stencil, e.brush.stencil_xform = path, [0.5, 0.5, 1.0, 0.0]
        S += [stencil, lambda: (imgui.get_io().add_key_event(K.s, True), self.mouse(vx(), vy(), 0, True)),
              lambda: self.mouse(vx() + 60, vy()), lambda: None,
              lambda: (self.mouse(vx() + 60, vy(), 0, False), imgui.get_io().add_key_event(K.s, False)), lambda: None,
              lambda: check(abs(e.brush.stencil_xform[3] - 30) < 1, "S + Left drag rotates the stencil"),
              lambda: self.key(K.n), lambda: None, lambda: check(not e.brush.stencil_enabled, "N ignores the stencil"),
              lambda: self.key(K.n), lambda: setattr(e.brush, "stencil", None)]
        # V + click sets the clone source
        S += [lambda: (imgui.get_io().add_key_event(K.v, True), self.mouse(vx(), vy(), 0, True)), lambda: None,
              lambda: (self.mouse(vx(), vy(), 0, False), imgui.get_io().add_key_event(K.v, False)), lambda: None,
              lambda: check(e.clone_source is not None, "V + click sets the clone source")]
        # polygon fill click
        S += [lambda: (self.key(K._4), n0.__setitem__("u", len(e.undo_stack))), lambda: None,
              lambda: self.mouse(vx(), vy(), 0, True), lambda: None, lambda: self.mouse(vx(), vy(), 0, False), lambda: None,
              lambda: check(len(e.undo_stack) == n0["u"] + 1, "Polygon fill: a click fills (one undo step)"),
              lambda: self.key(K._1), lambda: None]
        # layer clipboard and folders
        S += [lambda: n0.__setitem__("n", len(e.all_layers())), lambda: self.key(K.c, (K.mod_ctrl,)), lambda: None,
              lambda: self.key(K.v, (K.mod_ctrl,)), lambda: None,
              lambda: check(len(e.all_layers()) == n0["n"] + 1, "Ctrl+C / Ctrl+V copies and pastes a layer")]
        def group():
            e.select(e.layers[0])
            self._sync_selection()
            self.sel_uids = {e.layers[0].uid, e.layers[1].uid}
            n0["top"] = len(e.layers)
        S += [group, lambda: self.key(K.g, (K.mod_ctrl,)), lambda: None,
              lambda: check(len(e.layers) == n0["top"] - 1 and e.layer.is_group and len(e.layer.children) == 2,
                            "Ctrl+G groups the selected layers into a folder"),
              lambda: check(len(self._flat()) == len(e.all_layers()), "the folder's children show in the stack"),
              lambda: self.key(K.z, (K.mod_ctrl,)), lambda: None,
              lambda: check(len(e.layers) == n0["top"], "Ctrl+Z ungroups")]
        def content():
            names = [l.name for l in e.layers]
            e.select(e.layers[names.index("Iron base")])
        S += [content, lambda: self.key(K.c, (K.mod_ctrl, K.mod_shift)), lambda: None,
              lambda: e.select(next(l for l in e.layers if l.kind == "fill" and l.name != "Iron base")),
              lambda: self.key(K.v, (K.mod_ctrl, K.mod_shift)), lambda: None,
              lambda: check(list(e.layer.color) == list(next(l for l in e.layers if l.name == "Iron base").color),
                            "Ctrl+Shift+C / V copies a layer's content")]
        def mask_toggle():
            lay = next(l for l in e.layers if l.gen.kind)
            self._toggle_mask(lay)
            check(not lay.has_mask_stack(), "Shift+click on the mask disables it")
            self._toggle_mask(lay)
            check(lay.has_mask_stack(), "and enables it again")
        S += [mask_toggle]
        S += [lambda: self.key(K.f1), lambda: None, lambda: self.key(K.f4), lambda: None,
              lambda: check(self.view_swap and self.vp_rect[0] > self.uv_rect[0], "F4 swaps the 2D and 3D views"),
              lambda: self.key(K.f4), lambda: self.key(K.f2), lambda: None]
        S += [lambda: self.key(K.b, (K.mod_ctrl, K.mod_shift)), lambda: None, lambda: None,
              lambda: check(self.bake_settings is not None, "Ctrl+Shift+B opens mesh-map baking"),
              lambda: self.key(K.escape), lambda: None, lambda: None]
        # history: jump back to the oldest state
        def hist():
            while e.undo_stack:
                e.undo()
            check(not e.undo_stack and e.redo_stack, "History can step back")
        S += [hist]
        # rebinding a shortcut
        def rebind():
            self.rebind = "tool.erase"
        S += [rebind, lambda: self.key(K.q), lambda: None,
              lambda: check(self.reg.shortcut("tool.erase") == "Q", "shortcut rebinding captures the key"),
              lambda: self.key(K.q), lambda: None, lambda: check(e.brush.mode == 1, "the new key works")]
        # UI scale
        S += [lambda: self._set_ui_scale(1.25), lambda: check(abs(imgui.get_style().font_scale_main - 1.25) < 1e-6,
                                                              "UI scale applies")]
        # reset layout keeps working
        S += [self._reset_layout, lambda: None, lambda: None,
              lambda: check(imgui.internal.dock_builder_get_central_node(self.dock_id) is not None, "layout rebuilt")]
        return S


Logic().run()
print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
