"""Read and convert every Substance Painter file we can find, and optionally render some of them.

    python tests/substance_check.py                       # Painter's starter assets + your shelf
    python tests/substance_check.py PATH [PATH ...]       # files or folders (.spsm .spmsk .spp)
    python tests/substance_check.py --render out_dir ...  # also import on the GPU and save renders

Prints one line per file (layers, approximations, errors) and a summary. Exits 1 on any error.
"""
import glob
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strata.layers import GENERATORS                       # noqa: E402
from strata.substance import importer, library            # noqa: E402

args = sys.argv[1:]
render_dir = None
if "--render" in args:
    i = args.index("--render")
    render_dir = args[i + 1]
    del args[i:i + 2]

files = []
if args:
    for a in args:
        if os.path.isdir(a):
            for ext in importer.ALL_EXTS:
                files += glob.glob(os.path.join(a, "**", "*" + ext), recursive=True)
        else:
            files.append(a)
else:
    items, roots = library.scan()
    files = [i.path for i in items]
    for r in roots:
        files += glob.glob(os.path.join(os.path.dirname(r), "samples", "*.spp"))
    print(f"Painter folders: {roots or 'none found'}")
files = sorted(set(files))
if not files:
    print("No Substance files found. Pass a folder or file.")
    sys.exit(0)

errors, t0 = [], time.time()
stats = {"smart_material": 0, "smart_mask": 0, "project": 0}
loaded = []
for f in files:
    kind = importer.kind_of(f)
    name = os.path.basename(f)
    try:
        if kind == "smart_material":
            r = importer.load_smart_material(f)
            all_il = [x for il in r.layers for x in il.walk()]
            fx = sorted({e.kind if e.kind != "generator" else GENERATORS[e.params["gen"].kind]
                         for x in all_il for e in x.layer.mask_effects})
            print(f"ok   {name}: {len(all_il)} layers, {len(r.notes)} notes  [{', '.join(fx)}]")
            loaded.append((kind, f, r))
        elif kind == "smart_mask":
            m = importer.load_smart_mask(f)
            fx = [e.kind for e in m.mask.effects] if m.mask is not None else []
            print(f"ok   {name}: mask -> {len(fx)} effects ({', '.join(sorted(set(fx))) or 'none'})")
        elif kind == "project":
            info = importer.inspect_project(f)
            sets = ", ".join(f"{t.name} ({t.resolution}px, {t.layer_count} layers, {t.stroke_count} strokes)"
                             for t in info.texture_sets)
            p = importer.load_project(f, 0)
            nl = sum(1 for si in p.sets for il in si.result.layers for _ in il.walk())
            print(f"ok   {name}: Painter {info.version}; {sets}; {len(p.sets)} sets -> {nl} layers, "
                  f"{len(p.mesh.positions)} vertices")
            loaded.append((kind, f, p))
        else:
            continue
        stats[kind] += 1
    except Exception as e:
        errors.append((f, e))
        print(f"FAIL {name}: {e}")
        traceback.print_exc()

print(f"\n{stats['smart_material']} smart materials, {stats['smart_mask']} smart masks, "
      f"{stats['project']} projects in {time.time() - t0:.1f}s; {len(errors)} error(s)")

if render_dir and loaded:
    import moderngl
    import numpy as np
    from PIL import Image
    from strata.engine import Engine
    os.makedirs(render_dir, exist_ok=True)
    ctx = moderngl.create_standalone_context(backend="egl", require=330) if sys.platform.startswith("linux") \
        else moderngl.create_standalone_context(require=330)
    eng = Engine(ctx)
    W = H = 512
    fbo = ctx.framebuffer([ctx.texture((W, H), 4)], ctx.depth_renderbuffer((W, H)))

    def snap(path):
        eng.update_view(W, H)
        fbo.use()
        eng.render((0, 0, W, H))
        Image.fromarray(np.frombuffer(fbo.read(components=3), np.uint8).reshape(H, W, 3)[::-1]).save(path)

    mats = [x for x in loaded if x[0] == "smart_material"][:12]
    if mats:
        eng.new_project("Rounded Cube", res=1024, ao_samples=48, with_default_layer=False)
        eng.camera.yaw, eng.camera.pitch = 0.75, 0.45
        for _, f, r in mats:
            eng.layers, eng.selected = [], -1
            eng.add_imported(r)
            snap(os.path.join(render_dir, os.path.splitext(os.path.basename(f))[0] + ".png"))
    for _, f, p in [x for x in loaded if x[0] == "project"][:3]:
        t = time.time()
        dabs = eng.import_painter_project(p, ao_samples=48)
        eng.camera.yaw, eng.camera.pitch = 0.6, 0.35
        snap(os.path.join(render_dir, os.path.splitext(os.path.basename(f))[0] + ".png"))
        print(f"rendered {os.path.basename(f)}: {dabs} dabs replayed in {time.time() - t:.1f}s")
    print(f"renders in {render_dir}")

sys.exit(1 if errors else 0)
