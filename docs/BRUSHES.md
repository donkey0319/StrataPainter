# Brush controls and pressure input (T07)

Properties > Brush exposes round, built-in and image alphas, alpha inversion,
stroke opacity, camera/tangent-wrap/tangent-planar/UV alignment, backface angle,
angle following, four jitter amounts and a deterministic jitter seed. Pressure
size and flow each have a minimum fraction at zero pressure. Size can use screen
pixels, object size or UV units. Mirror/radial symmetry includes axis, center in
normalized object coordinates, and radial count. Search the Properties panel to
isolate controls. Brush controls are session settings, saved with the project;
they do not add document undo steps. Each resulting stroke is one undo action.

Projection has independent load/clear controls for all seven channels. Loading
validates the image before assignment and enables its channel; clearing affects
only that slot. Use the Material (brush) channel toggles to disable a projected
channel. S + left/middle/right drag rotates/moves/scales the shared projection or
stencil placement. Existing stencil, clone-source, smudge and quick-mask controls
remain available. Clone/smudge use Flow for strength; the UI explains that stroke
opacity applies to paint/projection rather than exposing an ineffective slider.

On Windows, `strata/tablet.py` observes Windows Ink `WM_POINTER` pen messages on
the GLFW window. `GetPointerPenInfo` supplies pressure normalized from 0–1024;
the adapter checks the pressure-valid bit and clamps the result. It forwards all
messages to the original window procedure so GLFW retains position/button and
mouse-promotion handling. Ordinary mouse input, focus/capture loss and failed pen
queries restore pressure 1.0. Devices without pressure also use 1.0. The original
window procedure is restored before GLFW shuts down. Capture does no GPU work.
The production viewport forwards captured pressure to both stroke begin and move,
including straight-line/resumed painting. The panel shows adapter/source status.

The adapter uses the latest pressure at the UI frame rate, consistent with current
mouse sampling. It does not preserve every coalesced pen event, tilt, rotation,
barrel-button or eraser-end semantics. Windows Ink must be enabled in the device
driver; legacy WinTab is not implemented. Linux/macOS currently use mouse fallback.
**No physical tablet was available for this qualification.** Installing the native
observer and injecting synthetic pressure do not certify a physical device.

`Engine.begin_stroke(hit, pressure=1.0, info=None, seed=None)` now accepts an optional
seed. With no override it uses saved `Brush.seed` (default 17), independent of undo
history length. `Stroke.seed` records the normalized 32-bit value for the live
stroke. Identical settings, geometry, samples and seed reproduce jitter. Settings,
including the radius calculation, freeze at stroke start. This is not an operation
journal; persistent native replay remains T12. Repeated strokes deliberately use
the same seed until the artist changes it.

No archive version change: older brush dictionaries receive the default seed,
ordinary projects remain v3, and independent mask-paint projects remain v4.
Portable resource packaging already covers image alpha, stencil and projection
paths. Raster results retain their existing undo/save/export behavior.

## Qualification and handoff

- Prerequisites consumed: verified T02 resource packaging, T03 stroke undo and
  transactions, T04 seven-channel storage, and the current T06 v4 mask-paint code.
- `tests/brush_check.py --gpu .artifacts/brush-t07-final`: seven CPU/GPU scenarios
  cover normalization/fallback/native dispatch, legacy brush dictionaries,
  pressure size and flow coverage, stroke opacity/undo, seeded repeatability,
  frozen sizing, alpha inversion, all seven projection channels, portable reopen,
  continued painting, seven exported channels, backface rejection and a wrapped
  sphere stroke covering both sides of the U seam. Coverage tolerance is .025;
  saved/repeated raster arrays are exact; linear export evaluation tolerance is
  1e-5 for 32-bit EXR.
- `tests/brush_ui_check.py .artifacts/brush-ui-t07-final`: actual widgets and
  viewport gestures cover controls, alpha selection/inversion, pressure size,
  opacity, seven image slots and isolated clear, pressure begin/move routing,
  seed capture, undo/redo, portable save/reopen, mouse fallback and export.
  Image-dialog results are injected; native OS file-picker interaction is untested.
  Screenshots: `brush.png`, `jitter.png`, `tablet.png`; assertions in `results.json`.
- Native environment: Windows CPython 3.13.14, OpenGL 3.3-compatible RTX 4050,
  existing `.venv` launched through the approved execution path. CPU input checks
  are included in CI; remote CI execution and other GPU platforms are unverified.
- Final regression logs are `.artifacts/t07-final-*.log`. The feature suite also
  checks stencil placement, mirror/radial strokes, clone and smudge. The known
  baseline low-flow accumulation failure remains separate work.
- Changed source: `strata/app.py`, `strata/tablet.py`, `strata/layers.py`,
  `strata/painter.py`, `strata/engine.py`. Checks: `tests/brush_check.py`,
  `tests/brush_ui_check.py`, CPU CI workflow. No dependency added, commit or release
  created. Existing uncommitted work retained.
- Next: T08 may use the same pressure/seed engine API while adding UV input;
  T09 may proceed with its existing prerequisites. Keep tablet capture independent
  of brush evaluation. Before claiming tablet hardware support, perform the manual
  check below.

## Physical tablet smoke check (not run)

Enable Windows Ink in the tablet driver. Open a paint layer, enable Pressure size
and Pressure flow, set minimum size .1 and minimum flow 0, and paint with light
then firm contact. Confirm the panel reports `pen` with changing values, light
strokes are narrower/fainter, and an ordinary mouse immediately reports `mouse`
at 1.0. Lift/recontact, leave the window, switch focus and return; verify no stuck
stroke or stale pressure. Undo/redo, save/reopen, continue painting and export.
Record device/driver versions and actual results before adding hardware evidence.

Native API references checked during implementation: Microsoft
[POINTER_PEN_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-pointer_pen_info),
[POINTER_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-pointer_info),
[WM_POINTERUPDATE](https://learn.microsoft.com/en-us/windows/win32/inputmsg/wm-pointerupdate),
[SetWindowLongPtrW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowlongptrw),
and [GLFW native access](https://www.glfw.org/docs/latest/group__native.html).
