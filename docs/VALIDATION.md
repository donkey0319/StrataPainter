# T20: local qualification and evidence

Qualification is separated into portable CPU contracts, offscreen GPU behavior,
actual desktop interaction, carried asset workflows and performance measurements.
Release/package/hardware qualification is a separate decision; a successful
engineering run does not imply a release-ready product.

The user's instruction to keep **all tests local and ignored** overrides the
implementation plan's proposed public CPU/offscreen test CI. The maintained suite
and runner remain under ignored `tests/`; evidence remains under `.artifacts/`.
They are not in the Git index or source candidate. A fresh public checkout does
not contain this private local suite. CI remains **source syntax only**; it parses
application/examples/launchers and packaging recipes on the configured Windows /
Linux, Python 3.12 / 3.13 matrix. That is not runtime or platform qualification,
and GitHub execution has not been verified here.

## Maintained local entry points

```powershell
python tests/qualify.py --list
python tests/qualify.py --out .artifacts/qualification-new
python tests/qualify.py --out .artifacts/qualification-cpu --lanes cpu --development
```

Use the established project `.venv/Scripts/python.exe`; no dependency installation
is performed by these commands. `--lanes cpu gpu ui asset performance` chooses
lanes, and `--only name ...` chooses explicit named checks. Each run requires a
fresh output directory under this workspace's `.artifacts`, preventing accidental
replacement/mixing of evidence. The matrix is `tests/qualification_matrix.json`.
Checks run sequentially on the owning process/GL thread where applicable; GUI
suites use actual separate native windows.

| Lane | What is established | What it does not establish |
|---|---|---|
| CPU | Real export/archive/identity/channel/journal/delivery/qualification contracts with GPU, GL backend, window/UI and Engine imports prohibited | A graphics driver, rendered pixels, or physical inputs |
| GPU | Actual GL engine, painting, effects, bakes, replay, reimport, memory and headless behavior | Interactive pointer/key/widget integration or other drivers |
| UI | Real desktop input and controls, per-package desktop assertions, project/controller/close handling and legacy UI logic | Physical stylus hardware or another window system |
| Asset | Frozen v2 reference, local Painter corpus, actual Blender reconstruction and one carried native scene | Full proprietary graph fidelity, every external target or arbitrary topology preservation |
| Performance | Fixed workload/hardware/seed/resolutions, first-call and warmed GPU-complete timing, p50/p95, owned texture accounting, OS process memory, exact cancel/budget rollback/release | Universal latency SLAs, driver VRAM usage or dense-scene benchmarks |

The runner writes `report.json` after each completed check. It records interpreter,
package/platform versions, Git HEAD **and dirty state**, SHA-256 of actual source /
requirements / recipes / CI inputs, local suite/matrix, immutable baseline fixtures,
commands, exit codes, elapsed times, log hashes and exact failure classifications.
Actual working-tree hashes matter: HEAD alone does not describe this uncommitted
implementation. Source and suite hashes must remain unchanged during a run.
Documentation is recorded separately at completion and can receive subsequent
status/evidence bookkeeping updates.

Each check gets `logs/<name>.log`; large raw logs stay out of progress messages.
The report records local GL renderer/vendor/version/limits when performance runs.
A CPU-only run does not create a context or claim any GPU qualification. Partial
runs explicitly set `complete_local_matrix: false`.

## Failure policy

`passed`, `known_failure`, `failed` and `timeout` remain distinct results. Existing
assertions/goldens are not changed by the runner. The only recognized baseline
signatures are:

1. Feature suite: exit 1, exactly `low flow builds up gradually`, summary
   `101/102 checks passed`, and no traceback.
2. Legacy UI logic: exit 1, exactly `hovering a panel splitter shows the resize
   cursor`, summary `1 failure(s)`, and no traceback.

Any additional failure, changed summary, crash, timeout or different exit code is
an unexpected failure, including when a known failure also appears. Seven focused
CPU contracts verify classification and matrix/import boundaries. A known failure
never becomes a passed check or an automatic release waiver.

The default command uses release semantics and exits nonzero while release gates
remain open. `--development` may return 0 for the selected engineering checks when
there are no unexpected failures and code/suite fingerprints are stable. The JSON
still records all known failures and `release_ready: false`. It cannot infer manual
hardware/package/remote-CI approval. See RELEASE_GATES.md for the outstanding gates.

## Carried milestone scene

`tests/t20_workflow_check.py --gpu OUTPUT` carries a single two-material, mirrored-UV
MikkTSpace prop through:

1. Import with declared meter units and managed linear Rec.709 color.
2. External high-poly file bake with a retained portable source.
3. Bitmap foundation, masked procedural wear and persistent accumulated anchors.
4. A real surface stroke followed by an independent native UV correction.
5. Native material save, apply and undo; portable project save/reopen with unchanged
   native composite pixels.
6. Independent set resize (256 / 128), then a supported geometry revision.
7. Distinct texture export and 256px Blender bundle delivery.
8. Actual Blender 5.1.2/Cycles material reconstruction compared to native GPU output
   at the **same output resolution**. The native reference uses the declared OCIO
   transform rather than an assumed gamma. Source bitmap/high-poly hashes remain
   unchanged.

The image metric is maximum absolute error in linear Rec.709 color, linear scalar
roughness/metal/opacity and encoded world-normal data, on the fixed interior mask
used by the T19 reference (excluding geometry edges). Tolerance remains **0.002**;
no golden was regenerated or tolerance relaxed. The focused carried scene measured
color **0.00045639**, roughness **0.00000012**, metallic **0**, normal **0.00000769**
and opacity **0.00000006** maximum differences.

The initial draft comparison incorrectly mixed a native 128px material with a
256px delivery. Legacy encoded-space bilinear filtering additionally differs from
Blender's linear-space interpolation around high-contrast painted edges. T20 aligns
reference resolution/color semantics instead of accepting a wider error. This
managed scene establishes managed target behavior; arbitrary high-contrast legacy
filtering equivalence is not claimed. T19's separate legacy smooth-pattern target
checks remain useful within their recorded scope.

The same scene has a tiled variant: two materials, three pages, the same bitmap /
mask / anchor setup, cross-page native painting, portable reopen and per-UDIM
export. PNG comparison encodes the managed native linear output to the actual
sRGB file space first; the per-component tolerance is **1/255**. Mesh/material
UDIM bundles remain unsupported by T19 and are not implied by this texture case.

## Reproducible performance protocol

```powershell
python tests/t20_performance.py .artifacts/performance-new --sizes 512 2048 4096 --samples 9
```

The fixed geometry is a four-vertex indexed UV plane, seed 271828. Two named
profiles separate core fill/noise plus sparse C/R paint from the same workload
with one user scalar channel. Records include the geometry/UV hash,
resolution, sample values and graphics limits. Each measured operation waits with
`ctx.finish()` before and after: reported milliseconds include CPU and completed
GPU work, not just command submission and not GPU-only timer queries.

First project/composite/stroke calls are recorded separately from warmed samples.
One process/context is reused across sizes, so shader/driver caches may persist
between resolutions; these are not claims of a fully cold process/driver cache
for every size. p50/p95 over nine samples are descriptive, not a production SLA.
The benchmark times a complete seven-sample UV path, stroke finalization/history
and composite, not individual pointer-event latency. It is an isolated UV
authoring workload, not a dense mesh/viewport test.

Owned texture live/peak accounting excludes driver/depth/VBO overhead. Windows OS
working-set, peak working-set and private process bytes (RSS on other systems) are
measured separately and labeled; those are **not driver VRAM measurements**. The
OS peak-working-set field is a process-lifetime high-water mark across cases, not
a separate per-resolution peak. Resource
release must return estimated texture bytes to the engine's initial baseline.
Cancellation must restore pixels/serial exactly. An injected allocation budget
failure must retain resolution, pixels, history and estimated live bytes. Existing
history and global GPU budgets still apply.

Actual final results, complete matrix status and remaining failures are recorded in
IMPLEMENTATION_STATUS.md and the local run's JSON, not inferred from test filenames.


## November 2 local outcome and the discovered budget boundary

The original complete **45-check** report is retained at
`.artifacts/t20-final/report.json`: 43 passed, the known low-flow feature failure
remained, and the initial combined 4K/custom performance case hit the default
5 GiB budget. Legacy UI logic passed this run; its historical exact failure
signature is retained for classification, not reported as a current failure.

That run exposed a genuine late-initialization problem: enough budget existed for
lazy C/R targets and snapshots, but a later stroke-buffer allocation could fail
and leave empty authored channels behind. A focused 128px reproducer failed on
the old implementation. `MemoryBudget.check` now admits the full initial target /
snapshot / buffer working set **without reserving or inflating peak accounting**
before Stroke publishes lazy channels. This changes budget admission, not paint
math, serialization, assertions or golden images. It covers the owned initial
stroke working set; it does not claim to predict untracked driver allocations or
all later dynamic alpha/projection resource failures.

All **10 memory cases** pass after the fix, including the new late-budget case.
The frozen post-fix subset at `.artifacts/t20-patch-verification/report.json`
contains **11 checks**: ten passed and feature retained only the known 101/102
low-flow failure. It covers scalar painting/UI, tile operations, UV/UI, journal,
transactions, memory, the carried scene and the performance protocol. Additional
brush verification passes seven scenarios and 35 real desktop assertions. Source
and suite hashes are stable within each report. The old full run is not rewritten
as a post-fix full pass; the post-fix report is explicitly a focused subset.

The revised performance protocol has two explicit profiles. A default-budget
rejection is recorded **only** for the named user-scalar/4096 stroke-initialization
stress case; it must preserve empty-channel ownership, pixels/history/serial/live
accounting and an absent active stroke. It reports `budget_limited`, with **no
invented stroke timings**. Other allocation failures still fail the benchmark.
Supported cases require actual painted coverage, exact cancellation, injected
resize-budget rollback and full owned-texture release.

Final warmed p50 / p95 milliseconds on the local RTX 4050, GL 3.3 NVIDIA 596.36,
nine samples per measured operation:

| Profile | Size | Composite p50 / p95 | Whole stroke p50 / p95 | Peak owned textures |
|---|---:|---:|---:|---:|
| Core | 512 | 3.49 / 4.10 | 79.48 / 85.37 | 62.1 MiB |
| Core | 2048 | 10.98 / 11.91 | 80.85 / 90.82 | 993.5 MiB |
| Core | 4096 | 28.71 / 30.09 | 144.43 / 182.35 | 3974.4 MiB |
| User scalar | 512 | 7.57 / 15.61 | 76.00 / 95.69 | 83.1 MiB |
| User scalar | 2048 | 16.80 / 18.70 | 83.34 / 87.47 | 1329.5 MiB |
| User scalar | 4096 | 51.35 / 51.65 | Budget-limited; not measured | 4560.0 MiB |

All six cases return owned textures to the **24-byte engine baseline** after
release. Raw first-call/warm samples, process working-set/private memory, limits,
rollback checks and fixture hashes are in
`.artifacts/t20-patch-verification/performance/performance.json`. These measurements
do not certify interactive 4K custom-channel painting under the default budget.

A separate 128-file **source-only candidate** excludes tests, artifacts, caches and
Git metadata. Every product/build-input hash matches the post-fix qualification
source. Relocation verifies import origin from the extracted tree, CLI command
listing, explicit extension loading, a native create/save/ZIP/GLB batch and real
GUI startup/rendering with isolated settings. The screenshot was inspected.
Archive and results: `.artifacts/strata-t20-source-candidate.zip` and
`.artifacts/t20-source-smoke/verification.json`. It uses the established Python
runtime/dependencies and is **not a frozen package**. Documentation in the archive
is a snapshot before the final evidence bookkeeping update.


## Subsequent T21 multi-tile qualification

The maintained local matrix now has 49 checks, including guarded CPU packing,
the original UV/physical-scale scenarios, multi-tile Blender/GPU workflows and
actual preparation UI. `.artifacts/t21-final/report.json` records **48 passed,
one known low-flow feature failure**, stable source/suite hashes and a complete
matrix. Both T21 control panels were visually inspected. This is later source
qualification; the earlier T20 source candidate remains tied to its original
hashes and has not been rebuilt for the T21 changes. Manual release gates remain
open. See UV_PREPARATION_SCALE.md for packing and revision limits.
