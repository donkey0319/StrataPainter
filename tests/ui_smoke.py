"""Open the real window (e.g. under Xvfb), drive a few actions, save screenshots, exit.

    xvfb-run -s "-screen 0 1600x960x24" python tests/ui_smoke.py out_dir
"""
import os
import sys

import glfw
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strata.app import App  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "ui_out"
os.makedirs(OUT, exist_ok=True)


class Smoke(App):
    n = 0

    def frame(self):
        super().frame()
        self.n += 1
        e = self.engine
        if self.n == 8 and e.comp is not None:
            e.add_smart_material("Worn Orange Paint on Iron")
            e.camera.yaw, e.camera.pitch = 0.75, 0.45
        if self.n == 12:
            self.snap("ui_1.png")
            # programmatic stroke through the viewport centre
            vx, vy, vw, vh = self.vp_rect
            pts = [(vx + vw * (0.3 + 0.4 * t), vy + vh * (0.35 + 0.3 * t)) for t in np.linspace(0, 1, 30)]
            sx, sy = self.fb_scale
            e.brush.size_px, e.brush.color = 30, [0.1, 0.8, 0.9]
            started = False
            for (x, y) in pts:
                hit = e.pick((x - vx) * sx, (vy + vh - y) * sy)
                if hit is None:
                    continue
                if not started:
                    started = e.begin_stroke(hit[0])
                else:
                    e.stroke_to(hit[0])
            e.end_stroke()
            print("stroke:", started)
        if self.n == 16:
            self.snap("ui_2.png")
            self.open_help = True
        if self.n == 20:
            self.snap("ui_help.png")
            glfw.set_window_should_close(self.window, True)

    def snap(self, name):
        fw, fh = glfw.get_framebuffer_size(self.window)
        data = self.ctx.screen.read(components=3, viewport=(0, 0, fw, fh))
        img = np.frombuffer(data, np.uint8).reshape(fh, fw, 3)[::-1]
        Image.fromarray(img).save(os.path.join(OUT, name))
        print("saved", name)


Smoke().run()
