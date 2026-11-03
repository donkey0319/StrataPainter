# Strata baseline for implementation work

Captured October 25, 2026 against application commit `cefb609` before T01/T02 application edits. This is the T00 reference for distinguishing existing failures from regressions. The planning documents were untracked and have been preserved.

## Execution environment

- Native Windows project runtime: `.venv/Scripts/python.exe`, CPython 3.13.14, ModernGL 5.13.0.
- GPU: NVIDIA GeForce RTX 4050 Laptop GPU; requested OpenGL 3.3 context; reported `3.3.0 NVIDIA 596.36`.
- The project Python is based on Windows Store Python. It cannot start inside the restricted filesystem sandbox but works with approved elevated execution. This is an execution-access limitation, not evidence that dependencies or the environment are missing.
- The bundled analysis Python is CPython 3.12.14 and lacks the project GPU modules. It can run the standard-library CPU fixture generation path. Do not combine CPython 3.13 binary modules with that interpreter.
- GPU and UI commands below were run centrally by the coordinator. The fixture agent's separate attempted escalated feature command was interrupted while waiting and supplied no test results; it is not counted as a second execution.

## Actual baseline results

| Check | Outcome | Evidence and limitation |
|---|---|---|
| Project runtime and standalone GL context | Passed | Python/ModernGL/GPU information above was returned by the real project runtime. |
| `feature_check.py` at resolution 256 | 94 of 96 checks passed; two existing failures | Outputs under `.artifacts/baseline/feature`; approximately 20 seconds. Details below. |
| `headless_check.py` | Passed, exit 0 | Outputs under `.artifacts/baseline/headless`; approximately 6.2 seconds. Stroke landed; undo changes and redo restores; four exported maps; save/load round-trip image difference 0.0. |
| `ui_smoke.py` | Passed, exit 0 | Outputs under `.artifacts/baseline/ui`; 2048 bake approximately 2.3 seconds. Coordinator visually inspected `ui_2.png` and found no layout defect. This is smoke coverage, not a full UI qualification. |
| Full UI logic and unsaved-change suites | Not run in this T00 capture | Must be run for changes to relevant input/property/project-close behavior. |
| Adobe file conversion corpus | Not run | No fixture corpus was selected for this initial native baseline. Native fixtures require no Adobe installation. |

The feature suite's existing failures are:

1. **Low flow builds up gradually** reported coverage `0.999`, failing its assertion. Preserve this as a baseline failure; investigate brush accumulation separately rather than changing golden values to make a later task pass.
2. **Export all templates** crashed on Windows because the test turns template names into directory names by removing only colons. Template names still contain slashes and whitespace; a directory segment such as `Strata Unreal (BC / N DirectX ` is invalid. This test-harness failure prevents the broad export section from completing. T01 should add platform-safe output directories and targeted export assertions. It does not excuse the separate real legacy multi-set overwrite defect.

Source inspection plus the earlier CPU name-expansion reproduction established that legacy Unreal exports for two sets generate four unique names for eight intended files. Modern Unreal naming contains the texture-set token and generates ten unique names for ten intended files. T01 must validate pixels as well as names.

## Regenerate small reference fixtures

Run from the repository root using the verified executable. The GPU command needs the same approved outside-sandbox access as other project Python commands on this host.

```powershell
.\.venv\Scripts\python.exe tests/baseline_fixtures.py .artifacts/baseline/fixtures --gpu
```

For portable CPU-only geometry, image and settings generation:

```powershell
python tests/baseline_fixtures.py .artifacts/baseline/fixtures_cpu
```

The standard-library CPU path emits:

- `two_material_mirrored.obj`: Metal and Rubber parts, separate vertices at a UV seam, mirrored U handedness on Rubber; both sets deliberately occupy the same 0–1 UV range.
- `low_plane.obj` and `high_bump.obj`: UV-mapped low plane and 16 by 16 high-poly bump without UVs for projection testing.
- `color_grid.png`: deterministic RGB calibration grid.
- `fixture_settings.json`: seed 271828, 128px reference resolution, distinct AO samples/distances per set.
- `manifest.json`: asset hashes, application-source hashes, source commit, interpreter and platform.

GPU mode additionally emits `distinct_settings.strata`, nested groups, painted stripe masks, anchor content/references, and one set of document-channel reference maps per material under `reference_maps/`. The saved settings differ between Metal and Rubber so T02 can detect incorrect restoration. Manifest metadata records requested settings, renderer information and project-data/member hashes.

ZIP archives contain timestamps, so archive bytes are not a reproducibility criterion. The generator hashes decompressed ndarray data and project metadata, plus reference PNG files. Compare CPU fixture asset hashes exactly. Compare GPU images using an explicit channel-space tolerance on matching hardware/settings; do not require exact bytes across drivers. Reference regeneration after application changes must use a new output directory rather than overwriting this baseline.

## Existing suite commands

Use task-local library/cache directories and isolate user settings for UI checks. Set these variables only in the spawned test process/session, preserving the user's normal shelf and preferences.

```powershell
$env:STRATA_LIBRARY = "$PWD/.artifacts/baseline/library"
$env:STRATA_SUBSTANCE_CACHE = "$PWD/.artifacts/baseline/substance_cache"
.\.venv\Scripts\python.exe tests/feature_check.py .artifacts/baseline/feature --res 256
.\.venv\Scripts\python.exe tests/headless_check.py .artifacts/baseline/headless
```

For UI smoke, set `HOME` and `USERPROFILE` in a short-lived test subprocess to a created task-local settings directory before launching the script, or use a dedicated wrapper. Do not permanently change the shell/user profile. The coordinator used `.artifacts/baseline/ui_home` for this capture. Then run:

```powershell
.\.venv\Scripts\python.exe tests/ui_smoke.py .artifacts/baseline/ui
```

## Interpretation and release gate

The baseline establishes a working native GPU runtime and concrete engine/UI evidence. It authorizes comparison of subsequent fixes against recorded application-source hashes and artifacts; it does not certify production readiness or every feature listed by the API.

T01 and T02 may begin their owned changes once the coordinator verifies the fixture generator completed and its manifest still describes the pre-implementation application. Keep `.artifacts/baseline` immutable thereafter. A failing assertion unrelated to the package should remain documented; newly introduced failures must be resolved or explicitly rejected during integration.
