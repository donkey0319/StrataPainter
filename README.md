# Strata

A small 3D texture painter written from scratch in Python + OpenGL. It covers the core
Substance-Painter-style loop: bake mesh maps, stack fill and paint layers with masks and
generators, paint directly on the model in 3D, and export PBR maps for Unreal or Unity.

## Install and launch Strata Painter

Strata currently runs from source. You need **Python 3.10 or newer**, a GPU and driver
that support **OpenGL 3.3**, and an internet connection for the initial dependency install.
Launchers are provided for Windows, macOS and Linux. Windows is the locally verified
platform; the macOS/Linux launchers do not yet have native GPU/UI runtime verification.

Download this repository using **Code > Download ZIP** on GitHub and extract it, or
clone it with Git. Keep the complete folder together, including `run.py`, `strata/`,
and `requirements.txt`. Run the launcher for your operating system below.

### Windows: launch with a double-click

1. Install native Windows Python 3.10+ and enable **Add python.exe to PATH** in the
   installer. Use Windows Python rather than WSL for the desktop app.
2. Open the extracted or cloned folder containing `Strata.bat`, `run.py`, and
   `requirements.txt`.
3. Double-click **`Strata.bat`**. On the first launch, it creates a local `.venv`
   Python environment and installs the dependencies. Keep the console window open
   while setup finishes; the Strata window then opens with a Rounded Cube.

For future launches, double-click `Strata.bat` again. You can create a desktop
shortcut to that file for convenience. Use **File > Open** to open a saved `.strata`
project, or **File > New Project > From file** to start painting your own mesh.

To launch from PowerShell, open a terminal in the repository folder and run:

```powershell
.\Strata.bat
.\Strata.bat "C:\Projects\my.strata"   # open a saved project
.\Strata.bat "C:\Projects\painter.spp" # import a Substance 3D Painter project
```

### macOS

Install Python 3.10+ with `python3` available in Terminal. Open Terminal, change to
the extracted or cloned repository folder (replace the example path), and run:

```sh
cd "/path/to/strata"
bash Strata.command
```

The launcher creates `.venv`, installs dependencies on first launch, and opens the
app. Later launches reuse that environment; changes to `requirements.txt` trigger
a dependency update. To enable launching from Finder, run this once in the same folder:

```sh
chmod +x Strata.command Strata.sh
```

Then double-click **`Strata.command`** in Finder. Keep the Terminal window open
while using Strata. If macOS blocks opening the downloaded launcher, use the
Terminal command above to see its output.

### Linux

Install Python 3.10+ with pip and venv support, and use a graphical desktop session
with OpenGL 3.3 drivers. On Debian/Ubuntu, the Python setup packages are:

```sh
sudo apt install python3 python3-pip python3-venv
```

Use equivalent packages on other distributions. From a terminal, change to the
repository folder and launch:

```sh
cd "/path/to/strata"
bash Strata.sh
```

The launcher creates `.venv` and installs dependencies automatically, reusing it
on later launches and updating dependencies when `requirements.txt` changes.
You can also run `chmod +x Strata.sh` once, then launch with `./Strata.sh`.

Both Unix launchers accept project paths (quote paths containing spaces):

```sh
bash Strata.sh "/home/you/Projects/my.strata"             # Linux
bash Strata.command "/Users/you/Projects/painter.spp"     # macOS
```

### Manual setup (all platforms)

If you prefer to install dependencies yourself, open PowerShell in the repository
folder and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

These commands use the virtual environment directly, so PowerShell script activation
is not required. If `py` is unavailable, use `python` for the first command instead.
For later launches, run only the last command. Append a quoted `.strata` or `.spp`
file path to open it at startup.

For Linux/macOS manual setup, run these commands from the repository folder in a
terminal:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

### Launch troubleshooting and optional features

- **Python cannot be found:** install Python 3.10+ with PATH enabled, then reopen
  your terminal and rerun your platform's launcher.
- **Permission denied on macOS/Linux:** use `bash Strata.command` or `bash Strata.sh`,
  or set executable permissions with `chmod +x` as described above.
- **Linux window-system library errors:** install your distribution's GLFW/OpenGL
  runtime libraries and run from a graphical desktop session.
- **Dependencies fail to install:** read the error in the launcher's console window.
  You can retry the manual setup commands above to see the full installation output.
- **The app exits or cannot create an OpenGL context:** check that your GPU supports
  OpenGL 3.3 and install the appropriate graphics driver. On Windows, launch outside WSL.
- **See startup errors directly:** run `.\.venv\Scripts\python.exe run.py` from
  PowerShell, or `.venv/bin/python run.py` from a macOS/Linux terminal, in the
  repository folder after installing dependencies.

Managed color additionally uses `requirements-managed.txt` (OpenColorIO). After the
base Windows setup, install it with
`.\.venv\Scripts\python.exe -m pip install -r requirements-managed.txt`.
On macOS/Linux, use `.venv/bin/python -m pip install -r requirements-managed.txt`;
the managed-color runtime has only been qualified on Windows.
Optional MikkTSpace/automatic UV preparation uses an installed Blender executable, selected
with STRATA_BLENDER when necessary. See [color](docs/architecture/COLOR.md),
[mesh revisions](docs/MESH_REVISIONS.md), and [UV preparation/scale](docs/UV_PREPARATION_SCALE.md)
for qualified versions, workflows and limits.

## What's in it

- **Test meshes**: Rounded Cube, Sphere, Torus, Canister. **Import**: OBJ, plus FBX / glTF / GLB via `assimp-py`
  (File > New Project > From file, or drag the file onto the window). Meshes need UVs in the 0-1 range.
- **Bakes** (GPU, texture space): position, normal, curvature, ambient occlusion (96 directions), UV coverage.
- **Layers**: fill layers (uniform material + procedural colour/roughness/height noise) and paint layers.
  Blend modes, separate height blend, layer opacity and per-channel blend/opacity/enables for Color,
  Roughness, Metallic, Height, Normal, Emissive and Opacity.
- **Fill materials**: seven bitmap slots with previews, load/relink, clear and imported-image selection.
  UV, tri-planar, planar, spherical and cylindrical mapping with numeric controls and viewport translation,
  rotation and scale. See the [fill-material guide](docs/FILL_MATERIALS.md).
- **Editable objects**: surface paths, ribbons, filled regions and portable font labels.
  Point/profile editing, typography, shared warp/decal controls and resolution regeneration.
  See [authored objects and limits](docs/AUTHORED_OBJECTS.md).
- **Masks**: paintable mask per layer, plus a generator: Edge Wear (curvature), Dirt/Cavity (AO + concavity),
  Ambient Occlusion, Upward Facing (dust), Height Gradient, Noise. Each has level, softness, noise breakup, invert.
- **Effects**: ordered content/mask editors, stable anchors, independent paint rows between mask filters,
  baked-ID color picking and geometry masks. See the [effects guide](docs/EFFECTS.md).
- **Smart materials**: Worn Blue Paint on Steel, Worn Orange Paint on Iron, Rusty Iron, Aged Gold, Dusty Rubber,
  Glazed Ceramic (Chipped). These are just layer stacks you can then edit.
- **3D brush**: projection painting with occlusion and back-face falloff, so strokes wrap across UV seams.
  Size, hardness, flow, spacing, grain; paint or erase; paint into the layer or its mask.
- **Viewport**: GGX PBR shading with a studio environment, display channels (Base Color, Roughness, Metallic,
  Height, Normal, Layer Mask, AO, Curvature, UV Checker).
- **Undo/redo** for strokes and layer-stack changes. **Save/Open** `.strata` projects (mesh + layers + paint).
- **Export**: Unreal (BC, DirectX normal, ORM, height), Unity (Albedo, Normal, MetallicSmoothness, AO, Height),
  or separate maps. 16 px of padding around UV islands, 16-bit height.
- **Substance 3D Painter files** (needs `h5py`): see below.

## Project protection and texture delivery

The Export dialog uses a shared output manifest for its preview and writer. Choose a stock or custom template,
select texture sets and output maps, and configure packing, format, bit depth, size and padding. Multi-set
filenames stay distinct; ambiguous names are rejected before writing. Outputs are staged before existing files
are replaced. Larger exports regenerate supported native paint and procedural content;
legacy raster bases and clone/smudge checkpoints are resampled. See [native paint operations](docs/PAINT_OPERATIONS.md).
See [export behavior](docs/EXPORT.md).

Native raster projects use v3/v4/v5, managed color uses v6, native paint journals use v7, and physical material repeat uses v8; earlier projects remain readable.
Independent mask paint remains v4 when no native journal is present. **Save Portable Project** embeds referenced images,
stencils, alphas, environments and file-based high-poly sources. Saves are atomic, with backups controlled in
**Settings > Project protection**. The same settings control automatic recovery snapshots, which keep the
project's unsaved status. **File > Recover Autosave** opens recovery snapshots; **Project Resources** lists
dependencies and supports relinking. Opening a `.strata.bakN` file restores it as unsaved work for the original
project. Saved bake caches preserve high-poly detail when source geometry is unavailable, with diagnostics;
relink or clear unavailable sources before rebaking. See [persistence and recovery](docs/PERSISTENCE.md).

The [implementation status](docs/IMPLEMENTATION_STATUS.md) records completed work, local verification and known
test failures. The [agent implementation plan](docs/STRATA_PAINTER_IMPLEMENTATION_PLAN.md) describes remaining work.

Texture-set settings can resize the selected set. Replacements are staged before the live set changes;
failure preserves its pixels and history. A successful resize clears global undo history, as stated beside
the Apply control, because old GPU snapshots have incompatible dimensions.

## Substance 3D Painter files

Strata reads Painter's own files, so existing work and asset libraries carry over:

| File | How | What you get |
|---|---|---|
| Project `.spp` | File > Import Substance Painter project, drag onto the window, or `python run.py file.spp` | The mesh (with its mesh parts), **every texture set** at its resolution, and each set's layer stack. Paint layers are rebuilt by **replaying the recorded brush strokes** with Strata's brush. The set you pick in the dialog opens first. |
| Smart material `.spsm` | Assets > **Substance** tab (double-click or drag onto the Layer Stack), or drag the file onto the window | One folder with its layers, masks and effects, like Painter (one undo step). |
| Smart mask `.spmsk` | Assets > Substance > Smart masks (double-click, or drag onto a layer), or drag the file onto the window | A black mask plus the smart mask's effect stack on the selected layer (one undo step). |

The Substance tab finds Painter's starter assets and your shelf automatically (Documents\Adobe\Adobe Substance 3D Painter,
the Painter install's `starter_assets`), shows Painter's thumbnails, and can watch extra folders (Settings > Substance
Painter assets).

**What carries over exactly.** Folders (nested, with their own masks and blending), per-channel blend modes and
opacities (Painter's 32 modes map one to one), the Color / Roughness (or Glossiness) / Metallic / Height / Normal /
Emissive / Opacity channels, uniform fill values, embedded bitmaps and baked mesh maps (as image maps with UV,
tri-planar, planar, spherical or cylindrical projection), geometry masks (mesh parts), mask stacks in order (uniform
fills, levels, blur, invert, histogram scan, anchors), painted masks, filter layers such as HSL and Levels (as
Passthrough layers with the same effect), and anchor points.

**What is approximated.** Painter's procedural materials and generators are compiled Substance graphs (.sbsar) that
only Adobe's engine can run. Strata recognises them by name and parameters and rebuilds them with its own tools:
`mg_mask_editor` and `mg_mask_builder` are decomposed term by term (AO, convex/concave curvature, world-space
direction, position gradient, thickness and grunge become mesh-map and generator effects with the same weights,
blend modes, balance and contrast), `mg_dirt` / edge wear / dust / light map to the matching generators, grunge and
noise textures become Strata's noise, ridged-noise and cellular generators, and procedural material fills become a
uniform value plus noise (gradient-map filters give their colours). Layers with several fills become a folder of
sub-layers so each fill keeps its blending. Warp / sharpen filters, smudge strokes, decals and specular / AO /
displacement channels are left out, and replayed strokes use round dabs (no brush alphas, jitter or symmetry).
Embedded images are written once to `~/.strata/substance_cache` (or `$STRATA_SUBSTANCE_CACHE`). Every import lists
what it changed in Window > Log; projects also show a report. Painter files are only read, never written.

Check every Painter file you have with `python tests/substance_check.py [folder]` (add `--render out_dir` to render
some of them on the GPU).

## Interface

The layout follows Substance 3D Painter's default workspace, so Painter users find things where they expect:

- **Top**: main menu (File, Edit, Layer, Viewport, Window, Help) and, on the right, **Search commands (Ctrl+K)**:
  type any action, layer operation, material or panel name and press Enter.
- **Under the menu**: the tool's options (size, flow, hardness, spacing, paint into layer or mask, colour),
  plus Undo / Redo / **Export** on the right.
- **Left edge**: tools (Paint, Eraser, mask painting) and, at the bottom, Frame, Hide panels, Command search.
- **Assets** (left): smart materials, materials and mask generators with search and a thumbnail-size slider.
  Double-click, or drag onto the Layer Stack. Clicking a material sets the brush (or the selected fill layer).
- **Viewport** (centre): display channel and 3D / 3D+2D / 2D switch in the top-left corner. The 2D view shows
  and paints the active texture set in UV space, with rotation/pan/zoom matching the Alt+mouse profile.
  New workspaces default to split 3D/2D. **Mode > Baking (F8)** exposes nonmodal bake controls in Properties;
  **F9** returns to Painting.
- **Right column**: Texture Set List, then **Layer Stack** (tabbed with Texture Set Settings), then **Properties**.
  Each layer row has visibility, content and mask thumbnails (click the mask thumbnail to paint the mask),
  name (double-click to rename), and blend/opacity (click to change). Drag rows to reorder; Ctrl/Shift-click
  to select several and edit them together. Right-click a row for its menu.
- **Properties** shows only what applies to the current selection, in collapsible sections, with a search box.
- **Right edge**: Display Settings, History (click a step to go back), Log, Shortcuts, Settings.

Every panel docks: drag its tab to move it, Window > Reset Layout to restore. Settings (UI scale, shortcuts,
layout) live in `~/.strata/`. UI scale defaults to your display scaling and can be changed in Settings (75-200%).

## Controls

Strata uses Substance 3D Painter's default shortcuts. Everything is listed (and rebindable) in Window > Shortcuts.

| Action | Input |
|---|---|
| Paint | Left mouse |
| Straight line from the last stroke (snapped) | Shift+click (Ctrl+Shift+click) |
| Orbit | Alt+Left drag, or Right drag |
| Snap to axis views (front, right, top...) | Alt+Shift+Left drag steps between them, or click an axis of the gizmo (bottom right of the 3D view) |
| Pan | Alt+Middle drag, Ctrl+Alt+Left drag, or Middle drag |
| Zoom | Alt+Right drag, wheel, or Alt+wheel |
| Brush size / hardness | Ctrl+Right drag (horizontal / vertical), `[` `]`, Ctrl+wheel |
| Brush flow / angle | Ctrl+Left drag (horizontal / vertical) |
| Rotate light | Shift+Right drag |
| Stencil / projection image | S+Left drag rotate (Shift snaps), S+Middle move, S+Right scale |
| Quick brush settings | Right click |
| Tools: Paint, Eraser, Projection, Polygon fill (shows the mesh wireframe and highlights what a click fills), Smudge, Clone | 1, 2, 3, 4, 5, 6 (Ctrl+6 absolute clone) |
| Clone source | V+click |
| Pick stroke material | P |
| Lazy mouse / Symmetry / Ignore stencil / Resume stroke | D / L / N / A |
| Invert mask paint (white / black) | X |
| Quick mask: edit-apply / clear / invert | U / Y / I |
| Display material / next-previous channel / next-previous mesh map | M / C, Shift+C / B, Shift+B |
| 3D+2D / 3D / 2D view, swap views | F1 / F2 / F3, F4 |
| Resize the 3D and 2D views | Drag the divider between them (double-click: half and half) |
| Perspective / orthographic camera | F5 / F6 |
| Frame mesh | F |
| Hide panels / pause engine | Tab / Shift+Esc |
| Isolate texture set / pick texture set under cursor | Alt+Q / Ctrl+Alt+Right click |
| Layers: copy, cut, paste, duplicate, delete, group | Ctrl+C, Ctrl+X, Ctrl+V, Ctrl+D, Delete, Ctrl+G |
| Copy / paste layer content | Ctrl+Shift+C / Ctrl+Shift+V |
| Show mask in viewport / disable mask | Alt+click / Shift+click the mask thumbnail |
| Undo / Redo | Ctrl+Z / Ctrl+Y |
| New / Open / Save / Close | Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+F4 |
| Bake mesh maps | Ctrl+Shift+B (or F8) |
| Export textures | Ctrl+Shift+E |
| Command search | Ctrl+K |

W/E/R activate native fill projection translation/rotation/scale; Q shows or finishes that editing mode.
Painter shortcuts for features Strata doesn't have yet (general manipulator space/size controls, Iray F10,
particles Ctrl+1/2/3 and Space, Alt+H) are reserved: pressing them says why nothing happened.

The [Painter UX implementation guide](docs/PAINTER_UX_IMPLEMENTATION.md) records the compatible
interactions, visual export editor, saved export configuration and remaining parity requirements.

Every shortcut can be changed in Window > Shortcuts (click the shortcut, press the new keys).

## How it works

Everything happens in UV space on the GPU:

- **Painting**: each brush dab draws the mesh with `gl_Position = uv * 2 - 1`, so every fragment is a texel of the
  texture with its world position attached. Texels within the brush radius (in 3D) get paint, if a picking
  buffer rendered from the camera confirms that point is actually visible. That's why strokes don't care where
  the UV seams are.
- **Paint storage**: each paint layer keeps seven textures (color, roughness, metallic, height, normal, emissive, opacity), each storing a
  premultiplied value plus coverage, so channels can be painted and erased independently with plain blending.
- **Compositing**: the stack is evaluated bottom-up into ping-pong render targets, one full-screen pass per layer.
  Generators read the baked maps, so they evaluate at the same resolution as the paint.
- **Normals**: the final height channel is converted to a tangent-space normal map; the viewport uses mesh tangents.

Code map: `strata/mesh.py` (meshes, tangents, curvature, loaders), `baker.py`, `compositor.py`, `painter.py`,
`renderer.py`, `engine.py` (all of the above, no UI), `exporter.py`, `app.py` (window, docking layout and panels),
`ui/` (theme, command registry + palette, 2D view), `shaders.py` (all GLSL), `substance/` (Painter file import:
HDF5/HBO/Qt readers, layer-stack converter, stroke replay, asset library).

## AI Assistant

**Window > AI Assistant** opens a dockable chat with your installed **Codex** or
**Claude Code** agent. Sign in through the agent's CLI, choose it in the panel,
and describe the changes you want. The agent can inspect the live project, edit
native layers/materials/masks, paint UV paths, and check a fresh viewport image.
Saving/exporting has an explicit panel toggle; edits use native undo.

Other agents can connect through **Connection > Copy external MCP connection**.
Chat history stays in local Strata settings, separate from portable projects.
Source installations are supported; frozen integration is not yet qualified.
See [setup, tools, privacy and limits](docs/AI_ASSISTANT.md).

## Tests

```
python tests/headless_check.py out      # engine only, offscreen (EGL on Linux)
python tests/ui_smoke.py out            # opens the real window, drives a stroke, screenshots
python tests/ui_logic_check.py          # drives shortcuts, mouse, layer actions through the real UI
python tests/ui_tour.py out             # screenshots of the main UI states (add --size 1280x720 --scale 1.5)
python tests/substance_check.py         # read + convert every Painter smart material / mask / sample project found
python tests/substance_check.py --render out    # ... and render some of them on the GPU
python tests/substance_ui_check.py out [folder] [file.spp]   # Substance tab, smart masks, .spp import dialog
python tests/identity_check.py          # persistent IDs and legacy anchor migration, CPU only
python tests/transactions_check.py --gpu out  # actual undo/cancel, shared storage and resource pixels
python tests/transaction_ui_check.py out      # real slider, Escape, multi-selection and display gestures
python tests/channel_check.py --gpu out      # all seven channels through paint, save/reopen and export
python tests/channel_ui_check.py out         # seven-channel controls and independent opacity gestures
python tests/material_check.py --gpu out     # bitmap/projection authoring and failure-safe set resizing
python tests/material_ui_check.py out        # assemble, edit, save/reopen and export an external PBR material
python tests/effects_check.py --gpu out      # ordered paint effects, anchors, copies and archive storage
python tests/effects_ui_check.py out         # effect editors, paint targeting, geometry and ID picking
python tests/brush_check.py --gpu out        # pressure, seeded jitter, seam/backface and portable projection
python tests/brush_ui_check.py out           # advanced brush controls, pressure routing and save/export
python tests/uv_check.py --gpu out           # native UV tools, coordinates, overlap policy and diagnostics
python tests/uv_ui_check.py out              # actual 2D/split/scaled gestures, mask persistence and export
python tests/bake_controls_check.py --gpu out # bake rollback, external maps, native dependencies and display
python tests/authored_check.py --gpu out # persistent paths/ribbons/regions, portable fonts and projective decals
python tests/authored_ui_check.py out    # actual point placement, label editing and shared warp gestures
python tests/procedural_import_check.py --gpu out # native graphs, source metadata and resumable import replay
python tests/procedural_import_ui_check.py out    # actual graph editor and import continuation controls
python tests/substance_compatibility.py out --render # curated available Painter fixtures and native references
python tests/advanced_bake_check.py --gpu out # named pairing, cages, sampling and painted correction fields
python tests/advanced_bake_ui_check.py out    # actual source controls, correction paint and portable reopen
python tests/bake_ui_check.py out             # native shelf, high-poly bake, environment and portable delivery
python tests/memory_check.py --gpu out         # sparse storage, region undo, budgets and canonical instances
python tests/memory_ui_check.py out            # real budget controls and graceful viewport allocation failure
```

## Known limits

- Multiple material-based texture sets and layer folders are supported. Materials can own UDIM tiles with cached 3D/2D views, live surface/UV paint/erase/masks/projection, height-normal edge continuity, polygon fill, independent duplication, image sequences and atomic delivery. T14's authored-layout workflow is verified locally; advanced tool, instancing, topology and workload limits are explicit in [tile acceptance](docs/architecture/T14_ACCEPTANCE.md).
- Advanced brush controls, stencils, mirror/radial symmetry and effect editors are available.
  Windows Ink pressure capture is implemented; physical tablet hardware remains unverified.
  Linux/macOS and legacy WinTab devices use mouse pressure 1.0. See [brush qualification](docs/BRUSHES.md).
- High-poly baking, external mesh maps, environment controls and the portable native shelf are available; see [qualification](docs/BAKE_DISPLAY_LIBRARY.md). Named pairing, custom cages and painted ray/distance correction are qualified in [advanced baking](docs/ADVANCED_BAKING.md).
- Interactive 2D painting supports paint/erase, masks, projection, clone and smudge; see [UV painting](docs/UV_PAINTING.md) for tool limits.
- Managed OCIO, native journals, bounded mesh revisions and automatic UV preparation
  are qualified locally. The [UV preparation controls](docs/UV_PREPARATION_SCALE.md)
  support a 1–64-page UDIM budget with fixed valid UVs and angle-seam chart allocation.
  Arbitrary topology preservation and changed-layout tiled reimport remain outside
  the qualified scope. User scalar channels and shader workflows are documented below.
- Imported Substance procedural content and brush strokes can be approximated; file-read success is not visual equivalence.
- Paint history stores changed GPU regions and has configurable byte/step limits; see [memory qualification](docs/MEMORY.md).


User channels and shaders: **Layer > Channels and shaders** creates paintable
scalar channels and arbitrary-component export templates. Bind independent linear
specular F0 RGB/glossiness and optional clearcoat, or inspect physical vertex
displacement on a mesh with declared source units. See
[workflow contracts and qualification](docs/SHADER_WORKFLOWS.md).


**File > Deliver mesh and materials** writes portable Blender bundles or real
mesh/material GLB files. Blender is the qualified target; see
[delivery conventions and limits](docs/DELIVERY.md). Source batch and optional
Cycles entry points share the native engine:

```powershell
python -m strata commands
python -m strata batch examples/delivery_job.json
python -m strata render export/reference.zip export/render.png --size 512 --samples 32
```

The sample declares meter source units and uses installed Blender for MikkTSpace.
See [extension and batch API v1](docs/EXTENSIONS.md) for job paths, explicit plugin
loading and failure behavior. Particle simulation brushes and Unreal/Unity setup
integrations remain unclaimed. Frozen delivery builds have not been qualified.


Local qualification and release readiness are tracked separately. See
[validation lanes and reproducible evidence](docs/VALIDATION.md) and
[release/manual gates](docs/RELEASE_GATES.md). The test suite and generated evidence
remain local and ignored; public CI checks source syntax only. Physical tablet,
other-platform runtime and frozen-package claims require their own qualification.
