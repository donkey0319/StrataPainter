# Strata

A small 3D texture painter written from scratch in Python + OpenGL. It covers the core
Substance-Painter-style loop: bake mesh maps, stack fill and paint layers with masks and
generators, paint directly on the model in 3D, and export PBR maps for Unreal or Unity.

## Run

Python 3.10+ (on Windows, use native Windows Python rather than WSL for the best GL drivers).

```
pip install -r requirements.txt
python run.py                 # starts with a Rounded Cube
python run.py my.strata       # open a saved project
python run.py painter.spp     # import a Substance 3D Painter project
```

Needs an OpenGL 3.3 capable GPU. First bake at 2048 takes about a second on a real GPU.

## What's in it

- **Test meshes**: Rounded Cube, Sphere, Torus, Canister. **Import**: OBJ, plus FBX / glTF / GLB via `assimp-py`
  (File > New Project > From file, or drag the file onto the window). Meshes need UVs in the 0-1 range.
- **Bakes** (GPU, texture space): position, normal, curvature, ambient occlusion (96 directions), UV coverage.
- **Layers**: fill layers (uniform material + procedural colour/roughness/height noise) and paint layers.
  Blend modes (Normal, Multiply, Screen, Overlay, Add), separate height blend (Normal / Add), opacity,
  per-channel enables for Color / Roughness / Metallic / Height.
- **Masks**: paintable mask per layer, plus a generator: Edge Wear (curvature), Dirt/Cavity (AO + concavity),
  Ambient Occlusion, Upward Facing (dust), Height Gradient, Noise. Each has level, softness, noise breakup, invert.
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
  the texture set in UV space (view only).
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

Painter shortcuts for features Strata doesn't have yet (the transform manipulator Q/W/E/R/T, Iray F10,
particles Ctrl+1/2/3 and Space, Alt+H) are reserved: pressing them says why nothing happened.

Every shortcut can be changed in Window > Shortcuts (click the shortcut, press the new keys).

## How it works

Everything happens in UV space on the GPU:

- **Painting**: each brush dab draws the mesh with `gl_Position = uv * 2 - 1`, so every fragment is a texel of the
  texture with its world position attached. Texels within the brush radius (in 3D) get paint, if a picking
  buffer rendered from the camera confirms that point is actually visible. That's why strokes don't care where
  the UV seams are.
- **Paint storage**: each paint layer keeps four textures (color, roughness, metallic, height), each storing a
  premultiplied value plus coverage, so channels can be painted and erased independently with plain blending.
- **Compositing**: the stack is evaluated bottom-up into ping-pong render targets, one full-screen pass per layer.
  Generators read the baked maps, so they evaluate at the same resolution as the paint.
- **Normals**: the final height channel is converted to a tangent-space normal map; the viewport uses mesh tangents.

Code map: `strata/mesh.py` (meshes, tangents, curvature, loaders), `baker.py`, `compositor.py`, `painter.py`,
`renderer.py`, `engine.py` (all of the above, no UI), `exporter.py`, `app.py` (window, docking layout and panels),
`ui/` (theme, command registry + palette, 2D view), `shaders.py` (all GLSL), `substance/` (Painter file import:
HDF5/HBO/Qt readers, layer-stack converter, stroke replay, asset library).

## Tests

```
python tests/headless_check.py out      # engine only, offscreen (EGL on Linux)
python tests/ui_smoke.py out            # opens the real window, drives a stroke, screenshots
python tests/ui_logic_check.py          # drives shortcuts, mouse, layer actions through the real UI
python tests/ui_tour.py out             # screenshots of the main UI states (add --size 1280x720 --scale 1.5)
python tests/substance_check.py         # read + convert every Painter smart material / mask / sample project found
python tests/substance_check.py --render out    # ... and render some of them on the GPU
python tests/substance_ui_check.py out [folder] [file.spp]   # Substance tab, smart masks, .spp import dialog
```

## Known limits

- One texture set (UDIMs and multiple materials per mesh aren't supported).
- No layer folders, no stencils/alphas for the brush, no symmetry yet.
- Undo keeps GPU copies of the layer being painted; 24 steps max.
