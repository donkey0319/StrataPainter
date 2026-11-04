# StrataPainter implementation status

Execution started October 25, 2026; T00–T04 integration completed October 26, 2026. T05 integration completed October 27, 2026. The implementation plan and capability review remain the baseline specifications. Verification below describes this local Windows/RTX 4050 environment, not all supported platforms.

| Package | Owner | Status | Scope and evidence |
|---|---|---|---|
| T00 | baseline agent and coordinator | verified | Deterministic CPU fixtures reproduced with matching hashes; GPU fixture project and 16 reference maps captured before application edits. Existing feature suite 94/96, headless exit 0 with save/load image difference 0.0, UI smoke exit 0. See BASELINE.md for existing failures and unrun checks. |
| T01 | export agent and coordinator | verified | Shared validated manifest, collision-safe paths, staged publication/rollback, modern export controls and correct sparse channel packing. 21 CPU tests pass; real export UI passes 10 assertions, including modal visibility, distinct set pixels and preview/writer agreement. See EXPORT.md. |
| T02 | persistence agent and coordinator | verified | Versioned portable resources, atomic saves/backups, transactional restoration, independent set settings, bake-time provenance and recovery/relink UI. 13 CPU/GPU persistence tests and 7 controller tests pass; real resource selection and unsaved-recovery confirmation exercised. See PERSISTENCE.md. |
| T03 | identity, transaction and check agents; coordinator | verified | Persistent IDs, stable anchor references, unified edit transactions and saved-state undo, resource relink undo, instance guards. 27 CPU/GPU transaction checks, 13 identity checks and 11 actual UI gesture assertions pass. See TRANSACTIONS.md. |
| T04 | channel core, engine/painter and export/check agents; coordinator | verified | Immutable descriptors across model, paint storage, compositing, controls and export. 14 CPU/GPU channel checks and 6 actual UI assertions pass; legacy pixels remain identical. See CHANNELS.md. |
| T05 | fill UI, engine and test agents; coordinator | verified | Seven bitmap slots and previews, imported resource selection, five projection modes with numeric/viewport edits, per-channel blending and safe per-set resize controls. 14 CPU/GPU material checks and 47 actual UI assertions pass; see FILL_MATERIALS.md. |
| T06 | coordinator, single-agent workflow | verified | Ordered effect editors, stable anchor selection, independent mask paint with undo/v4 storage, geometry masks and viewport ID selection. Six focused CPU/GPU scenarios and 15 actual UI assertions pass; see EFFECTS.md. |
| T07 | coordinator, single-agent workflow | verified | Advanced brush controls, seven projection slots, deterministic stroke seeds and Windows Ink pressure capture. Seven focused CPU/GPU scenarios and 35 actual UI assertions pass; physical tablet hardware unverified. See BRUSHES.md. |
| T08 | coordinator, single-agent workflow | verified | Native UV tools, shared coordinates, complete channel diagnostics and wireframe. Eleven CPU/GPU scenarios and 26 actual UI assertions pass; see UV_PAINTING.md. |
| T09 | coordinator, single-agent workflow | verified | Transactional baking/external maps, display controls and portable native shelf. Eight CPU/GPU scenarios and 21 actual UI assertions pass; see BAKE_DISPLAY_LIBRARY.md. |
| T10 | coordinator, single-agent workflow | verified | Lazy channels, cropped/bounded history, visible budgets, v5 canonical sharing and measured 2K/4K workloads. Nine CPU/GPU scenarios and seven UI assertions pass; see MEMORY.md. |
| T11 | coordinator, single-agent workflow | verified | Explicit OCIO-managed/v6 and legacy modes, linear/HDR/data handling, portable image interpretation and external Mikk adapter. Eight CPU/GPU scenarios, seven actual UI assertions and actual Blender 5.1.2 render comparisons pass; see architecture/COLOR.md. |
| T12 | coordinator, single-agent workflow | verified | Durable native journal/v7, explicit raster checkpoints and detached resolution evaluation. Seven focused scenarios and seven UI assertions pass; 1K-to-4K alpha output matches direct evaluation exactly. See PAINT_OPERATIONS.md. |
| T13 | coordinator, single-agent workflow | verified | Ten CPU/GPU scenarios and eight actual UI assertions pass staged comparison/reprojection, material retention, cancel/commit and portable checkpoint recovery; see MESH_REVISIONS.md. |
| T14 | coordinator, single-agent workflow | verified | Plan acceptance passes for authored/imported multi-tile layouts: material-owned v9 tiles, streamed bake/evaluation, live surface/UV paint and masks, height-normal gutters, browser/grid, diagnostics, image assignment, bounded revision and atomic UDIM delivery. Eight CPU foundation contracts, four isolated GPU scenarios, 53 Engine GPU scenarios and 63 tile UI assertions pass. Audited tool/instance/topology/workload limits are explicit in architecture/T14_ACCEPTANCE.md. |
| T15 | coordinator, single-agent workflow | verified | Named high/low pairing, validated custom cages, hit/miss/crossing diagnostics, 1x/2x/4x sampling and undoable painted ray/distance fields with optional v10 storage. 13 CPU/GPU scenarios and ten actual desktop assertions pass, including tiled portable reopen/resize and stale-source recovery. See ADVANCED_BAKING.md for contracts and limits. |
| T16 | coordinator, single-agent workflow | verified | Explicit native procedural DAGs and node editors, source/version coverage with retained metadata, full-size image extraction and whole-stroke budget/progress/cancel/portable continuation. 13 CPU/GPU scenarios, ten desktop assertions and 11 real source fixtures pass; native references reopen with zero pixel difference and unchanged source hashes. Source graph appearance, symmetry and tiled Painter replay limits are explicit in PROCEDURAL_IMPORTS.md. |
| T17 | coordinator, single-agent workflow | verified | Editable anchored paths/ribbons/regions, portable font labels and shared projective warp/decal controls with optional v12 storage. Four CPU contracts, ten GPU scenarios and 12 desktop assertions pass, including native resize, tile boundaries, camera stability, font recovery and supported mesh revision. Indexed-chart, typography and topology limits are explicit in AUTHORED_OBJECTS.md. |
| T18 | coordinator, single-agent workflow | verified | Project-local scalar channels through paint/effects/portable replay/packing, independent F0/glossiness, clearcoat and physical vertex displacement with optional v13 storage. 16 CPU/GPU scenarios, 16 desktop assertions and actual Blender 5.1.2/Cycles references pass. Scalar, shader approximation and non-tessellated/single-tile displacement limits are explicit in SHADER_WORKFLOWS.md. |
| T19 | coordinator, single-agent workflow | verified | Blender mesh/material bundles, real GLB interchange, explicit extension/batch API v1 and isolated optional Cycles rendering. 19 CPU/GPU/runtime cases and ten desktop assertions pass; actual multi-material Blender/Cycles reconstruction verifies pixels and material ownership. Single-tile/target/tangent/precision and unbuilt frozen-release limits are explicit in DELIVERY.md and EXTENSIONS.md. |
| T21 | coordinator, single-agent workflow | verified | Fourteen CPU/runtime scenarios and twelve desktop assertions cover Blender single-/multi-tile preparation, fixed UVs, 11-page row wrapping, separate materials, source scale, per-page painting/reopen/delivery and revision guards. Bounded angle-seam allocation and unchanged-layout tiled revision limits are explicit in UV_PREPARATION_SCALE.md. |
| T22 | coordinator, single-agent workflow | source verified | Dockable Codex/Claude Code chat, native tool schemas, authenticated live MCP bridge, viewport feedback and project-scoped conversation resume. Real signed-in turns verified for both providers. Source-only and bounded-tool limits are explicit in AI_ASSISTANT.md. |
| T20 | coordinator, single-agent workflow | in_progress | Local qualification increment verified: guarded CPU lanes, hashed 45-check run, managed carried scene/UDIM variant, 512/2K/4K profiles, initial-stroke budget admission fix with focused reruns, and relocated source candidate. Known low-flow failure remains; current legacy UI logic passes. Tests stay local; syntax-only CI, frozen/physical-tablet/other-platform/remote gates remain explicit in VALIDATION.md and RELEASE_GATES.md. |

## File ownership for the first wave (T00–T02)

- Baseline agent: baseline fixture/check tooling under `tests/`, `docs/BASELINE.md`, `docs/FEATURE_PARITY.md` and generated `.artifacts/baseline` outputs.
- Export agent after T00: `strata/exporter.py`, `tests/export_check.py`, export imports/state/helpers/dialog regions in `strata/app.py`, export documentation and the existing legacy-export assertion in `tests/feature_check.py` by coordination.
- Persistence agent after T00: persistence and project-creation hooks in `strata/engine.py`, new project archive/resource helper, dedicated persistence regression checks and persistence documentation.
- Coordinator: this status document, API/user documentation integration and non-export persistence UI regions. Shared-file changes must preserve the other owner's regions.

## Integration policy

All agents shared this checkout. Application code was unchanged until T00 captured the baseline. After that, each owner worked within the boundaries above. Coordinator reviewed actual diffs, incorporated independent review findings, and ran the combined regression suite. No release publication or Git commit was made in this wave.

## Environment

The project `.venv` interpreter uses Windows Store Python and cannot start under the current sandbox. An approved elevated execution successfully imported ModernGL and created an OpenGL 3.3-compatible context. Run native project tests through the approved execution path, with task-local output/configuration directories. Do not install dependencies or alter user asset/settings directories merely to run tests.

## Final integration evidence

| Check | Actual result | Evidence |
|---|---|---|
| `tests/export_check.py` | 21/21 pass using bundled CPU Python | Pure manifest, image packing, failure injection and rollback tests; no GL dependency. |
| `tests/persistence_check.py --gpu .artifacts/persistence-final` | 13/13 pass using native Python and RTX 4050 | Includes changed/missing high-poly sources, stale settings, failed GPU restoration, portability and legacy archive validation. |
| `tests/persistence_check.py` | 7 CPU archive tests pass; 6 GPU tests intentionally skipped | Confirms CPU-only CI entry point. Sandboxed bundled runtime stalled on filesystem I/O and was terminated; native run passed. |
| `tests/project_ui_check.py` | 7/7 pass | Recovery scheduling, backup discovery, corrupt metadata, failed recovery and relink contracts. |
| `tests/project_ui_check.py --ui .artifacts/project-ui-qualified` | Pass | Real bitmap save, autosave, recovery, portable save, resource selection and unsaved-replacement confirmation. Modal screenshots visually reviewed. |
| `tests/export_ui_check.py .artifacts/export-ui-verified` | 10/10 assertions pass | Actual modal controls render; 10 distinct multi-set textures match preview; selected EXR output is 256px; custom sparse packing works. Screenshots visually reviewed. |
| `tests/wave_integration_check.py .artifacts/baseline/fixtures .artifacts/integration/legacy` | Pass | Frozen v2 project retains per-set settings and all 16 reference maps, then portable v3 round-trip preserves outputs. Detailed differences in results.json. |
| `tests/feature_check.py .artifacts/integration/feature --res 256` | 101/102 pass | Only existing low-flow accumulation assertion fails (0.999). The export section now completes and writes all 166 intended built-in-template files. |
| `tests/unsaved_ui_check.py` | Pass, 0 failures | Unsaved-close/cancel/save behavior remains correct with v3 persistence. |
| `tests/ui_logic_check.py` | One splitter-cursor assertion failure | Same failure reproduced using an isolated archive of original commit cefb609; other actions pass. Original sources in .artifacts/baseline-ui-source. |
| `.github/workflows/checks.yml` | Added, not run on GitHub | CPU export/archive checks and fixture generation on Windows/Linux, Python 3.12/3.13. GPU qualification remains local. |

The two known broad-suite failures were not fixed by weakening assertions or changing golden references. They remain separate work. Native file-dialog interaction, the Adobe conversion corpus, Linux/macOS GPU behavior and physical tablet input were not qualified in this wave.

## Next assignment

T19 is verified within DELIVERY.md and EXTENSIONS.md contracts; continue T20 release/hardware/platform qualification and explicitly deferred extensions as separately scoped work. T18 is verified within SHADER_WORKFLOWS.md contracts. T17 is verified within AUTHORED_OBJECTS.md contracts; T16 within PROCEDURAL_IMPORTS.md and T15 within ADVANCED_BAKING.md. T14 is verified for authored/imported tile layouts; T21 adds bounded automatic multi-tile chart packing with unchanged-layout tiled revision guards. Keep one primary agent, targeted reads, concise logs, focused tests and one final regression pass per milestone. Preserve all uncommitted work. Physical tablet hardware remains unqualified.

## Helmet tutorial workflow qualification

The [helmet workflow reference](HELMET_TEXTURING_TUTORIAL.md) now includes native
desktop instructions for material blockout, linked chip masks, normal-detail wear,
decals, typography, emissive, opacity inspection and packed delivery.

- Added positional scalar mask anchors, editable mask bevels and content-normal
  anchor inputs to curvature-based generators. Existing content-anchor capture
  semantics remain intact. New effects select native v15, with archive preflight
  guarding placement, radius and strength. Existing project version selection
  and legacy restoration remain supported.
- Added Albedo validation to both 3D and UV displays with an editable session
  threshold in sRGB code values. Managed linear colors are converted before the
  check. This display diagnostic leaves composited and delivered pixels intact.
- Seven local CPU/GPU scenarios pass for capture order, later source filters,
  disabled/moved sources, rename, undo, bevel profiles, portable masks and normal
  sources, resolution changes, malformed archives, actual ORM component values,
  and managed/legacy diagnostic rendering.
- Nineteen real effects UI assertions pass, including creation of mask anchors
  and bevels, enabling the normal input, selecting its source, independent paint,
  persistent identity selection and portable reopen. Screenshots of the new
  normal controls and the reopened workflow were visually inspected.
- One final 14-suite regression passes user channels, authored objects and their
  desktop controls, effects, channels, transactions, persistence, materials,
  bake controls, managed color, UV desktop painting, legacy fixtures and CPU
  export. The feature suite retains its documented low-flow failure at 101/102.
  No unexpected failures occurred. The runner confirms unchanged application
  sources and local suite during qualification. Report and logs are in
  .artifacts/tutorial-regression.
- Focused local evidence is in tests/tutorial_workflow_check.py,
  tests/tutorial_ui_check.py and .artifacts/tutorial-ui-final. These files remain
  ignored and excluded from the Git index.

Bevels use an eight-direction distance approximation with a 0–32 texture-pixel
radius. Normal-derived curvature is a local vector-difference approximation.
Neither filter stitches UV seams or tile neighborhoods. Glass uses the existing
alpha preview, with optical refraction left to a destination renderer. The
albedo diagnostic checks dark values only. Adobe filter pixel equivalence and
the complete artist cursor sequence remain unverified. See [effects](EFFECTS.md)
for the capture and generator contracts.

## T03 qualification

- `tests/transactions_check.py --gpu .artifacts/transactions-t03-qualified`: 27/27 pass, including stale anchor pixels, copied references, tree/raster/quick-mask saved markers, shared-set effects, resource undo and unsafe instance rejection.
- `tests/identity_check.py`: 13/13 CPU checks pass, including archive validation and legacy migration.
- `tests/transaction_ui_check.py .artifacts/transaction-ui-t03-qualified`: 11/11 actual gesture assertions pass. Screenshot inspected.
- Persistence: 13/13 CPU/GPU checks pass; recovery/resource controller: 7/7 pass; export: 21/21 CPU checks pass.
- Frozen v2 fixture: all 16 reference maps and portable v3 roundtrip pass. Full feature suite: 101/102, retaining only the known baseline low-flow failure.
- CPU identity and transaction checks added to CI; remote execution remains unverified.

## T04 qualification

- `tests/channel_check.py --gpu .artifacts/channels-t04-qualified`: 14/14 pass. Each of seven channels passes fill assignment, enable/disable, real brush-stroke coverage, independent other-channel storage, layer-opacity blending, v3 save/reopen and 32-bit EXR export. Normal assignment uses a tilted direction and verifies its encoded unit normal.
- `tests/channel_ui_check.py .artifacts/channel-ui-t04`: 6/6 pass. Both production panels expose all seven values; actual mouse gestures confirm opacity-channel independence, fill undo and brush session semantics. Screenshot inspected.
- `tests/wave_integration_check.py .artifacts/baseline/fixtures .artifacts/integration/t04-final-legacy`: pass; all 16 original reference maps have maximum difference 0.0, followed by a matching portable v3 roundtrip.
- Combined regressions: 27/27 transaction checks, 13/13 persistence checks, 21/21 export CPU checks and 10/10 real export UI assertions pass. Unsaved-close/save UI passes with zero failures.
- Full feature suite: 101/102, retaining only the known baseline low-flow failure. All 55 Python sources/tests parse; `git diff --check` passes.
- CPU channel checks added to CI; remote execution remains unverified. Custom channels, managed color transforms and higher-precision emissive compositing remain later work.

## T05 ownership and qualification

Ownership in the shared checkout was explicit: fill UI agent owned `strata/ui/material.py` and `docs/FILL_MATERIALS.md`; engine agent owned `strata/engine.py` and new `strata/materials.py`; check agent owned `tests/material_check.py` and `tests/material_ui_check.py`; coordinator owned `strata/app.py`, CI and documentation integration. No commit or release was created.

- `tests/material_check.py --gpu .artifacts/materials-t05-final`: 14/14 pass (3 CPU validation and 11 GPU scenarios). Covers all seven bitmap assignments, automatic channel enablement as one undo step, all five mapping modes, axis/sharpness effects, channel blending, portable save/export, failed allocation/bake rollback, cached resize provenance and categorical part IDs.
- `tests/material_ui_check.py .artifacts/material-ui-t05-final`: 47/47 assertions pass. Actual controls load all seven map slots, enable/clear channels, visibly open the resource picker and assign a different image with changed pixels, edit projections numerically and through translate/rotate/scale viewport gestures, cancel with Escape, edit channel blending, resize, save/reopen and export eight maps matching the material pixels. File-picker results are injected; native OS picker interaction is not qualified. Screenshots of bitmap previews, the open picker and projection controls were inspected.
- Regression suites: 27/27 transaction checks and 13/13 persistence checks pass. Full feature suite remains 101/102, with only the known baseline low-flow failure.
- Frozen v2 fixture and portable v3 roundtrip pass; all 16 reference maps remain unchanged. Application/test sources parse and `git diff --check` passes. CPU material validation added to CI; remote execution remains unverified.
- Successful resolution changes clear global GPU undo history; this is stated beside Apply. Failed changes retain the open set and history. Cross-resolution raster instances remain guarded. Viewport transform tools edit mapping parameters; warp remains T17.

## T06 qualification

Single-agent implementation; no delegated conversation copies. Full test output saved under `.artifacts/t06-*.log`.

- `tests/effects_check.py --gpu .artifacts/effects-t06-qualified`: 6/6 scenarios pass. Covers archive validation, unresolved/cyclic dependencies, ordered painted corrections, real independent strokes and undo/redo, stable renaming, v4 save/reopen, copy/move/delete/resize ownership, channel-scoped effect blending, geometry, native library storage and raster instance guards.
- `tests/effects_ui_check.py .artifacts/effects-ui-t06-qualified`: 15/15 assertions pass. Every content/mask editor renders; actual controls create/enable paint, target and stroke it, select persistent anchors, pick baked IDs, restrict geometry, and save/reopen the independent pixels. Screenshot inspected.
- Combined regression: 27/27 transaction and 13/13 persistence checks pass. Frozen legacy project retains all 16 reference textures. Full feature suite remains 101/102; only the known low-flow failure remains.
- CPU effect archive checks added to CI; remote execution unverified. Independent paint projects require v4-aware builds; ordinary projects remain v3. Geometry masks support part IDs 0–1023. No commit or release created.

## T07 qualification

Single-agent implementation, preserving the existing uncommitted checkout. Details,
API/platform limits and manual tablet procedure are in [BRUSHES.md](BRUSHES.md).

- `tests/brush_check.py --gpu .artifacts/brush-t07-final`: 7/7 CPU/GPU scenarios pass. Pressure normalization/fallback and native message dispatch, pressure size/flow and stroke opacity, frozen stroke sizing, history-independent jitter seeds, alpha inversion, seam crossing/backface rejection, seven-channel projection, portable reopen and seven pixel-matched EXR exports.
- `tests/brush_ui_check.py .artifacts/brush-ui-t07-final`: 35/35 actual UI assertions pass. Controls, alpha selection/inversion, pressure size, opacity, seven projection slots/isolated clear, viewport pressure routing, seed capture, undo/redo, portable save/reopen, continued mouse painting and export. Projection, jitter and tablet-status screenshots visually inspected. OS file-dialog results injected.
- One final regression pass: 27/27 transaction, 13/13 persistence, 6/6 effect and 21/21 export scenarios pass. Frozen v2 settings/all 16 reference maps and portable v3 roundtrip pass. Full feature suite remains 101/102; only known low-flow accumulation fails (0.999). Mirror/radial painting, stencil placement, clone and smudge pass.
- Native Windows CPython/RTX 4050 execution through the approved path. Logs: `.artifacts/t07-final-*.log`. CPU input contracts added to CI; remote execution unverified.
- Windows Ink observer installs and restores the GLFW window procedure successfully. **Physical tablet hardware was unavailable and is not certified.** Latest pressure is sampled each UI frame; no coalesced-event journal, tilt/eraser-end support or WinTab backend. Linux/macOS retain mouse pressure 1.0.
- No schema version change: independent mask-paint projects remain v4; ordinary projects remain v3. Optional `begin_stroke(..., seed=...)` is backward compatible; old brush dictionaries default to seed 17. No dependency, commit or release added.

## T08 qualification

- `tests/uv_check.py --gpu .artifacts/uv-t08-final`: 11/11 CPU/GPU scenarios pass, covering shared/scaled coordinates, pan/zoom, all channels, pressure/size spaces, erase, overlap/background policy, active-set isolation, live mapping changes, projection/stencil, clone/smudge, masks/quick mask, v4 reopen/continued painting, seven pixel-matched exports and channel diagnostic/wireframe rendering.
- `tests/uv_ui_check.py .artifacts/uv-ui-t08-final`: 26/26 actual UI assertions pass, including 2D-only, split, swapped panes and 125% UI scale, both-way 3D/UV edits, undo/redo, clone source selection, smudge, stencil/projection placement and independent mask save/reopen/export. Screenshots visually reviewed.
- One final regression pass: 7/7 brush, 27/27 transaction, 13/13 persistence and 6/6 effect scenarios pass. Frozen legacy settings/all 16 maps and portable v3 roundtrip pass. Full feature suite remains 101/102 with only known low-flow accumulation failure. Logs `.artifacts/t08-final-*.log`.
- Native Windows/RTX 4050. CPU coordinate checks added to CI; remote CI, other GPU platforms and physical tablet unverified. No schema/dependency change, commit or release. See [UV_PAINTING.md](UV_PAINTING.md) for APIs, overlap/background behavior and explicit tool limits.

## T09 qualification

- `tests/bake_controls_check.py --gpu .artifacts/bake-t09-final`: 8/8 CPU/GPU scenarios pass. Includes all-set rollback/cancel, independent settings, external-map validation and actual generator consumption, portable maps/rebake, undo/saved markers, environment rollback/display persistence and embedded native dependencies after source deletion.
- `tests/bake_ui_check.py .artifacts/bake-ui-t09-final`: 21/21 actual UI assertions pass. Editable weathering applied to a second mesh, real native drag/drop, all four native save categories, high-source staging/cancel, real bake/hit coverage and responsive progress with identical pixels, external map/preview, environment/emissive/alpha controls, save/reopen/export. Screenshots visually reviewed; file-dialog results injected.
- Final regressions: 11/11 UV, 27/27 transaction, 13/13 persistence and 6/6 effect scenarios pass. Full feature suite 101/102 retains only the known low-flow failure. The frozen legacy check initially detected an added empty bake field; serialization was fixed to omit it, and legacy/persistence/bake checks rerun successfully. All 16 original maps and portable v3 roundtrip pass without altered fixtures.
- CPU map validation added to CI; remote execution unverified. No dependency, commit or release added. Ordinary projects remain v3 and independent mask-paint projects v4. See [BAKE_DISPLAY_LIBRARY.md](BAKE_DISPLAY_LIBRARY.md) for APIs, platform/format limits and handoff. Logs `.artifacts/t09-final-*.log`.

## T10 qualification

- 9/9 CPU/GPU memory scenarios and 7/7 real UI assertions pass. Covers lazy/sparse allocation, exact region undo, budgets/eviction, OOM preservation, active-stroke cancel, resource lifecycle and v5 cross-resolution canonical sharing. Screenshot reviewed.
- Same RTX 4050 / 6141 MiB GPU, fixed 2K/4K workloads against isolated T00: estimated peaks 1604.8 → 1033.4 MiB and 6416.8 → 4131.5 MiB. Warm p50/p95: 36.9/38.1 → 38.1/41.7 ms at 2K; 1049.9/1744.4 → 124.6/131.2 ms at 4K. Six warm samples each. Scope, default budget and raw artifacts in [MEMORY.md](MEMORY.md).
- Final regressions pass 11 UV, 7 brush, 14 channel, 14 material, 27 transaction, 13 persistence and 6 effect checks. Frozen legacy settings/all 16 maps and v3 roundtrip pass. Feature suite stays 101/102 with only known low-flow failure. No goldens or legacy assertions changed.
- Ordinary projects remain v3 and ordinary independent mask paint v4; cross-resolution canonical raster projects require v5. No new dependency, commit or release. CPU CI extended; remote execution unverified. Logs `.artifacts/t10-final-*.log`.

## T11–T13 and T21 qualification / continuation

One primary agent continued the existing checkout; all prior uncommitted changes
remain. No commit or release was created.

- T11: 8 color CPU/GPU scenarios and 7 UI assertions pass. Optional OpenColorIO
  2.6.0 installed locally; pinned in requirements-managed.txt. External Blender
  5.1.2 Mikk reference and actual Cycles unlit color/world-normal renders pass.
  See architecture/COLOR.md for tolerances and excluded full PBR equivalence.
- T12: 7 journal/evaluation scenarios and 7 UI assertions pass. A real 1024→4096
  alpha fixture exactly matches direct 4096 evaluation; resized pixels differ by
  0.28619. Operation journals require v7. Legacy independent mask paint without
  a journal remains v4 and is explicitly migration-tested. See PAINT_OPERATIONS.md.
- T13: 10 CPU/GPU scenarios and 8 UI assertions pass revision preview, bounded
  surface reprojection, material retention/reassignment, cancel/failure preservation
  and portable pre-reimport recovery. See MESH_REVISIONS.md.
- T21: 7 CPU/runtime scenarios and 8 UI assertions pass installed Blender smart/
  angle unwrap, exact preservation of existing UVs, mixed-geometry retention,
  malformed geometry diagnostics, physical repeat and source/meter mesh delivery.
  Positive physical repeat requires v8; generated geometry alone uses existing
  formats. This initial pass was single-tile only; see the subsequent multi-tile
  extension below and UV_PREPARATION_SCALE.md.

Final T21 milestone pass: UV preparation 7, reimport 10, material 14, transaction
27, persistence 13, color 8, memory 9 and project controller 7 all pass. Frozen
v2 settings/all 16 reference maps and portable v3 roundtrip pass. Feature suite
remains 101/102 with only the original low-flow failure. No goldens were changed.
Logs: .artifacts/t11-final-*.log, t12-final-*.log, t13-final-*.log and
t21-final-*.log. Focused follow-ups cover required schema assertion migrations,
curvature preservation and source-transform validation. All Python files parse;
whitespace checks pass. CPU CI expanded; remote execution remains unverified.

Continue T14; T15–T19 remain unimplemented and T20 remains continuous. Do not infer
UDIM support from the single-tile UV backend or claim all Painter workflows done.
Preserve this uncommitted state. Physical tablet certification, other platform
graphics/runtime qualification and the Adobe conversion corpus remain unrun.

## T14 backend continuation (2026-10-28)

Material-owned Engine tile APIs now support one material on 1001/1002/1011,
continuous batch UV paths, one-action undo/redo, detached per-tile bakes/composites,
base/independent masks, portable v9 persistence, native operation resize/evaluation,
UV-preserving staged mesh revision with checkpoint recovery, and atomic UDIM export.
Metadata remains one editable tree per material. Tile-local anchor captures and
multi-material pixel isolation are checked. Ordinary independent mask paint without
a journal remains v4; existing non-tiled formats retain their version rules.

Regression qualification: tile foundation 12, material tiles 20, CPU export 23,
UV 11, journal 7, reimport 10, memory 9, transactions 27, persistence 13, material
14 and color 8 all pass. Frozen v2 settings/all 16 maps and portable v3 roundtrip
pass. The feature suite remains 101/102, with only the original low-flow result
0.999. No goldens or baseline assertions changed. Logs: .artifacts/t14-final-tiles.log,
t14-final-material-tiles.log, t14-final-export.log, t14-final-uv.log,
t14-final-journal.log, t14-final-reimport.log, t14-final-memory.log,
t14-final-transactions.log, t14-final-persistence.log, t14-final-material.log,
t14-final-color.log, t14-final-legacy.log and t14-final-feature.log.

T14 stays in_progress. Continue with interactive tiled input/rendering, revision-
keyed derived caching, tile list/grid/isolation, sequence controls and external
bake-map sequences. Complete remaining raster edits, duplication/instances, clone/smudge/quick
mask, changed-UV/topology reprojection and desktop acceptance. Unsafe legacy raster
edits reject explicitly on tiled owners. Current derived maps rebuild per evaluation;
large tiled workloads and the UI are not qualified. See architecture/TILES.md.
No dependency, agent, commit or release added. Existing uncommitted work preserved.

Image-sequence follow-up: explicit UDIM/file assignments now persist portably,
survive source deletion/resize, report missing/unassigned tiles and support resource
relink undo/redo. Decode/upload errors reject evaluation instead of substituting a
constant. Two additional CPU checks run in the existing tile CI entry point.
After this addition, the affected tile, persistence, transaction, export and frozen
legacy checks were rerun; the broad feature/color/etc. results above are from the
preceding complete pass. No baseline assertion or golden was changed.

Raster follow-up: clear paint, add/fill base mask and paint-effect fill now update
tile backing and immutable bases with undo/redo, rather than touching legacy-only
textures. Superseded owner/target operations are removed; masks/defaults persist
through resize and portable reopen. All seven channels paint/erase across the
boundary; projection uses one global view. A real 1K-to-2K replay matches direct
2K pixels exactly with four evictions under a 40 MiB tile-resident budget (tracked
texture peak 923 MiB, not total VRAM). Evidence:
.artifacts/material-tiles-t14-final/native-replay-1k-2k.json. Affected tile, memory,
transaction, persistence and frozen legacy checks were rerun after this addition.

## T14 browser continuation (2026-10-28)

The Material tiles browser is available from Texture Set Settings and the Viewport
command/palette. It provides tile selection/isolation, UV-grid fit/zoom/pan,
channel diagnostics, per-tile image assignment/removal and missing-file reports.
Its batch UV path tool paints on release across 1001/1002 as one undo action,
freezes brush resources/settings at pointer down, samples pressure, and supports
Escape/close/target-change cancellation. It is not the main viewport live-stroke
pipeline. Main 3D/2D views still sample legacy pixels and reject tiled live strokes;
use the browser for actual tiled previews. T14 is still in_progress.

A separate disposable preview cache retains only display-ready thumbnails, with
64 MiB resident budget, compressed backing and leases through ImGui submission.
Generation keys cover document/material/source, selected mask, channel/resolution,
color and image/high-source file stamps. Browser thumbnails are at most 256px;
authored resolution is unchanged. Native lower-resolution evaluation now replays
only the requested tile. Full bakes/composites still rebuild on cache misses and
are not retained in this cache. Preview state is omitted from archives/history.

23/23 Engine GPU scenarios and 17 actual browser UI assertions pass. New cases
cover preview reuse/eviction/invalidation, save without authored pins, managed
color/data previews and early rejection of invalid journal viewport dimensions.
UI checks cover actual canvas boundary painting, frozen brush values, cancellation,
navigation, isolation, typed image paths, sequence removal and portable save.
Screenshot .artifacts/tiles-ui-t14-final/tiles.png visually reviewed. Hardware
tablet sampling, other GPU platforms and the full tiled main viewport remain
unqualified. No dependency, extra agent, commit or release added.

One final regression pass after integration: foundation 12, tile Engine 23, export
23, UV 11, journal 7, reimport 10, memory 9, transactions 27, persistence 13,
material 14, color 8 and project controller 7 pass. Actual UI assertions: tile 17,
UV 26 and memory 7 pass. Frozen v2 settings/all 16 maps and portable v3 roundtrip
pass. Feature remains 101/102 with only the known low-flow failure (0.999).
Logs: .artifacts/t14-final-*.log, including tile-ui, uv-ui, memory-ui and
project-controller. Python parsing and whitespace checks pass. Existing
uncommitted changes and the ordinary independent-mask v4 contract are preserved.

Continue T14 with correct main-viewport tiled shading/picking and continuous
surface/UV strokes, full derived bake/composite caching, clone/smudge/quick mask,
polygon fill, duplication/instances, changed-UV/topology reprojection, external
bake-map sequences and larger asset acceptance. T15–T19 remain pending; do not mark
them or full T14 acceptance complete based on the browser's batch path tool.

## T14 main 3D viewport continuation (2026-10-28)

Main 3D rendering now streams one material/tile at a time from a disposable native-
precision output cache (256 MiB resident limit plus global tracked texture budget).
The viewport uses at most 512px tile maps independently of author/export resolution.
Cached composites/bakes preserve texture precision and sampler state; no editable
layers or authored leases are retained. Eviction restores exact cached bytes.
Partial allocation failure releases the incomplete cache page. Deterministic
missing-tile errors cache per revision, report visibly, and clear after resources
are resolved. Pause retains the cached generation until refresh resumes.

A separate tiled shader translates global UVs to tile-local sampling and clips
fragments at the half-open tile boundary. Crossing faces retain their original
geometry/interpolation. Picking retains global UVs/source triangles. The ordinary
scene shader path is unchanged. Managed color and data diagnostics are qualified.
The main 2D grid and continuous live strokes remain pending; browser paths still
paint on release. Neighboring-tile gutters for height-derived normals/filters,
clone/smudge/quick mask, polygon fill, duplication/instances, changed-UV/topology
reprojection, bake-map sequences and larger workload acceptance are still open.

25 Engine GPU scenarios and 21 actual UI assertions pass. New GPU evidence covers
distinct 1001/1002/1011 colors on crossing faces, warm-cache reuse, exact eviction
restore, property invalidation/pause, global picking, managed scene color/data,
portable save with populated caches, missing-resource retry suppression, partial
cache OOM preservation and complete project texture cleanup. Browser/UI checks
also verify actual 3D cache use, missing-tile reports, resolved-warning clearing and
released draw leases. Screenshot .artifacts/tiles-ui-t14-final/tiles-3d.png reviewed.

Final regression: tile foundation 12, tile Engine 25, export 23, UV 11, journal 7,
reimport 10, memory 9, transactions 27, persistence 13, material 14, color 8 and
project controller 7 pass. Actual UI: tile 21, UV 26 and memory 7 pass. Frozen v2
settings/all 16 maps and portable v3 roundtrip pass. Full feature remains 101/102
with only the known low-flow result (0.999). Logs .artifacts/t14-final-*.log.
Memory UI initially reused a prior run's saved one-step limit; its fixture now
sets explicit starting budgets without deleting config or weakening assertions,
and the same output/config path passes on rerun. Final focused checks also cover
the resolved-warning UI correction. Python parsing and whitespace checks pass.
Existing uncommitted changes, independent-mask v4 behavior and prior fixtures are
preserved. No extra agent, dependency, commit or release added. T14 stays open;
T15–T19 have not been marked complete.

## T14 main 2D grid and live UV continuation (2026-10-28)

The main 2D grid now shares the 3D material-output cache, clips tiles independently,
preserves global wireframe/picking, frames sparse layouts and supports pan/zoom.
Live UV paint, erase, base masks, independent paint-mask effects and projection
cross tile boundaries before release. One frozen native dab stream retains
pressure/time/seed and per-dab view provenance; bounded transient tile pages retain
coverage and opacity accumulation across eviction. Release commits one undo;
Escape and failed feeds restore pixels/flags. Save, selection and property edits
finish the live stroke in history order. LOD previews replay uncommitted dabs.

Rotated square-alpha corners reach adjacent tiles. Missing frozen brush files
report diagnostics and recover after repair. Referenced image interpretation
changes reject to preserve native replay. Legacy native shelf saves and raster
imports reject before archive publication/uploads rather than omit tiled pixels;
procedural content remains available. Canonical higher-resolution legacy rasters
retain their original base through tile migration, portable reopen and resize.

36 Engine GPU scenarios and 36 actual tile UI assertions pass. Actual screenshots
tiles-2d.png and tiles-live-uv.png reviewed. Final regression: tile foundation 12,
tile Engine 36, export 23, UV 11, journal 7, reimport 10, memory 9, transactions 27,
persistence 13, material 14, bake controls 8, color 8 and project controller 7 pass.
Actual UI: tiles 36, UV 26 and memory 7 pass. Frozen v2 settings/all 16 maps and
portable v3 roundtrip pass. Feature remains 101/102: only known low-flow (0.999).
The final native-import guard also passes focused tile/bake/persistence reruns.
Logs: .artifacts/t14-final-*.log. Independent mask-only projects remain v4;
explicit tiled projects remain v9. All existing uncommitted changes preserved.

T14 remains in progress: live 3D tools, neighboring-tile gutters, advanced raster
tools, duplication/instances, changed-UV/topology revision, external bake sequences
and larger workload acceptance remain open. T15–T19 remain pending. One agent;
no new dependency, commit or release.

## T14 polygon fill and material picker continuation (2026-10-28)

The 3D material picker now samples the hit material/tile at authored resolution,
using tile-local UVs and the existing managed color contract. Brush application
is atomic on resource errors. Actual mesh picks cover 1001/1002/1011; Engine
checks also cover all seven channels and picking another material without changing
the active set. Native raster shelf imports are guarded; procedural native shelf
imports remain available on tiled materials and evaluate across all addresses.

Polygon fill now stages paint/erase, base masks and independent paint-mask effects
across selected source faces and tile boundaries. It commits one undo action;
failure preserves live pixels, mask flags and history. The affected owner's target
becomes a raster base at current resolution; only its native operations are
flattened. Other owners/targets retain native replay. The brush panel states that
later resizing resamples this target. Portable save/reopen and resize retain the
fill; disabled-mask recreation matches the ordinary single-tile default. Live UV
mask recreation now follows the same rule; cancellation restores hidden mask bytes.
Screenshot tiles-polygon-fill.png and its resolution disclosure visually reviewed.

40 Engine GPU scenarios and 43 actual tile UI assertions pass. Final regression:
tile foundation 12, tile Engine 40, export 23, UV 11, journal 7, reimport 10,
memory 9, transactions 27, persistence 13, material 14, bake controls 8, color 8,
project controller 7, actual tile UI 43, UV UI 26 and memory UI 7 pass. Frozen v2
settings/all 16 reference maps and portable v3 roundtrip pass. Full feature remains
101/102 with only known low-flow accumulation (0.999). Final focused tile/UI checks
also pass the disabled-mask restoration correction. Python parsing and whitespace
checks pass. Tile replacement/staging now preserves configured residency limits;
degenerate-only polygon selections remain no-ops without flattening native paint.
Final focused tile/UI, reimport, memory and persistence checks pass these fixes.
Logs: .artifacts/t14-final-*.log. No dependency, agent, commit or release
added. Existing staged/unstaged/untracked work and independent-mask v4 preserved.

T14 stays in_progress. Continue with live 3D surface dispatch, neighboring-tile
gutters, clone/smudge/quick masks, duplication/instances, changed-UV/topology
correspondence, external bake-map sequences and larger workload qualification.
T15–T19 remain pending; T20 remains continuous.

## T14 live surface painting continuation (2026-10-28)

Main 3D now uses the shared tiled stroke lifetime for live paint, erase, masks
and projection. One global surface dab stream dispatches through shifted-UV tile
meshes, preserving native world/screen/UV brush semantics. Conservative world
bounds include mirror/radial copies and world-adjacent surfaces on distant UV
tiles. Operations retain distinct surface/UV coordinates, camera views,
pressure/time/seed and frozen resources. Replay regenerates whole-mesh occlusion,
including other materials, then restores current picks. Bounded surface reimport
projects dabs/samples and regenerates tile rasters before commit; UV-only paint
retains its existing coordinates. Both require unchanged UVs/topology/materials.
Misses/normal disagreement reject. Cancel or allocation failure retains the source;
commit writes a portable pre-reimport checkpoint. Actual tile materials now appear
on both sides of the revision comparison preview.

Pick-buffer resizing stages replacements and retains readable prior targets after
partial failure. Offscreen replay/evaluation isolates viewport clipping. Regression
caught a cached paint framebuffer retaining a tiny scissor; paint passes now clear
clipping after binding targets. Seven-channel erase and affected painting suites
pass this fix. Independent GPU fixtures release renderer-owned pick targets so
the project texture-cleanup assertion continues to check project-owned storage.

47 Engine GPU scenarios and 49 actual tile UI assertions pass. New evidence covers
boundary writes before release, one undo, Escape, masks/cancel/OOM, per-view
projection/frozen images, whole-mesh occlusion, distant UV seams, mirror/radial
copies, cold LOD evaluation under a scissor, pick-buffer resize failure and bounded
surface revision staging/preview/cancel/commit/OOM/recovery. tiles-live-3d.png reviewed.
The tiled before/after surface-revision-comparison.png was also visually reviewed.
Surface replay at 64-to-128 matches direct
authoring exactly. A separate 1K-to-2K fixture also matches exactly, with five live
state evictions under a 96 MiB resident limit and isolated tracked texture peak
958 MiB. Evidence: .artifacts/material-tiles-t14-final/surface-replay-1k-2k.json.
This is color-only; all-channel 4K and large production assets remain unqualified.

Final regression: foundation 12, tile Engine 47, export 23, UV 11, journal 7,
reimport 10, memory 9, transactions 27, persistence 13, material 14, bake controls 8,
color 8 and project controller 7 pass. Actual UI: tiles 49, UV 26, reimport 8 and memory 7 pass.
Frozen v2 settings/all 16 maps and portable v3 roundtrip pass. Full feature remains
101/102 with only known low-flow (0.999). Affected suites were rerun after the
scissor fix; the larger surface fixture and bounded revision follow-up also pass.
Python parsing and whitespace checks pass. Logs: .artifacts/t14-final-*.log.
Independent-mask projects without journals remain v4; tiled projects remain v9.
Existing uncommitted changes preserved. One agent; no dependency, commit or release.

T14 remains in_progress: gutters, clone/smudge/quick masks, duplication/instances,
changed-UV/topology correspondence, external bake-map sequences
and larger workload acceptance remain. T15–T19 remain pending; T20 is continuous.

## T14 layer/group duplication continuation (2026-10-28)

Duplicate layer now copies a tiled subtree with fresh layer/effect identities,
exact tile pixels, canonical raster bases, native replay, mask defaults and image
sequences. Settings and subsequent paint/reset/relink edits remain independent.
Internal anchor references remap to copied sources; external identities remain
stable. Legacy name references resolve on detached definitions and publish with
the copy, preventing the original reference from becoming ambiguous. One combined
tile_stack undo action restores the tree, tile storage, native operations,
selection and original reference bindings. Its compressed CPU payload counts
toward history budgets. History cleanup retains live sources and releases detached
copies. Pinned cache/authored leases reject replacement before any store closes.

50 Engine GPU scenarios and 55 actual tile UI assertions pass. New checks cover
independent paint/masks, canonical higher-resolution base copying through portable
reopen/resize, group anchors/image sequences, exact undo/redo, allocation and
validation failure preservation, usable thumbnails after pinned-read rejection,
and detached-copy cleanup when redo is dropped. The registered desktop duplicate
command retains both boundary tiles and restores tree/selection on undo/redo.
Screenshot tiles-duplicate.png visually reviewed.

Final regression: tile foundation 12, tile Engine 50, export 23, UV 11, journal 7,
reimport 10, memory 9, transactions 27, persistence 13, material 14, bake controls 8,
color 8 and project controller 7 pass. Actual UI: tiles 55, UV 26, reimport 8 and
memory 7 pass. Frozen v2 settings/all 16 maps and portable v3 roundtrip pass. Full
feature remains 101/102 with only known low-flow (0.999). Final focused history
cleanup checks also pass. Logs: .artifacts/t14-final-*.log. Independent-mask-only
projects remain v4 and tiled projects remain v9. Existing uncommitted changes
preserved; one agent, no dependency, commit or release added.

T14 remains in_progress: gutters, clone/smudge/quick masks, tiled clipboard forest
copying/cross-material instances, changed-UV/topology correspondence, external
bake-map sequences and larger workload acceptance remain. T15–T19 remain pending.

## T14 acceptance closure (2026-10-28)

T14 is verified against the five deliverables and acceptance fixture in the
implementation plan. See architecture/T14_ACCEPTANCE.md for requirement-to-test
traceability and explicit limits. Prior progress entries accumulated broader
extensions into the pre-verification checklist; the final record distinguishes
the plan's material/tile workflow and instance audit from those unsupported tools.
It does not claim cross-material instancing, every raster tool, arbitrary topology
preservation, automatic packing or full Painter parity.

Height-derived normals now read streamed neighbor height/coverage strips with
O(resolution) edge storage. Eight narrow world-position strips gate locally
continuous surfaces; nearby disconnected islands, outer and ambiguous edges clamp.
Horizontal/vertical borders match an independent central-difference plus authored
normal reference. Reopen is exact. Neighbors evaluate sequentially before the
center tile; original normal/bake combination and legacy behavior are retained.
General cross-tile blur/warp/filter neighborhoods remain unqualified.

The combined acceptance fixture has one material on 1001/1002/1011 and a second
on 1001/1002. A native boundary stroke survives portable reopen, bounded revision
with recovery checkpoint, 128-to-512 resize, eviction and atomic delivery of ten
textures plus two material JSON files. Missing-image diagnosis/repair, identities
and delivered boundary pixels are checked. Evidence:
.artifacts/material-tiles-t14-final/t14-acceptance.json.

The actual desktop fixture also reopens portably, uses Choose/Stage/Commit revision
buttons and tiled before/after comparison, preserves identities/checkpoint,
refreshes after 64-to-256 resize and delivers all three named UDIM color maps
with matching boundary pixels. 53 Engine GPU scenarios and 63 tile UI assertions
pass. Final regression: foundation 12, export 23, UV 11, journal 7, reimport 10,
memory 9, transactions 27, persistence 13, material 14, bake controls 8, color 8,
project controller 7; actual UV UI 26, reimport UI 8 and memory UI 7 all pass.
Frozen v2 settings/all 16 reference maps and portable v3 roundtrip pass. Feature
remains 101/102, solely the known low-flow accumulation failure (0.999). The final
surface-continuity refinement passes focused gutter checks and the complete tile
Engine suite. Logs: .artifacts/t14-final-*.log.

Independent-mask projects without a journal remain v4; explicit tiled projects
remain v9. All uncommitted changes preserved. One agent; no new dependency,
commit or release. T15 is next. Guarded extensions remain visible in the acceptance
record, including clone/smudge/quick masks, cross-material instances/clipboard,
changed-UV/topology reprojection and external bake-map sequences. Physical tablets,
other GPU platforms and all-channel 4K/large production assets remain unqualified.


## T15 qualification

Named projection pairing, indexed custom cages, cage-to-low crossing detection,
1x/2x/4x supersampling and painted ray/distance corrections are implemented through
the native staged baker and mesh-map controls. AO/thickness explicitly include
self-occlusion and all selected high parts. Shared bake parameters preserve each
material's correction owner. Binding, raw paint and rebake have undo; portable
reopen and tiled resolution replay retain identities and field pixels. Saved maps
remain usable when cage/field sources change or disappear, with actionable source
diagnostics. See ADVANCED_BAKING.md for usage, schema and scope.

- `tests/advanced_bake_check.py --gpu .artifacts/bake-t15-final`: 13/13 scenarios
  pass (three CPU contracts, ten GPU scenarios). Thin-gap crossings and overlapping
  material UVs have explicit diagnostic-color assertions; flat normal/height maps
  have analytical references. Includes painted skew/range recovery, multi-material
  ownership, tiled cage/field resize, stale/missing sources and allocation rollback.
- `tests/advanced_bake_ui_check.py .artifacts/bake-ui-t15-final`: ten actual desktop
  assertions pass. Source controls, field preview and diagnostic screenshots reviewed.
- One 22-suite regression pass: 21 suites exit zero; feature remains 101/102, solely
  the known low-flow accumulation failure (0.999). Tile foundation/Engine/UI,
  export, UV, journal, reimport, memory, transactions, persistence, materials, bake
  controls/UI, color, project controller and frozen v2/portable v3 compatibility pass.
  Logs: `.artifacts/t15-final-*.log`.
- After the final cage-source diagnostic fix, advanced baking, persistence and
  frozen v2/v3 checks pass again. CPU-only entry point passes its three contracts
  and skips ten GPU scenarios; compileall and diff whitespace checks pass.

Advanced settings activate v10 only when used. Ordinary independent-mask projects
without a journal remain v4; ordinary tiled projects remain v9. Custom validation
and sampled crossing detection do not certify arbitrary cage self-intersections or
manifoldness. Automatic cages and production-scale/cross-platform GPU qualification
remain outside this acceptance. All uncommitted work is preserved; one agent, no
new dependency, commit or release. T16–T19 remain pending.


## T16 qualification

Native graph v1 explicitly stores input/constant, six-octave grunge, ramps/gradient
maps, UV transforms, directional warp, sharpen and mixing nodes. The effect editor
exposes recipes, channel, node parameters and gradient stops through normal undo.
DAG validation, 32-node and 256 MiB intermediate limits bound evaluation. Content
and mask effects run through the existing compositor, including native tile evaluation.

Painter reports separate source read/version/feature coverage, retained editability,
notes/skipped/unexecuted operations, unvalidated source appearance and replay status.
Unknown HBO metadata survives project storage. Full-size image extraction is content
addressed; malformed/truncated or unsupported HDR images report errors rather than
silent reduction/clipping. Available bitmap stroke alphas and named jitter fields
are mapped; source symmetry/proprietary tips remain explicit unqualified metadata.
Native filter mappings replace silent sharpen/warp skips and average-color gradients.

Replay has visible session/per-layer budgets, progress/cancel, no point decimation
and whole-stroke publication. Pending source jobs/cursors/pixels survive portable
reopen; changed target checkpoints reject continuation. Partial cancelled strokes
publish no pixels. Pending alpha resources also support portable extraction and
resource relink/undo. Initial decoding remains synchronous. Tiled Painter replay
rejects explicitly; native tiled graph evaluation is independently verified.

- `tests/procedural_import_check.py --gpu .artifacts/procedural-t16-final`: 13/13
  scenarios pass (six CPU, seven GPU), including analytic filter references, graph
  undo/portable/tile output, exact resumed-vs-uninterrupted paint, partial-stroke
  cancellation, stale target guards, alpha relink/undo and invalid-budget preservation.
- `tests/procedural_import_ui_check.py .artifacts/procedural-ui-t16-final`: ten
  actual desktop assertions pass: recipe/node editing, undo, incomplete state,
  portable continuation, shared report command/view and JSON export. Screenshots reviewed.
- `tests/substance_compatibility.py .artifacts/substance-t16-final --render`: 11/11
  real source fixtures pass. Inline/registry preset versions and Painter 9.1.0 /
  project data version 80 are represented. Source hashes are unchanged; native
  64px reference maps have portable maximum difference 0. Source appearance against
  Painter stays explicitly unvalidated. Matrix and images remain in that artifact folder.
- One 27-suite final regression: 26 zero exits; feature remains 101/102 solely the
  known low-flow accumulation failure. After final alpha relink handling, focused
  procedural/UI, persistence and frozen v2/portable v3 compatibility pass again.
  Logs: `.artifacts/t16-final-*.log`. CPU-only checks and compileall are included in CI;
  hosted CI is unrun. No external sbsrender/sbsbaker/sbsupdater command was found on PATH;
  execution stays disabled behind an isolated discovery module.

Native graphs/import reports/continuation activate v11 only when used. Ordinary
independent-mask projects without journals remain v4, tiles v9 and advanced bakes
v10. Compiled Adobe graph identity, enabled source symmetry, UDIM Painter replay,
production-resolution corpus references and cross-platform GPU behavior are not
claimed. See PROCEDURAL_IMPORTS.md. All uncommitted work preserved; one agent,
no dependency installation, commit or release. T17–T19 remain pending.


## T17 qualification

Surface objects persist on fill-material layers as triangle/barycentric anchors,
width/pressure profiles, material/tip references and deterministic UV evaluation.
Editable polylines, ribbon UVs and closed polygon regions regenerate at the requested
resolution. Portable font records preserve live label text, origin, normalized em
size, tracking, leading and alignment. The shared projection manipulator stores
validated four-corner projective warp and explicit decal clipping; UV and planar
placement remain independent of the camera. Material maps/parameters stay editable.

Layer > Paths, ribbons and text provides actual point capture/movement, typography
and font selection. Standard property transactions provide undo. Supported indexed
geometry revisions retain object identity and appearance; changed topology/UVs/
material assignments reject before publication. Missing fonts retain label data,
report errors and support validated resource relink/undo. User-mask bypass retains
intrinsic object coverage. Native tile evaluation uses global UV placement.

- `tests/authored_check.py --gpu .artifacts/authored-t17-final`: 14/14 scenarios
  pass (four CPU contracts, ten GPU scenarios). Covers ownership/ambiguous UVs,
  region/warp validation, path profiles and edits after portable reopen/resize,
  exact text reference equality at the new resolution, UV/planar placement,
  camera-stable ribbon maps, tiled ribbon/label boundaries and explicit cropping,
  font recovery/undo, mask bypass, mesh-revision guards and the one-shot helper.
- `tests/authored_ui_check.py .artifacts/authored-ui-t17-final`: 12 actual desktop
  assertions pass. Screenshots of point markers, editable material coverage and
  font controls were reviewed. Material UI regression also passes all 47 assertions.
- One 30-suite final regression exercised T17/T16/T15, tile foundation/Engine/UI,
  export, journal, UV, material controls, memory, transactions, persistence, color,
  reimport, original bake UI, project controller and frozen v2/portable v3 output.
  The new CPU-preview protocol regression was repaired without changing assertions;
  focused authored/UI/effects/reimport checks pass afterward. Only the known feature
  low-flow accumulation failure remains (101/102). Logs: `.artifacts/t17-final-*.log`.
- CPU-only authored entry point, compileall and diff whitespace checks pass. CPU
  contracts are included in CI; hosted CI remains unrun.

Authored/warp/decal data activates v12 only when present. Ordinary independent-mask
projects without journals remain v4, ordinary tiles v9, advanced bakes v10 and
native procedural/import data v11. Paths are indexed-chart UV polylines; arbitrary
geodesic/seam traversal, spline editing and changed-UV/topology reprojection are
not implemented. Region holes, complex-script typography, large production object
stacks and cross-platform GPU behavior remain unqualified. These are explicit
limits in AUTHORED_OBJECTS.md. All uncommitted changes preserved; one agent, no new
dependency, commit or release. T18–T19 remain pending.


## T18 qualification

Single-agent implementation with targeted reads and focused checks, followed by
one 32-suite regression pass. All tests/artifacts remain ignored and local. No
commit, push, dependency install or CI test lane was added.

- `tests/user_channels_check.py --gpu .artifacts/channels-t18-final`: **16/16**
  scenarios pass (three CPU, thirteen GPU/runtime), including sparse allocation,
  scalar masks/effects/graphs, ordinary anchor dependencies, groups, managed data,
  native brush/cancel/undo, portable v13, detached and resized replay matching a
  directly painted 128px reference, arbitrary alpha packing, stale shader
  manifests, tile replay/cache/UDIM output, physical picking and legacy v4 masks.
  Definition/count/output-budget failures reject before publication/allocation.
- `tests/user_channels_ui_check.py .artifacts/user-channels-ui-t18-final`:
  **16 actual desktop assertions** pass. Actual controls create/enable/edit,
  insert scalar effects, preview and paint UV pixels, select an arbitrary packing
  component, prepare exports, restore/resize and bind/select the shading model.
  Screenshots of scalar paint and shader controls were inspected.
- Blender **5.1.2/Cycles** renders actual exported linear textures and both target
  material fixtures. F0 maximum error **0.00002198**, glossiness **0**, coat
  **0.000390625**, coat roughness **0.00004883**; independent gloss and coat changes
  affect actual BSDF renders. Signed displacement reads **0.0049999999 m**, matching
  Strata's **0.5 project-unit** surface offset for a centimeter-source fixture.
  Packed editable reference asset and full report:
  `.artifacts/channels-t18-final/blender-reference/reference.blend` and
  `.artifacts/channels-t18-final/reference-results.json`. This verifies texture
  interpretation, independent controls and physical conventions, not exact
  renderer lighting/BRDF equivalence.
- Final 32-suite pass: all suites pass after updating T04's exact source-list
  expectation for the three new sources. The existing feature suite remains
  **101/102**, solely the known low-flow accumulation failure. Its assertion and
  golden pixels were unchanged. The source-list assertion still requires exact
  membership, now including coat, coat_roughness and displacement_meters.
- After the source-list update and allocation/semantic guards, targeted channel,
  user-channel/UI, memory, journal, material-tile and export reruns pass. Application
  compileall and working-diff whitespace checks pass. Frozen v2 outputs and portable
  roundtrip remain unchanged; all previous authored/procedural/material/brush/UV,
  bake, transaction, persistence, tile and managed-color suites pass.
- Existing uncommitted work and test ignores/index removals were preserved.
  CI remains source-syntax-only as requested. T19 is next; tessellation, tiled
  displacement, custom clone/smudge/projection, transmission/scattering/anisotropy
  and exact target BRDF parity are outside this qualified T18 scope.


## T19 qualification

Single-agent implementation with targeted reads, focused CPU/GPU/desktop/runtime
checks and one final **34-suite regression pass**. No commit/push, dependency
installation or test CI restoration. Existing changes and local test ignores/index
removals were preserved.

- `tests/delivery_check.py --gpu .artifacts/delivery-t19-final`: the initial **18/18**
  scenarios pass (ten CPU, eight GPU/runtime). A final targeted fractional-opacity
  case passes through both import paths (`.artifacts/t19-opacity.log`), bringing
  focused T19 coverage to **19 scenarios**. The same script now includes that case.
  Coverage includes archive paths/inventory/integrity/budgets, atomic writer and
  replacement failures, geometry units, explicit extension version/loading,
  argument preflight and GUI bridge, native UV paint/portable reopen/batch delivery,
  target GLB/ZIP reconstruction, managed HDR/coat, independent F0/glossiness,
  displacement and real optional Cycles rendering/failure preservation.
- `tests/delivery_ui_check.py .artifacts/delivery-ui-t19-final`: **10 actual desktop
  assertions** pass. File menu opens the panel, controls select format/destination/
  resolution, real ZIP and GLB outputs contain mesh/material data, completion is
  visible, unsupported GLB preserves its previous destination, and a native
  Extensions menu callback edits the material through the versioned API.
  Screenshots were visually inspected.
- Actual **Blender 5.1.2/Cycles** imports a two-material reference asset with a UV
  color pattern, mirrored UVs, matched MikkTSpace and tilted normal. Rendered target
  semantic pixels match native GPU output. ZIP maximum differences: base color
  **0.00004941**, roughness/metallic/opacity **0.00000006**, world normal
  **0.00000685**. GLB (PNG8) differences: color **0.00266990**, roughness
  **0.00176549**, metallic **0.00193637**, world normal **0.00017822**, opacity **0**.
  Fractional alpha additionally matches both target material links and glTF BLEND
  semantics. Geometry/material ownership and packed editable `.blend` references
  are checked, not just filenames or node presence.
- Separate actual target cases cover independent F0/glossiness, clearcoat and
  managed HDR emission in both supported formats; signed meter displacement
  reconstructs the expected existing vertices. Full preview/target BRDF lighting
  identity is explicitly not claimed. Target assets and comparisons are under
  `.artifacts/delivery-t19-final/*-reference`, `managed-*` and `opacity-*`.
- Optional isolated Cycles renders a nonuniform **64px PNG at four samples** from
  the production bundle/importer. Injected render failure leaves its destination
  unchanged, and missing/unknown runtimes report actionable errors without output.
  Particle simulation remains independently optional and unavailable.
- The documented sample batch job also executes successfully from an isolated
  copy under `.artifacts/delivery-example-t19`, including native project creation,
  Mikk preparation, portable save, Blender ZIP and actual GLB output. The versioned
  extension module is loaded only by an explicit command-line option. Standalone
  CLI operational logs stay on stderr and JSON results on stdout.
- Final 34-suite regression: **33 suites exit 0**; the feature suite remains
  **101/102**, solely the known low-flow accumulation failure. Frozen v2 reference
  pixels/portable roundtrip and prior channel/graph/authored/material/bake/UV,
  paint history/reimport/memory/transaction/persistence/tile/color/UI suites pass.
  No assertion or golden for the low-flow failure was changed. Evidence logs use
  `.artifacts/t19-final-*.log`; compact results are `.artifacts/t19-qualification.json`.
- Source compileall and working-diff whitespace checks pass. GUI and console
  packaging recipes include readable external Blender source assets; recipes and
  example sources parse. **Frozen builds were not run** because PyInstaller is
  absent; no dependency was installed. CI remains source-syntax-only and all test
  files remain ignored and absent from the Git index.

Qualified target scope is Blender; Unreal/Unity setup integrations, UDIM
mesh/material bundles, arbitrary legacy-to-Mikk normal equivalence and frozen
release binaries are unclaimed. These limits do not remove the existing texture
presets or T14 per-UDIM texture delivery. T20 remains open for separate release,
hardware, platform and deferred-capability qualification.


## T20 local qualification increment — November 2, 2026

Single-agent implementation; existing uncommitted changes and ignored/untracked
local tests were preserved. Product changes are limited to non-reserving compound
memory admission and Stroke initialization preflight; paint math/project versions
remain unchanged. CI now parses examples, both source launchers and packaging
recipes separately, and accurately names the source-syntax job. It still contains
no uploaded CPU/offscreen test suite, honoring the user's offline-tests instruction.
Remote execution is not claimed.

- Added a local five-lane **45-check** matrix/report runner, a prohibited-GPU/UI/
  Engine-import guard for seven portable CPU entry points, and seven reporting/
  classification contracts. Reports include actual working-source/test/matrix /
  baseline hashes, dirty Git state, commands, log hashes, runtime versions and
  explicit known/failed/not-run/manual states. Exact known signatures cannot hide
  an additional failure or traceback. Default release status stays false; an
  explicit development mode reports an engineering subset without granting waivers.
- Original full run `.artifacts/t20-final/report.json`: **43 passed**, known feature
  low-flow failure **101/102**, and one newly exposed 4K custom-workload budget
  failure. **Legacy UI logic passed** this run; its earlier splitter-cursor failure
  is historical, not a current failure. This original report remains immutable.
- Investigated the budget boundary and reproduced a real 128px late-allocation
  ownership defect: empty C/R channels could survive rejected stroke initialization.
  `strata/memory.py` now checks a compound request without reserving bytes, and
  `strata/painter.py` checks targets/snapshots/buffers before allocating lazy channels.
  The old reproducer fails; the fixed **10/10 memory cases** pass. No global budget
  was raised and no brush/golden assertion was weakened.
- Focused post-fix matrix `.artifacts/t20-patch-verification/report.json`: **10/11
  passed**, solely known feature failure remaining, no unexpected failures; source
  and suite hashes unchanged during the run. This explicitly partial subset covers
  scalar paint/UI, native tiles, UV/UI, journal, memory, transactions, carried scene
  and performance. Additional **7 brush scenarios / 35 desktop assertions** pass.
  There was one broad regression pass, followed by these change-focused reruns.
- New carried-scene qualification passes **two full workflows**: two-material Mikk
  import, external bake, bitmap foundation, generator/anchor masks, real surface
  paint, UV correction, native asset save/apply/undo, portable reopen, independent
  resize, supported mesh revision, distinct maps and actual Blender reconstruction;
  plus a same-scene two-material/three-page variant with cross-page paint, portable
  reopen and correct per-UDIM pixels. Original source bitmap/high-poly hashes remain
  unchanged. Evidence is under `.artifacts/t20-patch-verification/workflow`.
- Target comparison uses output-resolution-matched managed linear Rec.709, a fixed
  interior mask and maximum absolute error tolerance **0.002**, unchanged from its
  first draft. Actual color error **0.00045639**; normal **0.00000769**; other scalar
  errors <= **0.00000012**. A wrong resolution/legacy-space comparison was corrected
  without changing goldens/tolerances. Managed PNG UDIM references use encoded
  sRGB space and **1/255** tolerance. Legacy high-contrast interpolation equivalence
  remains unclaimed.
- Benchmarks now separate **core** and **user-scalar** profiles at 512, 2048 and
  4096 pixels, nine warmed GPU-complete samples, first calls, actual OS process
  working/private memory and owned GPU estimates. Core 4K composite p50/p95
  **28.71/30.09 ms**; whole seven-sample stroke **144.43/182.35 ms**; estimated peak
  **3974.4 MiB**. The 4K user-scalar initial stroke correctly reports its default
  **5 GiB** limit with exact ownership/history/serial/live-byte rollback and no
  fabricated stroke timings. All six cases release to the **24-byte** engine
  baseline. Driver VRAM was not measured. Full distributions and all profile values
  are in VALIDATION.md and the focused performance JSON.
- Separate private source candidate: **128 files**, test/artifact/cache/Git paths
  excluded; all product/build-input hashes match the patched source report.
  Relocated import origin, CLI listing, explicit extension, native create/portable
  save/Blender ZIP/GLB batch, and six-frame real GUI rendering pass with isolated
  settings. Screenshot inspected. Candidate and report:
  `.artifacts/strata-t20-source-candidate.zip` and
  `.artifacts/t20-source-smoke/verification.json`. This is source-mode smoke using
  the established dependencies, **not frozen package qualification**.
- Application/examples/launchers and packaging recipes parse; working-diff
  whitespace checks pass. Tests remain ignored and absent from the Git index.
  No commit, push, dependency install, release publication or waiver was performed.

T20 intentionally remains **in progress**: low-flow resolution/release decision,
actual frozen builds (PyInstaller absent), physical tablet, other-platform runtime
and remote execution gates are still open. The planned public CPU/offscreen CI
lanes were not added because the user explicitly requires tests to stay offline.
See VALIDATION.md and RELEASE_GATES.md for profiles, commands, evidence semantics
and the manual protocols. Baseline signatures are never automatic release approval.


## T21 multi-tile preparation extension — November 2, 2026

Completed the deferred automatic multi-tile increment on the installed Blender
5.1.2/Windows/RTX 4050 runtime. New Project and Mesh Revision expose a per-material
1–64-page UV budget. The allocator keeps part/dihedral charts intact, orders by
surface area and assigns them deterministically to available page rectangles;
Blender performs the actual unwrap and island packing. Preserved valid UVs remain
exact. Full fixed pages can push generated geometry onto another page without
moving their existing charts. Materials retain separate ownership, UDIM columns
wrap after ten, and generated multi-tile projects automatically enter T14's tiled
paint/evaluation/save/export workflow. Both build recipes now retain the readable
external unwrap worker; this is source packaging support, not frozen validation.

Focused evidence: the original seven UV/scale/runtime checks still pass; seven
new CPU/Blender/GPU scenarios and twelve real desktop assertions pass. These
include strict-interior overlap checks, pixel padding, eleven occupied pages,
material identity, exact fixed UVs, actual per-page authored paint, undo/redo,
portable pixel equality, OBJ coordinates and UDIM delivery. Identical-layout
prepared revisions stage/cancel/commit; changed tiled layouts reject without
changing the open mesh or pixels. The CPU packing lane also passes with all GL
and UI imports prohibited.

Limits are explicit in UV_PREPARATION_SCALE.md: the tile count is a maximum;
intact smooth charts are not arbitrarily split, uniform density/optimal packing
is not promised, fixed charts must fit their budget pages, and conservative free
rectangles may reject irregular gaps. Existing fixed overlaps are not repaired.
T14's unchanged-layout/topology tiled revision policy still applies. T20 frozen,
physical-tablet, other-platform and remote qualification gates remain open.

Local checks and fixtures remain ignored and unindexed. The maintained local
qualification matrix now includes the original UV preparation, multi-tile CPU
and runtime suites, and the real preparation UI. The final combined run is
recorded at `.artifacts/t21-final/report.json`; focused evidence is in
`.artifacts/t21-tiles-qualified.log` and `.artifacts/uvprep-tiles-t21-qualified/`.

Final combined regression: **48/49 checks pass**, with only the unchanged known
low-flow feature failure (101/102 feature assertions). The complete 49-check
matrix reports stable source and suite hashes, no unexpected failures, and the
historical splitter-cursor UI check passes in this run. New T21 controls were
visually reviewed. Python compilation, both packaging recipe parses and working
diff whitespace checks pass; no tests are indexed. Summary:
`.artifacts/t21-summary.json`. No reference images, assertions or memory limits
were weakened, and no release/build/publication was performed.

## T22 live AI assistant extension — November 2, 2026

Added **Window > AI Assistant** as a dockable tab beside Properties, preserving
existing saved layouts. Installed Codex and Claude Code agents stream chat and
operate the live project through 15 shared native tools. Agents receive a concise
operating guide, allowlisted engine documentation, preset/effect catalogs,
persistent layer IDs and fresh offscreen 3D viewport PNGs. No model training,
new Python dependency or project-format change was introduced.

The authenticated loopback bridge queues work onto the owning graphics thread;
artist gestures and busy operations defer execution. Stop, project replacement
(including reopening the same IDs) and exit revoke the connection and cancel
queued edits. Native operations retain their existing undo boundaries. Saving
and texture export require a panel toggle; successful saves update the desktop
destination. Bounded chat history and backend session references stay in local
settings, separate from portable projects. Dedicated per-project agent workspaces
support Claude's directory-scoped session lookup. External stdio MCP clients use
the same tool contract through a copied ephemeral connection.

Qualification on installed Windows/Python 3.13/OpenGL runtime:

- Eight focused CPU/RPC/MCP/GPU checks pass: strict invalid-input rejection,
  documentation allowlist, authentication/browser-origin rejection, main-thread
  execution, queued cancellation, stdio handshake/error handling, native material
  edits, masks/effects, deterministic UV paint, undo/redo, portable reopen/export.
- Thirteen existing identity checks and all 27 existing CPU/GPU transaction
  checks pass (48 checks across these three suites).
- Real-window stdio MCP smoke passes live edits, PNG feedback, portable save,
  history persistence and same-project reopen/cancellation. The panel and both
  providers' real conversation screenshots were inspected.
- Real signed-in Codex **0.166.0-alpha.5.1** and Claude Code **2.1.91** each
  inspect, create a named fill, set roughness to 0.61, capture a viewport image,
  and confirm the value in a resumed second turn. Initial missing MCP annotations,
  a temporary-directory cleanup race and Claude's directory-scoped resume issue
  were corrected and the affected live workflows rerun successfully.
- The existing UI logic suite's sole failure is the historically documented
  panel-splitter cursor assertion. An unmodified HEAD app baseline passes this
  run; the current app also passes with diagnostic framebuffer reads, with the
  expected resize cursor appearing after the initial hover frame. Timing is
  implicated but not conclusively established; no assertion/reference was changed.
  Other shortcuts, paint, layer, mask, layout and cursor actions pass.
- Python compilation and whitespace checks pass. Local evidence is under
  `.artifacts/ai-ui/` and `.artifacts/ai-regression/`; the tests and evidence remain
  ignored/unindexed. The known low-flow baseline was not changed or rerun here.

Limits: Python source installation only; frozen packaging and other-platform
runtime are unqualified. MCP is local stdio with tool discovery/calls, not a
hosted/OAuth service. The tool surface covers a bounded subset of native features;
whole-request atomic undo, arbitrary project replacement/import, every AI product
and consumer-account interchangeability are not claimed. Muse needs a compatible
interface or an additional provider adapter. Provider account eligibility and
global/managed agent policy still apply. See AI_ASSISTANT.md for setup and data flow.

## Painter UX compatibility increment — November 2, 2026

Implemented the bounded authoring-workspace changes documented in
[PAINTER_UX_IMPLEMENTATION.md](PAINTER_UX_IMPLEMENTATION.md): active-target/write-channel
feedback, folder masks, per-channel row controls, inline effects, atomic forest drops,
smart-mask merge/replace, set highlighting and scope feedback, rotated UV navigation/
straight lines/resume, native projection shortcuts, F8/F9 bake controls, and visual
export templates/results with optional v14 project-owned export configuration.
Existing pipelines and dependencies are retained. Adobe's online screenshots were
used because the owner's installed Painter subscription is expired.

Qualification on the installed Windows/Python 3.13/RTX 4050 runtime:

- Five new coordinate/GPU contracts pass: rotated inverses/matrices, rendering and
  paint alignment, replay/portable restoration, bounded export settings/undo/load,
  and atomic ordered forest moves/no-ops/cycle rejection.
- The new desktop suite passes **31 assertions**, including real gestures, UV lines/
  resume, F8/F9, channel isolation, masks, graphical template Apply, actual packed
  export, project reopen, 150%/200% dialogs and projection transforms/undo.
- A **38-suite focused regression** passed 36 suites, retained the known low-flow
  feature failure (101/102), and found a stale W-unavailable expectation plus the
  existing splitter-cursor failure in UI logic. The private W assertion was updated
  to verify rejection of a non-fill target, with positive transform coverage in the
  new suite. The splitter and low-flow assertions/references were not changed.
- Corrected UI logic has only its documented splitter-cursor failure. Final visual
  review also caught foreground UV labels drawing over dialogs; those guides now
  yield to popups. The affected UV, new UX and UI-logic suites were rerun after that
  fix: UV and UX pass; UI logic retains only the known splitter failure.
- The 38-suite selection includes legacy archives, actual bake/material/channel/
  tile/reimport UI, native replay, memory, transactions, persistence, headless
  rendering, CPU contracts, unsaved handling and all eight assistant contracts.
  This is a targeted selection, not the entire local qualification matrix.
- Source/suite fingerprints are stable within the completed runs. Python compilation
  and whitespace checks pass. Actual painting/baking/effects/export/high-DPI
  screenshots were visually inspected. Tests and evidence remain ignored/unindexed.

Evidence: `.artifacts/painter-ux-final-focused/report.json`,
`.artifacts/painter-ux-ui-logic-corrected/report.json` and
`.artifacts/painter-ux-overlay-final/report.json`. Superseded incomplete matrix
attempts were stopped after review changes and are not qualification evidence.

Full Painter parity remains incomplete. Quad-loop fill, full cage visualization,
general transform gizmos, specialist shader/rendering/particle workflows, broader
resource UX, proprietary graph fidelity and the existing tile/hardware/platform
limits remain explicit in the companion's remaining-scope table. No release/tag,
frozen build or full artist-migration certification is claimed.

## Project protection follow-up

The desktop project workflow now guards archive open, file drop, New Project,
and Painter import against accidental loss of edits. Manual save failures display
a dialog while the current project stays open. This addresses the manual-save
visibility problem in [REL01](SUBSTANCE_PAINTER_USER_WORKFLOW_COMPLAINTS.md#rel01-save-failures-are-too-easy-to-miss).

The local desktop regression exercised a dropped archive with cancel, discard,
successful Save and Continue, and a destination that rejects replacement. It also
verified the existing quit and save flow. All seven CPU archive contracts passed,
including preservation of the previous archive after a publication failure.
The persistence suite's six optional GPU cases were skipped in this run.
