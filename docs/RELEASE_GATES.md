# T20: release and manual qualification gates

This document separates working local features from a publishable release. No
release is approved or published by running the validation suite or building an
archive. Current implementation status remains bounded to the actual local
Windows/NVIDIA/Blender evidence in IMPLEMENTATION_STATUS.md.

## Candidate decision record

For each candidate, retain actual source/suite hashes, dependency versions,
platform/GPU/driver, exact commands, logs, image spaces/masks/tolerances, benchmark
samples, packaging manifest and manual evidence. Keep unknown/not-run/failed states
explicit. A source parse, filename inventory or frozen build is insufficient proof
of product behavior. The local runner never marks a manual gate approved.

| Gate | Current evidence | Required decision or remaining work |
|---|---|---|
| Portable CPU contracts | Local guarded lane; GPU/window/UI/Engine imports prohibited | Keep independent of GL/UI dependencies; remote CPU-test CI intentionally absent under the offline-tests instruction |
| Windows offscreen engine | Local RTX 4050 native GL and package regressions | Match the candidate's actual dirty/source hashes; resolve unexpected failures |
| Windows desktop | Actual per-package UI actions plus legacy UI logic | Current legacy UI logic passed; retain the historical panel-splitter failure signature and repeat when its platform/layout changes |
| Brush behavior | Broad feature suite 101/102 | Known low-flow accumulation assertion remains failing; no assertion/golden weakening or automatic waiver |
| Carried scene | Managed two-material bake → authoring → native asset/project → revision → target plus tiled texture variant | Keep output-resolution/color-space comparison explicit; legacy interpolation limits stay unclaimed |
| Performance/memory | Local core and user-scalar UV profiles with p50/p95 and memory accounting; 4K scalar strokes are explicitly budget-limited | Treat nine-sample latency as measured context, not a universal SLA; driver VRAM and dense scenes remain separate work |
| Source candidate | 128-file local source candidate passed relocated CLI/extension/batch/GUI smoke | Candidate must exclude private tests, artifacts, caches, credentials and Git metadata; bind files to hashes |
| Frozen GUI/console package | Recipes/source assets parse; PyInstaller absent | Build in a deliberate packaging environment, then run candidate binaries with isolated settings from a relocated directory |
| Managed/optional runtimes in package | Native source mode OCIO/Blender paths verified | Actual frozen OCIO/data/GL loader behavior remains unqualified; do not infer it from installed source dependencies |
| Missing optional backends | Tested actionable failure/no destination replacement | Exercise the packaged optional-runtime behavior as well; particles remain unavailable |
| Remote CI | Configured Windows/Linux Python 3.12/3.13 syntax jobs | GitHub execution unverified; no CPU/offscreen test uploads while tests must stay local |
| Linux / macOS runtime | Not run | Native platform engine, input, resources, save/reopen and chosen target workflows need direct evidence before platform claims |
| Physical Windows Ink tablet | Synthetic/native capture code exercised, physical hardware not qualified | Use the manual protocol below; mouse/synthetic samples do not qualify a physical device |

T20 remains **in progress** while release/hardware/platform gates are open. The
local implementation/qualification increment can be verified without claiming
those external gates complete. Automatic multi-tile UV packing, arbitrary topology
preservation, Unreal/Unity setup and particle simulation are separately deferred
capabilities, not silently required or advertised by a narrow Windows mouse release.

## Physical tablet lane

Record device/model, connection, driver/firmware, Windows build, application source
hash, selected Windows Ink event source and relevant brush settings. Use actual
hardware, with task-local settings/project/output; retain event pressure/time and
screenshots or captured output.

- Draw slow/light/heavy strokes in 3D, 2D and split view. Verify pressure-size and
  pressure-flow independently, their documented minima, spacing and alpha behavior.
- Lift/re-enter, cross a viewport/UI boundary and perform a quick succession of
  strokes. Check for stuck pressure, mouse emulation duplication and lost releases.
- Verify stroke undo/redo, cancel, save/reopen and native replay retain the actual
  authored result. Resolution replay should use the recorded native samples.
- Record supported pen/eraser/button features individually; do not assume hardware
  controls are supported merely because pressure works. Document unsupported input
  paths rather than simulating a pass.

A physical device result cannot be supplied by automated mouse events or a
pressure-enabled fixture. There is no physical tablet signoff in this session.

## Platform lane

Run guarded CPU contracts first, then a supported offscreen GL path and the same
fixed asset/image protocol. Record actual GL renderer/vendor/version: software GL
can qualify an explicitly named offscreen lane without qualifying an interactive
physical-GPU desktop. Run the real UI with its native window system (or document
the virtual-display scope), bitmap/font dialogs, path handling, high-DPI input,
unsaved/recovery handling and missing-resource behavior. Retain portable project /
export / target comparisons and resource-release results. Tolerances must be
chosen for the declared space/mask/metric, not relaxed after seeing a failure.

The current source-syntax jobs do not meet any of these runtime gates. There is
no Linux/macOS GPU/UI or remote-run signoff in this session.

## Packaging lane

Source execution and frozen execution are separate. The maintained recipes are
`packaging/strata.spec` (GUI) and `packaging/strata_batch.spec` (console). Both carry
readable `blender_delivery.py` / `bundleio.py` assets for external Blender. A build
must be tied to actual product/source hashes, not just the old Git HEAD of this
dirty working tree. Do not install packaging dependencies or publish a release
merely to turn a validation report green.

For a future frozen build, independently verify:

1. Relocated launch with isolated config/shelf/cache and no source checkout on the
   import path; packaged fonts/resources and GL backend initialization.
2. New/import, bitmap fill, masks/anchors, actual input, save/portable reopen,
   native paint replay and exported image pixels.
3. Console `commands` / `capabilities` / batch operations, JSON stdout and error
   exits; native Blender ZIP/GLB creation with readable external setup source.
4. Managed color and optional native libraries in the claimed package profile;
   clear failures when Blender/OCIO/other optional readers are absent.
5. Package inventory and hashes: no test suite, `.artifacts`, `.venv`, user assets,
   configuration, `.git` or credentials; product sources/assets must be complete.
6. No stale fallback to source directories or machine-specific settings. A package
   that only works beside the development checkout is not a qualified release.

The packaging environment lacks PyInstaller. Source parsing/relocation evidence
must not be relabeled as a successful frozen build. Release publication and any
baseline-failure waiver remain separate explicit decisions.

## Baselines and history

T00 immutable fixtures remain under `.artifacts/baseline/fixtures`. New reference
outputs use new task directories. Source asset hashes must remain unchanged.
Archive timestamps are not cross-run equality criteria; compare manifest/data
semantics and declared image metrics instead. Historical baseline signatures remain available to the runner. In this session
only low flow still fails; the legacy splitter-cursor assertion passed. A recognized
failure remains release-visible rather than an automatic waiver.
A new assertion failure cannot inherit a baseline waiver just because the process
also prints a known failure.

Private tests/evidence intentionally are not shipped in Git or source candidates.
See VALIDATION.md for the maintained local matrix and report semantics.


## Current local decision

The T20 local increment is verified, including a real initial-stroke budget
admission fix, unchanged-space/tolerance carried-scene validation, two benchmark
profiles and a relocated source-only candidate. The original 45-check run and the
11-check post-fix subset remain separate hashed records. Source candidate tests
were performed with the established development Python/dependencies; frozen
packaging remains not run. No release publication or baseline-failure waiver was
requested or performed. Overall T20 remains in progress for the explicitly open
gates above. Full details and measurements are in VALIDATION.md.


Subsequent T21 source changes have a complete 49-check local report at
`.artifacts/t21-final/report.json`: 48 passed and the known low-flow feature
failure remains. The earlier source candidate does not contain these changes;
rebuild and bind any future candidate to its own source hashes. Frozen/device/
platform/remote gates and the release decision remain open.
