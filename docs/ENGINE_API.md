# Strata engine API (for the UI and import/export agents)

The engine is UI-free: everything below works headless (see `tests/feature_check.py`, which
exercises every call in this file). The UI only draws widgets, forwards mouse input, and calls
`engine.update()` + `engine.render()` once per frame. The old API that `app.py` uses
(`new_project`, `add_layer`, `layers`, `selected`, `brush`, `begin_stroke/stroke_to/end_stroke`,
`export(...)`, `save/load`) still works unchanged.

```python
from strata.engine import Engine
eng = Engine(moderngl_ctx)
eng.new_project("Canister", res=2048)            # or a Mesh from strata.mesh.load_mesh(path)
eng.add_smart_material("Rusty Iron")
eng.update(); eng.update_view(w, h); eng.render((x, y, w, h))
```

## Project and texture sets

| Call | What it does |
|---|---|
| `new_project(mesh, res=2048, ao_samples=96, progress=None, bake_settings=None, split_materials=True, resolutions=None)` | `mesh` is a built-in name (`mesh.BUILTIN_MESHES`) or a `Mesh`. One **texture set** per material; `resolutions={"SetName": 1024}` per set. `progress(f)` gets 0–1. |
| `eng.sets`, `eng.active`, `set_active(i)`, `eng.ts` | The texture-set list and the active set. `eng.layers`, `eng.comp`, `eng.bakes`, `eng.res` all refer to the active set. |
| `set_resolution(res, ts_index=None, rebake=True)` | Resample layers non-destructively (only that set when `ts_index` is given). |
| `rebake(settings: BakeSettings, ts_index=None)` | Re-run mesh-map baking. `BakeSettings` fields: `ao_samples, ao_max_distance, ao_spread, ground_plane, ground_offset, thickness_max_distance, id_source, dilation, curv_from_normal, ...` (`id_source` indexes `baker.ID_SOURCES`) |
| `set_high_poly(paths_or_meshes, ts_index=None, all_sets=True, front=0.02, rear=0.02)` | High → low bake (normal, height, ID) via GPU ray casting. The high-poly mesh doesn't need UVs. |
| `save(path)` / `load(path)` | `.strata` v2 (texture sets, groups, instances, camera, environment); v1 files still load. |
| `undo()` / `redo()` | Covers paint, masks, layer-tree edits and effect edits. |
| `eng.modified`, `mark_saved()` | True when anything has changed since the last new / open / save: paint, masks, layer settings, layer tree, resolution or bake settings. Selection, display mode, camera and brush settings don't count. `new_project`, `load` and `save` reset it. It fingerprints the layer settings when read, so check it when you need it (e.g. on close), not every frame. The app uses it for the "Unsaved Changes" prompt on quit. |

Mesh loading: `strata.mesh.load_mesh(path)` handles OBJ natively (objects → parts, `usemtl` → materials)
and FBX/glTF/GLB/DAE/PLY/STL/USD through assimp-py. `load_high_poly(path, low)` keeps the low-poly's
normalisation. **Import agent:** if you build a `Mesh` yourself, fill `positions, normals, uvs, indices`
and optionally `tri_material` + `material_names` (texture sets) and `parts` + `part_names`, then call
`mesh.finalize(normalize_size=True)`.

## Layer tree (`strata/layers.py`)

`Layer` fields the UI edits directly (set `eng.dirty = True` afterwards):
`name, visible, opacity, blend, chan_blend[7], chan_opacity[7], enabled[7], color, rough, metal, height, normal, emissive, opac, gen (MaskGen), proj (Projection), maps, effects, mask_effects, children, expanded`.

Channels (index order): `CHANNELS = Color, Roughness, Metallic, Height, Normal, Emissive, Opacity`.
Lists for drop-downs: `BLEND_MODES` (32), `GENERATORS` (14), `PROJECTIONS`, `MESH_MAPS`,
`MASK_EFFECTS`, `CONTENT_EFFECTS`, `EFFECT_DEFAULTS`.

| Call | Notes |
|---|---|
| `add_layer(kind="paint"|"fill"|"group", name=None, index=None, parent=None)` | Returns the layer. `add_fill_layer(name, material=preset name, maps={"C": path,...})`. |
| `add_smart_material(name, as_group=False)` | Built-in names in `presets.SMART_MATERIALS`. |
| `delete_layer / duplicate_layer(layer=...)`, `move_layer(idx, delta)`, `move_layer_to(layer, parent, index)` | Drag-and-drop in the layer panel → `move_layer_to`. |
| `group_layers(list, name)`, `ungroup(group)` | Folders. `layer.walk()` iterates a subtree; `eng.all_layers()` the whole set. |
| `instance_layer(layer, ts_index)` | Shares a layer with another texture set. |
| `select(layer)`, `eng.layer` | The focused layer (may be nested inside a group). |
| `add_mask(value) / remove_mask / fill_mask(value)` | Paint mask. |
| `add_effect(kind, layer=None, mask=None, index=None, blend=0, opacity=1.0, **params)` | Mask effects go in `layer.mask_effects`, content effects in `layer.effects` (chosen from `kind` unless `mask=` is given). Params: see `EFFECT_DEFAULTS`. `remove_effect`, `move_effect(e, ±1)`. |
| `set_geometry_mask(parts)` | Restrict a layer to mesh parts. |

Smart masks / library (`strata/library.py`, stored in `~/.strata/library` or `$STRATA_LIBRARY`):
`list_library(kind)`, `import_resource(path, kind)`, `save_smart_material(eng, layers)`,
`load_smart_material(eng, path)`, `apply_smart_mask(eng, layer, name_or_path)` (built-ins in
`presets.SMART_MASKS`), `save_brush_preset / load_brush_preset`.

## Substance 3D Painter content (`strata/substance/`)

Reading needs `h5py`. Conversion runs on the CPU; the engine calls put the result on the GPU.

```python
from strata.substance import importer
res = importer.load_smart_material("Bronze Armor.spsm")     # ImportResult: one folder, .notes
eng.add_imported(res)                                        # above the selected layer, one undo step
sm = importer.load_smart_mask("Dirt Cavities.spmsk")         # SmartMask: .mask (MaskBuild), .notes
eng.apply_mask_state(sm.mask, layer=eng.layer)               # black mask + the mask's effect stack
proj = importer.load_project("scene.spp", texture_set=0)     # ProjectImport: mesh + every texture set
eng.import_painter_project(proj)                             # new project; strokes replayed
eng.last_replay                                              # .dabs, .skipped, .truncated
```

| Module | Role |
|---|---|
| `spfile`, `hbo`, `qt`, `assbin` | HDF5 container, Painter's HBO object streams (inline and registry encodings), Qt values, embedded mesh |
| `convert` | Painter layer tree -> `layers.Layer` trees (`ImportedLayer`), masks -> `MaskBuild` (painted base + mask effects), notes |
| `importer` | file-level entry points (`load_smart_material`, `load_smart_mask`, `inspect_project`, `load_project`) |
| `apply` | GPU side: allocation, painted masks, stroke replay, undo |
| `replay` | replays Painter strokes through `painter.Stroke` from each stroke's stored camera |
| `library` | finds Painter's starter assets and shelf for Assets > Substance; thumbnail loader |

Fill-layer maps may be file paths or `bake:<name>` (a mesh map of the texture set, e.g. `bake:curvature`).

## Painting and tools

`eng.brush` (`layers.Brush`) holds every brush setting the properties panel shows: size (`size_space`
screen / object / UV), hardness, flow, spacing, `stroke_opacity`, angle + `follow_path`, jitters,
`alpha` (built-in names in `resources.BUILTIN_ALPHAS` or an image path), `stencil` + `stencil_xform`,
`symmetry` (off / mirror / radial) + `sym_axis` + `radial_count`, `lazy`, pressure options,
`tool` (`TOOL_PAINT, TOOL_SMUDGE, TOOL_CLONE, TOOL_PROJECTION` in `painter.py`), `mode` (paint/erase),
`target` (0 layer, 1 mask, 2 quick mask), per-channel `enabled` + values.

```python
hit = eng.pick(x, y)                      # None when the cursor misses the mesh
eng.begin_stroke(hit, pressure)           # mouse down
eng.stroke_to(eng.pick(x, y), pressure)   # mouse move
eng.end_stroke()                          # mouse up: one undo step
```

| Call | Tool |
|---|---|
| `set_clone_source(x, y)` | Clone tool source (Ctrl/Alt-click). |
| `paint_path(points, closed=False)` | Path tool: list of screen points. |
| `select_triangles(x, y, mode)` / `select_triangles_rect(x0, y0, x1, y1, mode, lasso=None)` | Polygon fill selection. `mode`: 0 triangle, 1 polygon, 2 UV island, 3 mesh part, 4 texture set. Returns triangle ids. |
| `polygon_fill(tris, erase=False, target=None, mask_value=None)` | Fill the selection into the layer, mask or quick mask. |
| `ensure_quick_mask() / clear_quick_mask()` | Quick mask (`brush.use_quick_mask` limits painting). |
| `pick_material(x, y, apply=True)` | Material picker: reads every channel under the cursor into the brush. |
| `brush_radius(hit)`, `can_paint()` | For drawing the cursor circle and greying out tools. |

## Viewport

`eng.renderer.mode` → `renderer.DISPLAY_MODES` (Material, Base Color, …, Layer Mask, AO, Curvature,
UV Checker, Emissive, Opacity, Thickness, ID, World Space Normal, Position).
`eng.renderer.load_environment(path_to_hdr_or_exr)`, `renderer.emissive_intensity`, `renderer.alpha_test`,
`eng.camera` (`orbit`, `ortho`, `to_dict`). 2D view: `eng.render_2d(rect, channel, zoom, pan, ts_index)`.

## Export (`strata/exporter.py`)

```python
exporter.export_textures(eng, folder, template="Unreal Engine (Packed)", file_format=None,
                         depth=None, size=None, padding="infinite", texture_sets=None,
                         shader_json=False, overrides=None)   # -> list of written paths
```

* `OUTPUT_TEMPLATES` — Painter's stock templates (Document channels, Unreal, Unity URP/HDRP, Blender,
  Sketchfab, Arnold, Spec/Gloss, Mesh maps) plus three legacy Strata ones. A template is a dict
  `{"maps": [{"name": "$mesh_$textureSet_ORM", "r": "ao", "g": "roughness", "b": "metallic", "format": "png", "depth": "8"}]}`;
  sources are listed in `SOURCES`. `save_template / load_template` read and write JSON.
* `PADDING`: none, infinite, dilation_transparent, dilation_background, dilation_diffusion.
* Formats (`imageio.FORMATS`): PNG 8/16, TGA, TIFF 8/16/32f, JPEG, BMP, WebP, EXR 16f/32f, HDR, PFM.
  `imageio.read_image / write_image` are usable on their own (the import agent can use `read_image`
  for EXR/HDR/16-bit inputs).
* `export_mesh(eng, path)` writes an OBJ with one group per texture set.
* The legacy `export(eng, folder, preset)` still works.

## Not implemented yet

Particle brushes, Iray/path tracing, UDIM tiles, OCIO colour management, user-defined channels, a
"paint" layer inside mask stacks, and painting in the 2D view.
