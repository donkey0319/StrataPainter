# Baking, display and native library (T09)

Bake Mesh Maps stages high-poly source add/remove, frontal/rear distances,
backface policy, ID source/generation and optional AO/thickness/ID maps. Required
position/world-normal/curvature/coverage maps remain enabled; a high-poly source
also generates tangent normal and height. All-set baking preserves each other
set's settings unless Apply these settings to all sets is explicitly checked.
External-map overrides remain set-specific even when parameters are shared.

Baking displays progress on the GPU context thread. Cancel requests finish the
current set safely and discard staged results before publication. Failure or
cancellation retains every live set's maps, settings and history. Success is one
undo step; undo/redo restores both maps and settings, including saved-state
markers. High-poly hit coverage is displayed in Texture Set Settings > Mesh maps.

Assign external maps there to AO, curvature, thickness, ID, tangent normal,
height, world normal or object position. Images must match the selected set's
resolution exactly and contain finite values. Scalar maps and tangent normals
use untransformed data; world normals use encoded RGB converted to signed unit
vectors; positions must already use the normalized object's coordinates. RGB
maps require at least three components. Assignment checks the selected set ID,
uploads before mutation, and is undoable. Generators, preview and export read the
same BakeSet map textures. Clear restores a native map through a staged rebake.
Explicit rebake reapplies overrides from their recorded files; missing/invalid
files preserve the original live maps. Resize with rebaking requires replacement
external files at the new size. File relinking also validates map dimensions.

Preview includes raw Baked Tangent Normal and Baked Height modes in both views,
separate from composited material Normal/Height. The selected raw map's preview
button is disabled when no such bake exists. Existing channel modes retain their
indices; the two new modes are appended as 16 and 17.

Display Settings loads/clears environments and exposes rotation, exposure, baked
AO, emissive intensity and alpha testing. Failed environment loads preserve the
previous texture. Environment changes are undoable. Environment resources and
display values survive portable project save/reopen.

Assets > Native provides searchable smart-material, smart-mask, brush and export
template categories, named saves/imports, material/mask/brush thumbnails,
double-click application and drag/drop onto the Layer Stack. Native material,
mask and brush files embed referenced fill/alpha/stencil/projection images;
loading verifies their hashes and resolves immutable content in the resource
cache. Originals can be moved or removed afterward. Legacy assets without an
embedded manifest remain readable. Native imports validate their category and
preserve conflicting existing files with a hash suffix. Thumbnails are optional
sidecar PNGs; templates use a category icon. Save/import uses the existing native
library and exporter rather than a separate material pipeline.

## API and schema

- `rebake(settings=None, ts_index=None, progress=None, all_sets=False)` stages all
  targets before publishing. `settings` may also map set IDs to individual
  BakeSettings. A progress callback returning False requests cancellation.
- `set_high_poly(...)` now uses the same staging/undo boundary.
- `assign_mesh_map(key, path, interpretation='data', ts_index=None, set_pid=None)`
  validates and assigns; `path=None` clears/rebakes the selected override.
- `set_environment(path_or_none)` validates before replacing the environment and
  records an undo action.
- `BakeSettings.external_maps` records path, content hash, interpretation and set
  ID. Empty overrides are omitted from serialization, preserving exact legacy
  bake dictionaries. `projectio` packages and validates nonempty records and the
  cached evaluated maps. Display metadata is optional and defaults to legacy
  values. Ordinary projects remain v3; independent mask paint remains v4.
- `library.import_native` validates native imports. Existing save/load APIs remain
  available. CPU alpha definitions moved unchanged to `strata/alphas.py`, with
  old resource-module names re-exported; CPU brush serialization needs no GL.

## Evidence and handoff

- `tests/bake_controls_check.py --gpu .artifacts/bake-t09-final`: eight CPU/GPU
  scenarios cover semantic validation, actual generator consumption of imported
  AO, invalid-assignment rollback, portable maps/rebake, all-set failure/cancel,
  independent settings across all-set controller/save/reopen, map selection and
  undo, environment failure/undo/display persistence, and native dependency
  collection after deleting originals.
- `tests/bake_ui_check.py .artifacts/bake-ui-t09-final`: 21 actual UI assertions
  cover saving/reapplying editable weathering on a second mesh with distinct
  pixels, real shelf drag/drop, material/mask/brush/template saves, staged source
  management/cancel, real high-to-low bake with hit coverage, identical results
  with/without progress rendering, external-map assignment/preview, environment
  and emissive/alpha controls, portable reopen and export. Native file-dialog
  results are injected. Native, bake and display screenshots visually reviewed.
- Final regression includes 11 UV, 27 transaction, 13 persistence and 6 effect
  scenarios, frozen v2/all 16 reference maps and portable v3 roundtrip. Full feature
  suite remains 101/102 with the known low-flow failure. An empty-field legacy
  serialization mismatch was fixed and affected legacy/persistence/bake checks
  rerun; no fixture or assertion was weakened. Logs `.artifacts/t09-final-*.log`.
- Windows CPython 3.13 / RTX 4050; no new dependency. Physical tablet, native OS
  picker and other GPU platforms remain unqualified. CPU map validation added to
  CI; remote execution unverified. Single agent, existing local changes retained,
  no commit/release. T10 is next; retained bake undo snapshots count toward its
  memory-budget work. Higher-level cage/skew correction remains T15.

T15 source pairing, custom cages, supersampling, diagnostic colors and paintable
correction fields are documented in [advanced baking](ADVANCED_BAKING.md).
