"""Drive the real window through the Substance Painter import features and screenshot each step.

    xvfb-run -s "-screen 0 1600x960x24" python tests/substance_ui_check.py out_dir FOLDER_WITH_SPSM [project.spp]

On Windows (no Xvfb needed) Painter's own folders are found automatically:
    python tests/substance_ui_check.py out_dir

Checks: Assets > Substance lists smart materials and masks with thumbnails; double-click adds a smart
material; a smart mask applies to the selected layer; a .spp opens the texture-set dialog, imports,
and shows the report. Uses a throwaway settings folder.
"""
import os
import sys
import tempfile

os.environ["HOME"] = os.environ["USERPROFILE"] = tempfile.mkdtemp(prefix="strata_sp_")

import glfw  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strata import app as A  # noqa: E402

args = sys.argv[1:]
OUT = args.pop(0) if args else "ui_out"
FOLDER = args.pop(0) if args else ""
SPP = args.pop(0) if args else ""
os.makedirs(OUT, exist_ok=True)
fails = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


class Check(A.App):
    def __init__(self):
        self.n = 0
        A.App._load_settings_orig = A.App._load_settings
        super().__init__(1600, 960)
        if FOLDER:
            self.settings["substance_folders"] = [FOLDER]
            self._scan_substance()
        self._run_busy("Baking...", lambda: self._new_project("Rounded Cube", 512))

    def frame(self):
        super().frame()
        if self.engine.comp is None or self.pending:
            return
        self.n += 1
        e = self.engine
        mats = [i for i in self.sp_items if i.kind == "smart_material"]
        masks = [i for i in self.sp_items if i.kind == "smart_mask"]
        if self.n == 2:
            check(len(mats) > 0, f"Substance smart materials found ({len(mats)})")
            self.asset_tab_request = "substance"
            self.asset_query = "dirt"           # brings a tile with an embedded preview into view
            e.camera.yaw, e.camera.pitch = 0.75, 0.45
        if self.n == 40:                       # give the worker time to decode thumbnails
            check(any(t is not None for t in self.sp_thumbs.values()),
                  f"thumbnails decoded ({sum(t is not None for t in self.sp_thumbs.values())} of {len(self.sp_thumbs)} requested)")
            self.snap("sp_assets.png")
            self.asset_query = ""
        if self.n == 41 and mats:
            pick = next((m for m in mats if "Steel Painted Worn" in m.name), mats[0])
            before = len(e.layers)
            self._add_sp_smart(pick.path)
            check(len(e.layers) > before, f"smart material '{pick.name}' adds {len(e.layers) - before} layers")
            e.undo()
            check(len(e.layers) == before, "one undo step removes it")
            e.redo()
        if self.n == 44:
            self.snap("sp_added.png")
        if self.n == 45 and masks:
            e.selected = len(e.layers) - 1
            self.sp_kind = 1
            self._apply_sp_mask(masks[0].path)
            check(e.layer.gen.kind != 0 or e.layer.has_mask, f"smart mask '{masks[0].name}' drives the layer mask")
        if self.n == 48 and masks:
            self.snap("sp_masks.png")
        if self.n == 49:
            if SPP:
                self._begin_spp(SPP)
                check(self.spp_info is not None, "project inspected")
            else:
                glfw.set_window_should_close(self.window, True)
        if self.n == 52 and SPP:
            self.snap("spp_dialog.png")
            self._import_spp(self.spp_info, self.spp_set)
            A.imgui.close_current_popup() if False else None
        if self.n == 56 and SPP:
            check(self.report is not None, "import report shown")
            check(len(e.layers) > 0 and e.mesh.name.startswith(os.path.splitext(os.path.basename(SPP))[0]),
                  f"project imported: {len(e.layers)} layers on '{e.mesh.name}'")
            e.camera.yaw, e.camera.pitch = 0.6, 0.35
            e.camera.frame(e.mesh.center, e.mesh.radius)
        if self.n == 60 and SPP:
            self.snap("spp_report.png")
            self.report_seen = True
        if self.n == 62 and SPP:
            glfw.set_window_should_close(self.window, True)

    def snap(self, name):
        fw, fh = glfw.get_framebuffer_size(self.window)
        data = self.ctx.screen.read(components=3, viewport=(0, 0, fw, fh))
        Image.fromarray(np.frombuffer(data, np.uint8).reshape(fh, fw, 3)[::-1]).save(os.path.join(OUT, name))
        print("saved", name)


Check().run()
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
