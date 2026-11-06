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
| `new_project(mesh, res=2048, ao_samples=96, progress=None, bake_settings=None, split_materials=True, resolutions=None, color_settings=None, tangent_basis='legacy', uv_settings=None, source_unit=None)` | Built-in name or Mesh; optional OCIO managed mode, external Blender Mikk/UV preparation, and declared source units. Defaults preserve legacy behavior. See architecture/COLOR.md and UV_PREPARATION_SCALE.md. |
| `eng.sets`, `eng.active`, `set_active(i)`, `eng.ts` | The texture-set list and the active set. `eng.layers`, `eng.comp`, `eng.bakes`, `eng.res` all refer to the active set. |
| `move_layers_to(layers, parent=None, index=None)` | Atomically move an ordered forest within the active set, preserving order and avoiding cycles. One stack undo; insertion index is measured before removing the moving roots. |
| `export_settings` / `set_properties(eng, export_settings=configuration)` | Bounded, validated export metadata with undo and modified-state tracking; optional schema v14. Loading never exports. See EXPORT.md. |
| `set_resolution(res, ts_index=None, rebake=True)` | Regenerate supported native paint; resample raster bases; stage maps/compositor before publishing. Failure retains live storage/history; success clears GPU undo history but retains the journal. `rebake=False` resamples cached maps. Shared rasters retain canonical storage. |
| `rebake(settings: BakeSettings, ts_index=None)` | Re-run mesh-map baking. `BakeSettings` fields: `ao_samples, ao_max_distance, ao_spread, ground_plane, ground_offset, thickness_max_distance, id_source, dilation, curv_from_normal, ...` (`id_source` indexes `baker.ID_SOURCES`) |
| `add_authored_path(points, kind='path', width=.04, name=None)` / `add_text(text, font, name=None)` | Create editable fill-material objects with surface anchors or portable fonts. `set_authored` and `set_path_point` use property undo; see AUTHORED_OBJECTS.md. |
| `continue_import(max_dabs=150000, per_layer=40000, progress=None)` | Resume a saved whole-stroke Painter replay checkpoint after target validation; see PROCEDURAL_IMPORTS.md for import budgets, source reports and native graph effects. |
| `set_bake_correction(kind, layer=None)` | Bind/clear an active material paint layer as raw ray-direction or distance data; undoable. Advanced BakeSettings and optional v10 storage are documented in ADVANCED_BAKING.md. |
| `set_high_poly(paths_or_meshes, ts_index=None, all_sets=True, front=0.02, rear=0.02)` | High → low bake (normal, height, ID) via GPU ray casting. The high-poly mesh doesn't need UVs. |
| `assign_mesh_map(key, path, interpretation='data', ts_index=None, set_pid=None)` | Assign a validated, resolution-matched external map through the native BakeSet interface; undoable and portable. `path=None` clears/rebakes. |
| `set_environment(path_or_none)` | Load or clear an environment transactionally; failed loads preserve the previous image. |
| `save(path, portable=False, backups=0)` / `load(path)` | Raster v3/v4/v5, managed v6, native journals v7, physical material repeat v8, material tiles v9, advanced bake controls v10, native graphs/import reports/continuation v11, authored objects/warp/decal v12, optional user/shader workflows v13; earlier versions remain readable. Atomic saves and staged restoration preserve resources/bakes. |
| `set_resource_color_space(path, space)` | Managed-only undoable immutable-image interpretation: `None` (automatic), `'srgb'` or `'linear'`. Data channels bypass it. See architecture/COLOR.md. |
| `journal`, `evaluation_report` | Native operation nodes/heads survive GPU history eviction. Larger export and resolution changes regenerate supported native paint; raster bases/checkpoints are resampled. See PAINT_OPERATIONS.md. |
| `strata.reimport.prepare(eng, mesh_or_path, mapping=None, max_distance=None)` | Staged geometry/bake/native-paint revision with `.report`, `.commit()` and `.cancel()`. Commit writes a portable pre-reimport checkpoint; see MESH_REVISIONS.md. |
| `strata.uvprep.prepare_mesh(mesh, settings, source_unit=None)` | Preserve/generate UVs through installed Blender; returns a new mesh. Optional tile_count=1..64 distributes intact angle-seam charts across UDIM pages. Settings and limits in UV_PREPARATION_SCALE.md. |
| `strata.exporter.export_mesh(eng, path, coordinates='normalized')` | OBJ with generated UVs/material groups; coordinates also accept `'source'` and `'meters'`. Meter delivery requires declared units. |
| `autosave(path, backups=3)` | Writes a portable recovery snapshot without clearing modified state or changing the manual-save destination. |
| `prepare_save(path, portable=False, commit=True)` / `finish_save(snapshot)` | Capture owned CPU archive data on the graphics thread, then publish successful save state on that thread. Completion refuses to clear newer edits. Desktop saves run archive compression/write/verification on a worker; `save()` remains synchronous. See PERSISTENCE.md. |
| `project_resources`, `project_diagnostics` | Resource manifest and actionable missing/changed resource or bake-restoration diagnostics. |
| `relink_resources(mapping)` | Replace resource IDs or recorded paths with validated local files; retained mesh bakes are not implicitly rebaked. |
| `mark_modified()` | Marks recovered content as unsaved so normal close/save protection applies. |
| `undo()` / `redo()` | Covers paint, masks, layer-tree edits, effect membership, property edits and resource relinking; restores saved-state revisions. |
| `eng.modified`, `mark_saved()` | True when anything has changed since the last new / open / save: paint, masks, layer settings, layer tree, resolution or bake settings. Selection, display mode, camera and brush settings don't count. `new_project`, `load` and `save` reset it. It fingerprints the layer settings when read, so check it when you need it (e.g. on close), not every frame. The app uses it for the "Unsaved Changes" prompt on quit. |

Mesh loading: `strata.mesh.load_mesh(path)` handles OBJ natively (objects → parts, `usemtl` → materials)
and FBX/glTF/GLB/DAE/PLY/STL/USD through assimp-py. `load_high_poly(path, low)` keeps the low-poly's
normalisation. **Import agent:** if you build a `Mesh` yourself, fill `positions, normals, uvs, indices`
and optionally `tri_material` + `material_names` (texture sets) and `parts` + `part_names`, then call
`mesh.finalize(normalize_size=True)`.

## Layer tree (`strata/layers.py`)

Editable `Layer` fields (use `set_property` / `set_properties` for undo and cache invalidation):
`name, visible, opacity, blend, chan_blend[7], chan_opacity[7], enabled[7], color, rough, metal, height, normal, emissive, opac, gen (MaskGen), proj (Projection), maps, effects, mask_effects, children, expanded`.

Use engine tree/effect operations for membership changes. `expanded` is session UI state. Persistent `pid` values on layers, effects and texture sets survive save/load; runtime integer `uid` remains a UI handle. See [transaction contracts](TRANSACTIONS.md).

`assign_fill_map(layer, key, path_or_none)` validates and uploads an image before changing the fill. Assignment enables that channel in the same undo step; clearing retains the enable flag and restores the constant source. Unchanged assignments preserve redo. `set_projection(layer, **changes)` validates mapping mode, signed nonzero scale, offset, rotation, axis and positive tri-planar sharpness. `set_channel_settings(layer, key, blend=None, opacity=None)` updates one channel while preserving other overrides; `blend=-1` inherits the layer rule. These APIs join an active transaction or create a discrete edit. See the [material workflow](FILL_MATERIALS.md).

`begin_edit(targets=None, label="Edit")` starts a compound or continuous property edit. Call `set_properties(target, **values)` or `set_property(target, name, value)` during the gesture, then `commit_edit()` once or `cancel_edit()` to restore starting values. Setters without an active transaction commit a discrete edit. No-op and canceled edits preserve redo. Targets can include document layers, effects, generators, projections, texture sets, and the engine's `normal_strength`; brush/view controls remain session settings.

`clone_layers(layers)` copies a complete forest with fresh identities and remaps internal anchor references. Instances share definitions/canonical rasters while each set owns evaluated outputs at its own size. Resizing an old raster is resampling. See [memory contracts](MEMORY.md).
For tiled materials, `duplicate_layer(layer=...)` copies a layer/group within the
same material, including rasters, native replay, masks, image sequences and anchor
bindings, as one combined undo action. Tiled clipboard forest copying through
`clone_layers` and cross-material instances remain explicitly guarded.

Channels (index order): `CHANNELS = Color, Roughness, Metallic, Height, Normal, Emissive, Opacity`.
Lists for drop-downs: `BLEND_MODES` (32), `GENERATORS` (14), `PROJECTIONS`, `MESH_MAPS`,
`MASK_EFFECTS`, `CONTENT_EFFECTS`, `EFFECT_DEFAULTS`.

| Call | Notes |
|---|---|
| `add_layer(kind="paint"|"fill"|"group", name=None, index=None, parent=None)` | Returns the layer. `add_fill_layer(name, material=preset name, maps={"C": path,...})`. |
| `add_smart_material(name, as_group=False)` | Built-in names in `presets.SMART_MATERIALS`. |
| `delete_layer / duplicate_layer(layer=...)`, `move_layer(idx, delta)`, `move_layer_to(layer, parent, index)` | Drag-and-drop in the layer panel → `move_layer_to`. |
| `group_layers(list, name)`, `ungroup(group)` | Folders. `layer.walk()` iterates a subtree; `eng.all_layers()` the whole set. |
| `instance_layer(layer, ts_index)` | Shares a definition/canonical raster; cross-resolution raster projects use v5. |
| `select(layer)`, `eng.layer` | The focused layer (may be nested inside a group). |
| `add_mask(value) / remove_mask / fill_mask(value)` | Paint mask. |
| `add_effect(kind, layer=None, mask=None, index=None, blend=0, opacity=1.0, **params)` | Mask effects go in `layer.mask_effects`, content effects in `layer.effects` (chosen from `kind` unless `mask=` is given). Params: see `EFFECT_DEFAULTS`. `remove_effect`, `move_effect(e, ±1)`. |
| `set_geometry_mask(parts)` | Restrict a layer to mesh parts. |

Smart masks / library (`strata/library.py`, stored in `~/.strata/library` or `$STRATA_LIBRARY`):
`list_library(kind)`, `import_resource(path, kind)`, `save_smart_material(eng, layers)`,
`load_smart_material(eng, path)`, `apply_smart_mask(eng, layer, name_or_path)` (built-ins in
`presets.SMART_MASKS`), `save_brush_preset / load_brush_preset`.

Assets > Native exposes these APIs plus templates, search, thumbnails and drag/drop.
Native material/mask/brush saves collect image dependencies. Bake operations stage
all target sets before publishing, are undoable, and accept cancellation through
`progress` returning False. Optional per-set external maps and display settings
survive project restoration. See [bake/display/library qualification](BAKE_DISPLAY_LIBRARY.md).

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

The desktop exposes these advanced controls, `sym_center` and all seven `proj_maps`
slots. `Brush.seed` defaults to 17; `begin_stroke(hit, pressure=1.0, info=None,
seed=None)` uses that value unless explicitly overridden. The live `Stroke.seed`
records the normalized 32-bit seed, independently of undo history. Brush settings
and sizing freeze at stroke start. Windows Ink capture feeds actual pen pressure
when available; other input defaults to 1.0. Physical tablet hardware remains
unverified. Clone/smudge use flow rather than stroke opacity. See [brush controls
and qualification](BRUSHES.md) for platform limits and reproducible checks.

```python
hit = eng.pick(x, y)                      # None when the cursor misses the mesh
eng.begin_stroke(hit, pressure)           # mouse down
eng.stroke_to(eng.pick(x, y), pressure)   # mouse move
eng.end_stroke()                          # mouse up: one undo step
```

Native UV input uses `begin_uv_stroke(uv, UVMapping(size, zoom, center), pressure=1.,
seed=None)`, `stroke_uv_to(uv, pressure=1., mapping=None)` and `end_stroke()`. It shares
paint/mask storage, undo, compositing and exports with 3D strokes. `pick_uv`,
`uv_brush_radius`, `set_uv_clone_source` and `uv_tool_reason` support input/cursor
controllers. See [UV painting](UV_PAINTING.md) for overlap, background and tool limits.

| Call | Tool |
|---|---|
| `set_clone_source(x, y)` | Clone tool source (Ctrl/Alt-click). |
| `paint_path(points, closed=False)` | Existing one-shot smooth paint helper: world positions or surface pick-info dictionaries. Persistent editable alternatives are in AUTHORED_OBJECTS.md. |
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
* `build_export_manifest(eng, folder, **options)` resolves/validates all paths and effective settings without GPU work or filesystem writes. The desktop preview and `write_export_manifest(eng, manifest)` consume the same manifest. The writer stages all maps before publication and rejects stale project identities.
* The legacy `export(eng, folder, preset)` still works. Single-set names are retained; multi-set legacy exports include the set name to prevent replacement of another set's output. Ambiguous sanitized names are rejected before writing.

The desktop File menu exposes Save Portable Project, Project Resources, Recover Autosave and Create Recovery Snapshot. Settings > Project protection controls autosave timing and backup retention. Opening a `.strata.bakN` file restores it as unsaved work targeting the original project path.

## Not implemented yet

Particle brushes and advanced tiled tools remain pending. The optional Blender/Cycles offline backend is documented in DELIVERY.md. Material tile backend APIs are documented in
architecture/TILES.md: enable_tiles, paint_tiles_uv, assign_tile_sequence and
context-managed evaluate_tile.
The ordinary begin_uv_stroke/stroke_uv_to/end_stroke/cancel_stroke APIs support
live tiled paint, erase, masks and projection with one undo action.
begin_stroke/stroke_to also support native tiled surface paint with whole-mesh
camera occlusion and recorded-view replay, including world-space symmetry.
Bounded surface reimport projects and replays tiled operations transactionally;
unchanged UVs, topology and material assignments are required. Misses reject.
polygon_fill supports tiled paint/erase and base/effect masks as a staged raster
edit at authored resolution; only the affected owner's target becomes a raster
base. pick_material samples the hit tile's authored accumulators independently
of viewport LOD. Both retain existing single-tile behavior.
MaterialTiles.cached_evaluation leases native-precision render outputs separately
from display thumbnails; Engine.render_materials streams them into the bound
target with global picking and tile-local image sampling. See architecture/TILES.md
for viewport LOD, budgets and incomplete live-tool support.
Explicit tiled saves use v9 (optional bake/procedural/authored features activate v10–v13); independent mask paint without a journal remains v4.
T14's authored/imported-layout acceptance is verified locally; see
architecture/T14_ACCEPTANCE.md for evidence and audited tool/workload limits.
Tile evaluation derives height normals using sequential neighboring evaluations
and narrow height/coverage/world-position strips. Covered locally continuous
edges share height samples; outer/disconnected/ambiguous borders clamp.
Managed OCIO, native journals and bounded mesh revisions are qualified
above; none establishes arbitrary topology preservation or full Painter parity.


## User channels and shader workflows (T18)

`add_user_channel(name, default=0, label=None)` declares a project-local linear
scalar key (`user:name`). `set_user_channel(key, layer=None, value=..., enabled=...,
blend=..., opacity=...)` edits layer settings through normal undo transactions.
`paint_user_channel(key, value=1)` selects and enables a user raster target on the
current layer; `paint_user_channel(None)` restores document-channel painting.
Native stroke, UV, polygon-fill, replay and tile APIs retain their ordinary entry
points. `assign_fill_map` / `set_channel_settings` accept declared user keys.

`add_effect("invert", mask=False, channel=3, user_channel=key)` (also levels, blur,
brightness_contrast and graph) targets a custom scalar instead of document Height.
Native graph parameters and editing remain unchanged. Use `engine.comp.user_outputs[key]`
inside a live evaluation scope, or `render_2d(..., channel=key)`. Tile outputs expire
with their lease as usual. Export maps accept user keys in any component.

`set_shader_workflow(model="spec_gloss", bindings={...})` requires independent
specular_r/g/b and glossiness channel bindings. Optional coat/coat_roughness
bindings work in either model. `exporter.workflow_template(engine)` derives the
matching outputs. Physical displacement additionally requires declared source
units and `displacement_meters` / `height_midlevel` settings. Only existing mesh
vertices are displaced; edit in UV space while the displaced preview is active.

Projects opt into v13 only for these optional definitions/settings. See
SHADER_WORKFLOWS.md for precise scalar, shader, storage and qualification limits.


## Delivery, extensions and source batch CLI (T19)

`strata.delivery.export_blender(engine, path, size=None)` creates an atomic,
verified Blender mesh/material ZIP; `export_glb(engine, path, size=None)` creates
real indexed glTF 2.0 GLB. Both evaluate the same native materials, including
supported higher-resolution paint replay. These are distinct from texture presets
and legacy `export_mesh` OBJ output. See DELIVERY.md for supported models, physical
units, Mikk normals, single-tile guards and actual target references.

`strata.offline.capabilities()` and `render_bundle(bundle, output, size=512,
samples=32, backend="blender_cycles", timeout=300)` expose the separate optional
renderer. Missing backends fail without creating output or changing a scene.

`strata.extensions.builtins()` returns the version 1 registry; `execute` dispatches
native project/material/layer/channel/brush/export/delivery operations. Explicit
modules declare `STRATA_EXTENSION_API=1` and register namespaced callbacks.
`install_ui_command` bridges a registered action to a separate native menu and
the command palette. `strata.cli.run_job` and `python -m strata batch` share this
API. See EXTENSIONS.md for exact signatures, ownership and error contracts.

## Live AI tools

`strata.ai_tools.StrataTools(engine, capture=None, on_save=None)` exposes a bounded
provider-independent tool contract over the native engine. `specifications()`
returns MCP-compatible schemas; `call(name, arguments)` validates and executes
on the owning engine thread. File output defaults to disabled (`allow_output`).
The desktop queues external calls onto that thread and provides viewport capture
and successful-save destination callbacks. See [AI_ASSISTANT.md](AI_ASSISTANT.md)
for connection, lifetime, native undo and supported-operation limits.
