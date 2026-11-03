# Painter compatibility workspace: implementation and remaining scope

November 2, 2026. Companion to [the UX reference](SUBSTANCE_PAINTER_UX_REFERENCE.md).
This is an implementation increment, not certification of full Substance Painter parity.

## Artist-facing changes

- New installations start with the split 3D/2D view; saved workspace preferences remain authoritative.
- Mode > Baking / F8 opens nonmodal bake controls in Properties, leaving the canvas available for navigation and existing correction-field painting. F9 returns to Painting. Ctrl+Shift+B retains the existing bake-settings dialog. Per-set pending bake controls survive switching sets within the workspace.
- Properties, the canvas and status identify the active texture set and content/mask target. Properties lists the brush's enabled write channels independently of display inspection. Folder thumbnails now switch between content and mask correctly.
- Layers has an All channels / individual channel selector. Row blend and opacity controls edit the selected channel, including inheritance. Multiple selected layers retain their other channel overrides.
- Content and mask thumbnails indicate attached effects. The selected thumbnail's effects appear below its layer, with selection, enablement and contextual reorder/duplicate/delete controls. Right-click a layer to add a content or mask effect.
- Layer drops preview above/below insertion and folder nesting. A selected forest moves in one native undo action, preserving relative order and preventing cycles. Selecting parent and descendant does not move the descendant twice.
- Native and imported smart-mask drops merge by default; Ctrl-drop replaces their effects. Existing transactional import/library code performs the actual application.
- Hovering a texture-set row, or holding Ctrl+Alt over the model, highlights its geometry. Polygon-fill wireframe is restricted to the active set. Other-set surfaces show a prohibited cursor; starting an ordinary stroke there does not create empty paint history.
- UV navigation supports Alt+left rotation, orthogonal snapped rotation, Alt+middle or Ctrl+Alt+left pan, Alt+right zoom, brush adjustment chords, environment rotation, and right-click quick properties. The initiating button retains gesture ownership after modifiers are released. Wheel zoom is anchored under the pointer.
- Rotation is shared by UV rendering, wireframe, picking, paint uniforms, clone offsets, tile bounds and native stroke provenance. Shift-click and Ctrl+Shift-click draw ordinary/snapped UV straight lines from the previous UV stroke on the same target. Resume connects that endpoint to the next UV stroke through the native stroke path.
- W/E/R select existing fill projection translate/rotate/scale operations; Q shows/finishes projection editing. These drive the existing viewport transform and native undo, rather than reserving nonfunctional commands. General world/object-space gizmos remain separate work.
- Export has Export settings, Output templates and List of exports tabs. The visual template editor supports output add/duplicate/remove, RGB/RGBA/grayscale/component layouts, source selection and source dragging. Apply validates through the shared manifest. The JSON editor remains available for advanced definitions.
- Save settings and successful exports preserve the resolved output configuration in the document. Reopening restores template, folder, format/depth, resolution, padding, map overrides and selected set IDs. Loading settings never exports automatically. Successful/failed writes remain visible in List of exports. Export controls fit the tested 150% and 200% UI scales.
- Popup/text entry capture prevents viewport editing. Hidden sets, hidden parent folders, disabled masks, missing channel enables and ordinary material painting in Baking mode have explicit explanations.

## Architecture and compatibility

The existing engine, renderer, shader pipeline, ImGui workspace, transaction registry and manifest writer remain in use. No dependency was added.

`Engine.move_layers_to(layers, parent=None, index=None)` moves a forest as one stack action. Its insertion index refers to the destination list before removal of the moving layers. The existing single-layer API retains its original semantics.

`UVMapping.rotation` is an optional angle in radians, defaulting to zero for existing records. Its forward/inverse point and vector transforms are shared by painting and display. Native operation records retain the mapping for replay. Reset/Frame UV tiles clears rotation.

Projects that save export settings use **optional schema v14**. Projects without that configuration retain their existing minimum schema. Readers support v1–v14; older Strata releases reject v14 rather than silently dropping the saved configuration. Export settings are bounded, validated, undoable metadata and participate in modified-state tracking. New projects clear them. Portable storage does not change their meaning or trigger filesystem writes on load.

New modules:

- `strata/exportsettings.py`: validation of inert export metadata.
- `strata/ui/export.py`: graphical editing over the existing manifest API.

## Reference screenshots and verification boundaries

The owner's Painter subscription is expired. Reference research therefore uses online Adobe material, not the installed application's licensed runtime. The inspected [viewport illustration](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/viewport/viewport), [layer-stack documentation](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/layer-stack/layer-stack) and [12.2 baking illustrations](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/release-notes/version-12-2) establish structure and interactions. Some manual illustrations predate the current release. They do not establish pixel dimensions or installed-build defaults. Adobe images are linked, not bundled in the repository.

Local private checks cover rotated coordinate inverses/matrices, GPU paint and wireframe alignment, resolution replay and portable restoration, saved export configuration, invalid metadata rejection, atomic forest moves, and actual UI gestures. Existing UV, effect, export and transaction checks were also exercised. New screenshots include painting/baking, mask effects, graphical packing/results, and scaled export dialogs. Tests and evidence remain ignored and unindexed.

The final combined results are recorded in IMPLEMENTATION_STATUS.md after completion. Focused evidence is under `.artifacts/painter-ux-contracts-qualified/` and `.artifacts/painter-ux-ui-qualified/`. These are local evidence paths, not distributed artifacts.

## Remaining requirements: do not mark these complete

| Area | Remaining work or evidence |
|---|---|
| Full visual identity | Exact typography/icon metrics, complete menu ordering, every selection/hover state and representative artist migration sessions remain unmeasured. |
| Polygon Fill 12.2 | Quad-loop/partial-loop tools, topology-flow feedback, complete hit-test/through-selection behavior and tool-specific blend parity remain beyond the existing triangle/polygon/island/part fills. |
| Dedicated baking visualization | Current native correction fields and map diagnostics are exposed; Adobe's deformed green cage overlay, full high/low/cage visualization and automatic rebake behavior are not reproduced. |
| Transform manipulators | W/E/R/Q operate the existing fill transform. Full world/object-space translation/rotation/scale gizmos, size controls and surface snapping remain unavailable. |
| Brush edge cases | The documented low-flow baseline failure remains. Exact resumed-stroke accumulation, temporary modifier semantics, all tablet modes and specialist brush math need additional reference fixtures. |
| Advanced authoring | Editable native paths/ribbons/text retain their documented bounded representation; complete Painter path/tangent/particle/dynamic-stroke equivalence is not claimed. |
| Tiled tools | Existing exclusions for tiled clone/smudge/quick masks and some raster imports remain; see architecture/T14_ACCEPTANCE.md. |
| Shader/rendering | Order-independent transparency, scattering/transmission/anisotropy, full displacement/tessellation, all custom shader formats and Iray parity are not implemented by this increment. |
| Adobe ecosystem | Proprietary Substance graph evaluation, arbitrary `.spp` fidelity, all starter assets and licensed render backends require their real supported runtimes and reference corpus. |
| Resource UX | The existing native/Substance shelves remain separate sources. Full library breadcrumbs, all resource family filters, favorites and every viewport/material-slot drop modifier need further work. |
| Delivery | Existing filename safety and manifest packing remain. All Adobe output formats, PSD layer export, all external DCC setup integrations and USD workflows are not implied. |
| Hardware/release | Physical stylus, other-platform runtime, frozen packaging and representative production assets remain separate qualification gates. |

Future agents should take the next bounded requirement from this table, reproduce the current behavior, extend the existing implementation and attach engine/UI/save/export evidence. A reserved shortcut, screenshot resemblance or source-level API is insufficient evidence of complete functionality.
