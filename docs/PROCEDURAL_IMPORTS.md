# Native procedural content and Painter import fidelity (T16)

T16 adds explicit native graph data, structured source coverage and resumable import
replay. It does not execute compiled Adobe graphs. Native graphs run without Adobe;
Painter conversions remain feature-dependent translations and approximations.

## Native graphs

Add a Graph content or mask effect. The node editor offers grunge, gradient,
transform, directional-warp and sharpen recipes, per-node parameters, content-channel
selection and two-to-eight gradient stops with editable positions/colors. Property
edits use ordinary undo. Effects retain normal row ordering, blending and opacity.
Recipes create explicit versioned DAGs; they do not infer execution from layer names.
`strata.graphs.node`, `preset` and `validate` also support authored DAGs through Python.

A graph is `{version: 1, nodes: [...], output: node_id}`. Nodes have a unique `id`,
`op`, prior-node `inputs` and explicit `params`. Forward/cyclic inputs, unknown
operations, duplicate IDs, wrong arity, nonfinite/out-of-range parameters and unordered
stops reject. There are at most 32 nodes. The evaluator releases inputs after their
last consumer and bounds live f2 RGBA intermediates to 256 MiB; it raises a visible
budget error instead of substituting a lower-resolution result.

| Operation | Inputs | Parameters and meaning |
|---|---|---|
| input | none | Selected content channel or current mask, in UV space. |
| constant | none | value -16..16. |
| grunge | none | scale .01..2048, seed 0..65535, roughness 0..1, ridge 0..1; six deterministic noise octaves. |
| ramp | none | angle -180..180 degrees and offset -2..2, clamped linear UV ramp. |
| gradient | one | 2..8 ordered stops [position, R, G, B]; luminance input, linear color interpolation. |
| transform | one | positive X/Y scale, X/Y UV offset and rotation in degrees; wrapped UV sampling. |
| warp | two | source plus scalar field; signed strength in texels and angle in degrees. |
| sharpen | one | strength 0..8 and radius .1..32 texels; four-neighbor unsharp kernel. |
| mix | two | linear weight 0..1. |

Scalar channels use their actual packed component; color, normal and emissive use RGB.
The graph operates in the compositor's current working space. It does not add a color
transform. Native tiled evaluation supports these effects, with tile-local filter
neighborhoods; general cross-tile warp/blur continuity remains outside this acceptance.

## Source compatibility and extraction

Each loaded smart material, smart mask and project receives a structured report:
source SHA256/path/kind, available Painter version, decoded dataset encoding/data
version, read success, feature counts and retention classifications, editable native
node/layer counts, conversion notes, skipped/unexecuted features, appearance validation
state and replay state. Unknown source metadata is retained as lossless tagged HBO
objects/primitives/bytes in native project metadata for diagnosis and future migration.
Unreadable preset variants are reported while a readable version may still be selected.
Read success does not imply supported operations or appearance identity.

Assets > Painter import coverage opens the saved reports and can export their JSON.
The existing import log keeps conversion notes. Unvalidated operations are explicit:
compiled procedural materials, unsupported channels/actions and source symmetry or
proprietary brush tips do not acquire an exact-execution claim merely because reading
succeeded. Native sharpen/warp kernels and luminance gradient maps replace the prior
silent detail-filter skip / average-color fallback; their source appearance remains
unvalidated. Imported gradient stop colors are retained with uniformly spaced positions;
more than eight stops report the omitted remainder. Existing projection and channel
mappings remain editable; multi-channel levels no longer truncate to three channels.

Embedded image extraction keys its cache by resource content, preserves native dimensions
and writes 16-bit PNGs. The previous silent 4096-pixel reduction is removed. Malformed
or truncated tile headers/data/dimensions fail explicitly. The decode budget is 256 MiB;
unsupported HDR values reject with a conversion note rather than silently clipping.
Embedded bitmap stroke alphas and explicitly named emitter jitter fields are mapped to
native brushes. Unknown brush metadata is retained; enabled source symmetry has no
validated adapter in this fixture corpus and remains metadata only.

The isolated `substance.backends.probe()` records local external command discovery and
fallbacks. No sbsrender/sbsbaker/sbsupdater command was found on PATH in this environment.
External execution remains disabled: installation/API/deployment/licensing qualification
is required before an adapter can claim graph execution. Native graphs, embedded
bitmap fallbacks and reported approximations remain available.

## Replay budgets and continuation

The import dialog and incomplete-import window expose session and per-layer dab
budgets (defaults 150000 and 40000). No source-point stride/decimation is applied.
A source stroke is buffered and published only when complete. Budget exhaustion or
Cancel keeps completed strokes, discards the current uncommitted stroke and retains
all remaining source jobs at a whole-stroke checkpoint. Raise both budgets when one
large stroke cannot fit. Progress/cancellation is checked within long strokes as well
as between them. Initial file decoding is synchronous; Cancel controls replay, not
an asynchronous file reader.

Continue import replay resumes from the saved source cursor. Portable save/reopen
retains source jobs, brush resources, owner IDs, committed counters and a fingerprint
of the mesh, target resolution and raw pixels. Continuation rejects changed targets
instead of duplicating or overwriting paint; reopen the saved checkpoint or explicitly
discard the remainder. Undo/redo that restores the exact target pixels can restore a
matching checkpoint. Continuation chunks do not add independent pixel-undo entries.
Imported completed paint remains a raster base on resize; this is not native T12
resolution-independent stroke authoring. Native UV replay now interpolates the entire
UV path across world-space seams instead of treating a long UV segment as a surface jump.
Missing 3D camera/surface data is counted as skipped and retained in source metadata.

`Engine.add_imported` and `import_painter_project` accept `progress`, `max_dabs` and
`per_layer`. `continue_import(...)` resumes; `discard_import_continuation()` explicitly
abandons pending execution. `apply_mask_state(..., **options)` accepts the same budgets,
progress and a structured source report. A second content import rejects while replay
is incomplete. Painter replay into tiled materials and project UVs outside 0..1 reject
explicitly before replacement; native tiled graphs are a separate supported path.

## Storage and qualification

Native graphs, retained import reports or continuation activate project format v11.
Ordinary independent-mask projects without journals remain v4, ordinary tiles v9,
and advanced bake projects v10 when no T16 data is used. Source .spp/.spsm/.spmsk files
are opened read-only and their bytes are not modified.

- `tests/procedural_import_check.py --gpu .artifacts/procedural-t16-final`: 13
  contracts (six CPU, seven GPU): DAG/schema validation, unknown metadata roundtrip,
  source projection/native-filter mapping, full-size/content-addressed extraction,
  invalid images, analytic ramp/gradient/transform/warp/sharpen pixels, graph undo,
  portable/tiled output, exact resumed/uninterrupted replay, cancellation with no
  partial pixels, checkpoint mismatch, pending-alpha portability/relink/undo and invalid-budget preservation.
- `tests/procedural_import_ui_check.py .artifacts/procedural-ui-t16-final`: ten
  actual desktop assertions; recipe/node editing, undo, incomplete state, portable
  reopen, continuation, report command/view and actual JSON export. Screenshots visually reviewed.
- `tests/substance_compatibility.py .artifacts/substance-t16-final --render` builds
  a curated local matrix from available source assets, checks source hashes before/
  after, exports native 64px reference images and checks exact portable output.
  JSON records feature/file versions, retained editability, appearance status,
  notes/skips, replay budgets and native output references separately. These images
  are native reference exports, not matched Painter ground truth. Source appearance
  deviation stays explicitly unvalidated; portable output differences are measured.
- CPU contracts are in CI; hosted execution remains unrun. Local corpus evidence
  includes inline and registry presets and a Painter 9.1.0 project. Exact source
  graph reproduction, arbitrary source symmetry, UDIM Painter replay, cross-platform
  GPU behavior and full-resolution production corpus rendering remain unqualified.

Final local evidence: all 11 curated source files remain byte-identical, and every
native 64px reference has portable maximum pixel difference 0. Inline data versions
2/16/43/45, registry 54 and project data version 80 are represented; the project
identifies Painter 9.1.0. AGD_RockBase pauses visibly at 1835 committed dabs under
the 2000-dab fixture budget; Height Blend completes 354 dabs and JadeToad 62.
No appearance-deviation metric against Painter is implied by portable pixel equality.
The final 27-suite regression has 26 zero exits; the sole nonzero suite remains the
known feature low-flow failure (101/102). After the alpha-resource relink refinement,
procedural CPU/GPU/UI, persistence and frozen v2/v3 checks pass again. Logs are
`.artifacts/t16-final-*.log`; corpus data/images are in `.artifacts/substance-t16-final`.
