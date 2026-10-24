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

## Controls

| Action | Input |
|---|---|
| Paint | Left mouse |
| Orbit | Alt+Left drag, or Right drag |
| Pan | Middle drag |
| Zoom | Wheel, or Alt+Right drag |
| Brush size | `[` `]` or Ctrl+Wheel |
| Eraser toggle | E |
| Paint layer / its mask | M (X swaps white/black) |
| Cycle display channel | C |
| Frame mesh | F |
| Undo / Redo | Ctrl+Z / Ctrl+Y |
| Save / Open / Export | Ctrl+S / Ctrl+O / Ctrl+E |

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
`renderer.py`, `engine.py` (all of the above, no UI), `exporter.py`, `app.py` (window + ImGui UI),
`shaders.py` (all GLSL).

## Tests

```
python tests/headless_check.py out      # engine only, offscreen (EGL on Linux)
python tests/ui_smoke.py out            # opens the real window, drives a stroke, screenshots
```

## Known limits

- One texture set (UDIMs and multiple materials per mesh aren't supported).
- No layer folders, no stencils/alphas for the brush, no symmetry yet.
- Undo keeps GPU copies of the layer being painted; 24 steps max.
