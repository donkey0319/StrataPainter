"""Drive the real window through the main UI states and save a screenshot of each.

    xvfb-run -s "-screen 0 1600x960x24" python tests/ui_tour.py out_dir [scenario ...] [--size 1280x720] [--scale 1.5]

Scenarios: default fill_multi mask_split palette panels export quick hidden painter
Uses a throwaway settings folder, so your own layout is not touched.
"""
import os
import sys
import tempfile

os.environ["HOME"] = os.environ["USERPROFILE"] = tempfile.mkdtemp(prefix="strata_tour_")

import glfw  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strata import app as A  # noqa: E402

args = sys.argv[1:]
OUT = args.pop(0) if args else "ui_tour"
size, scale = (1600, 960), None
if "--size" in args:
    i = args.index("--size"); size = tuple(int(v) for v in args[i + 1].split("x")); del args[i:i + 2]
if "--scale" in args:
    i = args.index("--scale"); scale = float(args[i + 1]); del args[i:i + 2]
SCENARIOS = args or ["default", "fill_multi", "mask_split", "palette", "panels", "export", "quick", "hidden", "painter", "polyfill"]
os.makedirs(OUT, exist_ok=True)


class Tour(A.App):
    def __init__(self, scenario):
        self.scenario, self.n = scenario, 0
        super().__init__(*size)
        if scale:
            self._set_ui_scale(scale, save=False)
        self._run_busy("Baking...", lambda: self._new_project("Rounded Cube", 512))

    def frame(self):
        super().frame()
        if self.engine.comp is None or self.pending:
            return                          # count frames from when the project is ready
        self.n += 1
        e, sc = self.engine, self.scenario
        if self.n == 2:
            e.add_smart_material("Worn Orange Paint on Iron")
            e.camera.yaw, e.camera.pitch = 0.75, 0.45
        if self.n == 4:
            names = [l.name for l in e.layers]
            if sc == "fill_multi":
                e.selected = names.index("Orange Paint")
                self._sync_selection()
                self.sel_uids.add(e.layers[names.index("Grime")].uid)
            elif sc == "mask_split":
                e.selected = names.index("Grime")
                e.brush.target = 1
                e.renderer.mode, e.dirty = 6, True
                self.view_mode = A.VIEW_SPLIT
            elif sc == "palette":
                self.palette.request()
            elif sc == "panels":
                for w in (A.W_DISPLAY, A.W_HISTORY, A.W_KEYS):
                    self.show[w] = True
            elif sc == "export":
                self.open_export = True
            elif sc == "quick":
                self.quick_open = True
            elif sc == "hidden":
                self.ui_hidden = True
            elif sc == "polyfill":
                self._set_tool(A.TOOL_FILL)
                self.fill_mode = 1
                self.view_mode, self.split_frac = A.VIEW_SPLIT, 0.62
                e.camera.yaw, e.camera.pitch = 0.6, 0.5
                A.imgui.get_io().add_mouse_pos_event(self.vp_rect[0] + self.vp_rect[2] * 0.42,
                                                   self.vp_rect[1] + self.vp_rect[3] * 0.38)
            elif sc == "painter":
                import tempfile as tf
                path = os.path.join(tf.mkdtemp(), "stencil.png")
                yy, xx = np.mgrid[0:256, 0:256]
                Image.fromarray((((xx // 32 + yy // 32) % 2) * 255).astype("uint8")).save(path)
                e.brush.stencil, e.brush.stencil_xform = path, [0.45, 0.55, 0.6, 20.0]
                e.brush.symmetry, e.brush.lazy = 1, 25.0
                grime = e.layers[names.index("Grime")]
                orange = e.layers[names.index("Orange Paint")]
                e.group_layers([orange, grime], "Paint wear")
                e.select(grime)
        if self.n == 5 and sc == "palette":
            self.palette.query = "mask"
        if self.n == 10:
            self.snap(f"{sc}{'_' + str(scale) if scale else ''}{'_%dx%d' % size if size != (1600, 960) else ''}.png")
            glfw.set_window_should_close(self.window, True)

    def snap(self, name):
        fw, fh = glfw.get_framebuffer_size(self.window)
        data = self.ctx.screen.read(components=3, viewport=(0, 0, fw, fh))
        img = np.frombuffer(data, np.uint8).reshape(fh, fw, 3)[::-1]
        Image.fromarray(img).save(os.path.join(OUT, name))
        print("saved", name)


for sc in SCENARIOS:
    Tour(sc).run()
