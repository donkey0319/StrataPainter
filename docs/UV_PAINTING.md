# UV-space painting (T08)

F3 opens the 2D view; F1 shows split views and F4 swaps their sides. Left-drag
paints the active texture set. Middle-drag pans and the wheel zooms. Viewport >
UV wireframe toggles the active set's wire overlay. All sixteen display modes
include their corresponding channels or mesh-map diagnostics; Material is a flat
base-color inspection in 2D rather than a lit surface. The cursor uses the same
coordinate mapping and size calculation as brush evaluation.

Alt+left rotates around the pointer; Alt+Shift+left snaps to orthogonal angles.
Alt+middle or Ctrl+Alt+left pans; Alt+right zooms. The wheel also zooms around the
pointer. Ctrl+right adjusts brush size/hardness, Ctrl+left flow/angle, and
Shift+right rotates the environment. A right-click opens quick brush properties;
the existing right-drag pan remains available. View rotation is shared by rendering,
wireframe, picking, clone sampling, stencil/projection and native stroke replay.
Reset 2D view or Frame UV tiles clears rotation. Shift-click draws a straight UV
stroke from the previous UV stroke on the same target; Ctrl+Shift-click snaps it.

Paint, erase, base masks, independent mask paint, quick masks, seven-channel
projection, stencil placement, clone and smudge use the existing engine painter
and undo/storage/compositor/export pipeline. Hold V and click a UV island to set
the separate UV clone source; source coordinates remain valid when offscreen.
S + left/middle/right drag rotates/moves/scales projection or stencil placement
relative to the originating pane. Pressure and deterministic seeds apply in both
views. Changes are immediately visible in the other view.

Native UV strokes always align in texture space and ignore 3D backface/occlusion
tests. Screen size stays fixed in framebuffer pixels; UV size stays fixed in UV
units; object size converts using the hit triangle's scalar world-per-UV scale
(an approximation for stretched UVs). Object mirror/radial symmetry, polygon fill
and Shift straight-line/resume shortcuts currently use the 3D view; the UI explains
these limits. Brush spacing, angle following, alpha and jitter remain supported.

Only the active set's covered UV pixels can receive paint. Empty/outside-tile
background does not start a stroke or add history. Leaving islands/panes breaks
the input path, so reentry does not bridge a sampled gap. Overlapping or mirrored
islands intentionally share the same texture pixels; each dab evaluates once per
texel rather than accumulating once per overlapping triangle. For object sizing,
the first containing triangle in active-set order supplies scale provenance.

## Engine/input API

`strata/viewinput.py` has CPU-only `ViewInput` (logical window coordinates to local
framebuffer pixels) and `UVMapping` (framebuffer pixels to UV, shared by rendering,
input, cursor and evaluation). All use bottom-left local pixel coordinates.

- `pick_uv(uv)` returns an active-set sample or None.
- `begin_uv_stroke(uv, mapping, pressure=1., seed=None)` starts an ordinary engine
  stroke targeting the current layer/mask/effect/quick mask; returns False on an
  invalid target or unsupported UV tool configuration.
- `stroke_uv_to(uv, pressure=1., mapping=None)` feeds the native UV path. An optional
  updated mapping keeps live view changes consistent. Use `end_stroke()` normally.
- `uv_brush_radius(tri, mapping, brush=None)` gives UV-space radius.
- `set_uv_clone_source(uv)` validates/sets the UV source; `uv_tool_reason()` explains
  unsupported configuration. Changing sets/projects clears the UV clone source.

Native 3D `begin_stroke/stroke_to` remain backward compatible. View provenance is
live only; persistent operation journals and resolution-aware replay remain T12.
Painted results use existing raster storage. No schema change: ordinary projects
remain v3 and independent mask-paint projects remain v4.

## Qualification and handoff

Single-agent implementation consuming T03/T04/T07 and current T06 mask storage.
Source changes are `strata/viewinput.py`, `strata/ui/uvview.py`, `strata/app.py`,
`strata/engine.py`, `strata/painter.py` and `strata/shaders.py`.

- `tests/uv_check.py --gpu .artifacts/uv-t08-final`: CPU coordinates, framebuffer
  scaling, pan/zoom, lookup/overlaps/degenerates; GPU seven-channel paint/erase,
  pressure/size spaces, active-set isolation and live view changes, no double dab
  on overlaps, empty-background/gap behavior, projection/stencil, clone/smudge,
  mask/quick mask/v4 persistence, continued editing, seven-channel EXR export,
  channel diagnostic pixels and wireframe. Saved arrays compare exactly; exported
  linear channel values use 1e-5 tolerance; diagnostic RGB bytes use tolerance 3.
- `tests/uv_ui_check.py .artifacts/uv-ui-t08-final`: actual 2D and split gestures,
  middle/wheel navigation, swapped panes, 125% UI scale, pressure, 3D/UV shared
  results, erase, V-click/clone, smudge, stencil, projection/S-middle placement,
  independent mask save/reopen/continued editing/export and wireframe command.
  Screenshots `uv-only.png`, `split-swapped.png`, `uv-mask.png` visually reviewed.
- Native Windows CPython/RTX 4050 through approved execution; no new dependency.
  Physical tablet and other GPU platforms remain unqualified. CPU coordinate tests
  are included in CI; remote execution unverified. Logs `.artifacts/t08-final-*.log`.
- The known low-flow baseline failure is separate work. No commit/release created;
  all prior uncommitted changes preserved. T09 is next. Later journal/reimport work
  must preserve the distinction between native UV and native 3D coordinates.

T14 continuation: Material tiles (Texture Set Settings or the Viewport command)
has a separate tile browser with grid navigation, isolation and paint-on-release
UV paths across tile boundaries. It freezes brush settings/resources, samples
pressure, supports cancellation and commits one undo action. The 3D view now
and main 2D view share cached tile materials. The main 2D grid has tile labels,
global-UV fit/pan/zoom and wireframe, with viewport tile maps capped at 512px.
Main 2D now supports live tiled paint, erase, masks and projection with one undo
action, frozen brush settings, cancellation and native view/pressure provenance.
Main 3D also supports live tiled surface strokes and recorded-view replay. Tiled
clone, smudge and quick mask remain guarded. See architecture/TILES.md for
the exact tile APIs, preview-cache ownership and remaining qualification.
