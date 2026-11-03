# Native paint operations and resolution evaluation

Native strokes now create a version-1 operation journal, independently of GPU
undo history. Projects containing a journal require archive **v7**. Raster-only
v1–v6 projects remain readable; independent mask paint without a journal remains
v4, canonical cross-resolution raster sharing v5, managed color v6. New native
mask strokes add the v7 journal rather than dropping their v4 raster payload.

Each operation records frozen brush settings, enabled channels, content-addressed
alpha/stencil/projection images, random seed, raw pressure/time samples, surface
or UV coordinates, triangle IDs, camera matrices, viewport size, UV navigation,
mesh/color revisions, target set/layer/effect, and the emitted dabs. Replay uses
the recorded dabs and original camera occlusion, avoiding new spacing/jitter
decisions. Native surface and native UV operations retain distinct provenance.
T14 extends this distinction to material-owned v9 tiles, including live surface/UV
input, recorded-view replay and bounded accumulation pages. See architecture/TILES.md
for tiled operation lifetime, qualification and remaining reprojection limits.
Changing camera or editing resolution does not change their original footprint.

Checkpoint nodes store compressed half-float raster bases. Clone/smudge retain
their result, settings, source revision and clone offset as explicit checkpoints;
they are resampled at another resolution. Quick-mask-dependent strokes and
baked-map projections also checkpoint their result. None of those results are
discarded. Imported paint, copied/library rasters and edits made outside native
strokes remain raster bases; their absent brush information is not invented.
Extensions that write textures directly must invalidate the corresponding
`engine.journal` head before subsequent strokes/evaluation.

Undo/redo select journal heads as well as pixels; history eviction releases GPU
snapshots while retaining the document journal and its branches. Successful
resolution changes retain the journal even though incompatible GPU undo history
is cleared. Portable save includes journal image dependencies and checkpoints.
Nonportable saves still require their recorded resource files/cache for replay;
the saved current raster always preserves opening appearance. Missing immutable
sources cause an actionable evaluation failure rather than an alternate image.

Larger export creates a detached set, replays supported paint at the requested
resolution, rebakes analytic surface maps and evaluates procedural fills/effects
there. Imported mesh maps and raster bases are explicitly resampled. Original
paint textures, layers, settings, journal heads and edit resolution remain intact.
Failure releases staged textures and preserves existing delivery files. The
normal memory budget applies; a request that cannot fit fails before publication.
Mesh/color revision mismatches fall back to the current raster and appear in
`engine.evaluation_report`. There is no mesh-reprojection claim in this package.

The journal is document content, compressed in CPU memory and on disk; its size
is not an undo-budget estimate. Long clone/smudge histories can grow project size.
Periodic destructive compaction or a fixed operation limit is not applied.

## Qualification

- Seven CPU/GPU scenarios pass: schema/ancestry validation, deterministic replay,
  undo/redo/eviction, immutable alpha resources, 3D occlusion after camera changes,
  independent mask paint, legacy v4 migration, native resize, clone checkpoints
  and failed replay/publication preservation.
- Seven actual UI assertions pass UV input, native resize, larger export and
  portable reopen. Screenshot inspected in `.artifacts/journal-ui-t12/`.
- RTX 4050, 1024 editing / 4096 output, 512px checker alpha: regenerated output
  equals direct 4096 evaluation (maximum difference **0.0**, tolerance 0.001).
  Resized editing pixels differ by **0.28619**. Detached evaluation took **0.953s**;
  peak tracked texture estimate **3402.4 MiB**, excluding driver/depth/buffer/mipmap
  overhead. `.artifacts/journal-t12-1k4k/results.json` records this single fixture;
  it is not a general performance guarantee.

Engine API: `engine.journal` exposes nodes/heads; `evaluate_set(engine, ts, size)`
in `strata.evaluation` is a context manager yielding `(temporary_set, report)`.
Use the existing exporter and `set_resolution`; they share this native evaluation
path. Do not retain temporary GPU textures after the context exits.
