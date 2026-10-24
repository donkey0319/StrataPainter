"""Exercise the engine without a window: bake, layer, paint, composite, render, export, save/load.

Run:  python tests/headless_check.py  [out_dir]
"""
import os
import sys
import time

import moderngl
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strata.engine import Engine          # noqa: E402
from strata.exporter import export        # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "headless_out"
os.makedirs(OUT, exist_ok=True)
W, H = 900, 700

ctx = moderngl.create_standalone_context(backend="egl", require=330) if sys.platform.startswith("linux") \
    else moderngl.create_standalone_context(require=330)
eng = Engine(ctx)
screen_c = ctx.texture((W, H), 4)
screen = ctx.framebuffer([screen_c], ctx.depth_renderbuffer((W, H)))


def shot(name):
    eng.update_view(W, H)
    screen.use()
    eng.render((0, 0, W, H))
    img = np.frombuffer(screen.read(components=3), np.uint8).reshape(H, W, 3)[::-1]
    Image.fromarray(img).save(os.path.join(OUT, name))
    return img


def paint_line(x0, y0, x1, y1, n=40):
    eng.update_view(W, H)
    started = False
    for t in np.linspace(0, 1, n):
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        hit = eng.pick(x, H - 1 - y)
        if hit is None:
            continue
        if not started:
            started = eng.begin_stroke(hit[0])
        else:
            eng.stroke_to(hit[0])
    eng.end_stroke()
    return started


for mesh in ["Rounded Cube", "Canister"]:
    t = time.time()
    eng.new_project(mesh, res=1024, ao_samples=64)
    ctx.finish()
    print(f"{mesh}: baked in {time.time() - t:.1f}s")
    eng.add_smart_material("Worn Blue Paint on Steel")
    eng.brush.size_px = 40
    eng.brush.color = [0.95, 0.75, 0.1]
    eng.brush.enabled = [True, True, False, True]
    eng.brush.height = 0.8
    ok = paint_line(250, 250, 650, 450)
    print("  stroke landed:", ok, "layers:", [l.name for l in eng.layers])
    tag = mesh.replace(" ", "_")
    shot(f"{tag}_material.png")
    for mode, nm in [(1, "basecolor"), (5, "normal"), (7, "ao")]:
        eng.renderer.mode = mode
        shot(f"{tag}_{nm}.png")
    eng.renderer.mode = 0

# undo / redo
before = shot("before_undo.png")
eng.undo()
after = shot("after_undo.png")
eng.redo()
redone = shot("after_redo.png")
print("undo changes image:", np.abs(before.astype(int) - after).mean() > 0.1,
      "| redo restores:", np.abs(before.astype(int) - redone).mean() < 0.5)

files = export(eng, os.path.join(OUT, "export_unreal"), preset=0)
print("exported:", [os.path.basename(f) for f in files])
eng.save(os.path.join(OUT, "test.strata"))
eng.load(os.path.join(OUT, "test.strata"))
reload = shot("after_reload.png")
print("save/load roundtrip diff:", round(float(np.abs(before.astype(int) - reload).mean()), 3))
