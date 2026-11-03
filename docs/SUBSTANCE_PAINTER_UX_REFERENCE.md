# Substance Painter UX reference and Strata implementation contract

Research date: November 2, 2026. Reference baseline: Adobe Substance 3D Painter 12.2, released October 21, 2026. Audience: implementation, design, QA, and review agents working on Strata Painter.

## 1. Purpose and how to use this document

The product goal is that an experienced Painter artist can open Strata and complete familiar work with minimal relearning: find the same concepts, use familiar gestures, predict the destination of edits, and obtain dependable outputs. Familiar appearance must be backed by equivalent operations and editable data.

This is a UX reference and implementation contract, not a claim that Strata already matches Painter. It complements [the implementation plan](STRATA_PAINTER_IMPLEMENTATION_PLAN.md), [capability ledger](FEATURE_PARITY.md), and [implementation evidence](IMPLEMENTATION_STATUS.md). Source inspection and actual task execution take precedence over README feature claims.

Evidence labels used throughout:

- **Reference:** behavior described by the linked official Adobe documentation.
- **Requirement:** proposed Strata behavior derived from the migration goal; normative for implementation, but not a claim about an unobserved Adobe detail.
- **Verify:** needs a controlled session in the specified Painter build before claiming exact correspondence.

Research used public Adobe documentation and repository inspection. Painter was not launched for this work. No pixel measurements, timing benchmarks, physical tablet checks, or side-by-side screenshots were captured. Diagrams below are original structural schematics, not Adobe screenshots. Exact icon shapes, dimensions, colors, menu ordering, and undocumented interactions remain **Verify** items.

The 12.2 baseline matters: its Polygon Fill, cage correction, and texture-set feedback differ from older tutorials. Do not implement an older workflow and label it current parity. See [Adobe 12.2 release notes](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/release-notes/version-12-2).

## 2. Artist's mental model

| Concept | Meaning the artist expects | Strata requirement |
|---|---|---|
| Project | Mesh plus editable texturing work and configuration | Saving preserves editability, dependencies, settings, and delivery intent. |
| Texture Set | Material-associated authoring context | Clearly identify the active set; changing it changes the associated stack and settings. |
| UV Tile / UDIM | A tile within the chosen UV workflow | Show ownership and tile coordinates; do not confuse a tile with a material. |
| Channel | A material signal, such as Base Color, Roughness, Metallic, Height, or Normal | Distinguish authoring, storage, visualization, and export interpretation. |
| Layer content | Material or painted information | Keep its selection distinct from the layer's mask. |
| Mask | Grayscale modulation of layer coverage | White reveals, black hides, intermediate values partially reveal. |
| Effect | Editable operation on content or mask | Display its owner and position in the relevant effect stack. |
| Asset | Reusable resource or preset | Make compatible destinations discoverable before applying it. |
| Mesh map | Geometry-derived input to texturing | Distinguish it from a painted output channel. |
| View mode | How the result is inspected | Changing inspection must not silently change the paint target. |

**Reference:** a regular imported mesh creates Texture Sets from material IDs. The active set owns the accessible stack, and only one set is painted at a time. Visibility, selection, and disabled/unassigned status are distinct. UV Tile workflows add a different grouping model. Sources: [Texture Set](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/texture-set/texture-set), [Texture Set list](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/texture-set/texture-set-list), [UV Tiles](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/uv-tiles/uv-tiles).

**Requirement:** at every moment, the user must be able to answer: Which set am I editing? Which layer/effect? Content or mask? Which tool? Which channels will change? Which view am I inspecting?

## 3. Workspace layout

### 3.1 Structural map

The following is the proposed Strata Painter compatibility workspace. Panel roles and docking follow Adobe's documented interface model; the precise placement and proportions are Strata requirements pending reference capture.

```text
+----------------------------------------------------------------------------------+
| Main menus                                      Project name / modified state    |
+----------------------------------------------------------------------------------+
| Contextual controls: active tool / material transforms      View / mode controls   |
+---+----------------+----------------------------------------+-----------------+---+
| T | Assets         | 3D viewport        | 2D / UV viewport   | Texture Set List| D |
| o |                |                    |                   +-----------------+ o |
| o | Library / type | Material/channel    | Material/channel   | Layers          | c |
| l | Search         | inspection         | inspection         | / Set Settings  | k |
| s | Thumbnail grid|                    | UVs / tile grid    |                 | s |
|   |                |                    |                   +-----------------+   |
|   |                |                    |                   | Properties      |   |
|   |                |                    |                   | for target      |   |
+---+----------------+----------------------------------------+-----------------+---+
| Status / computation progress / actionable diagnostics                            |
+----------------------------------------------------------------------------------+
```

**Reference:** panels can be rearranged, resized, and hidden. Tools and dock access occupy vertical edge toolbars. The contextual toolbar stays above the viewports; its left side changes with context while viewport controls remain available. The documented split viewport defaults to 3D on the left and 2D on the right. Sources: [Interface](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/interface), [Toolbars](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/toolbars), [Viewport](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/viewport/viewport).

### 3.2 Panel-by-panel contract

| Region | Artist's task | Required contents and feedback |
|---|---|---|
| Main menu | Find document, edit, mode, viewport, and workspace actions | Predictable menu paths; shortcut labels; disabled reasons where useful. Verify exact reference menu structure before reorganizing Strata. |
| Tools | Choose the operation applied by a gesture | Distinct tool icons, checked active state, tooltips with names and bindings, alternate tool modes. |
| Contextual controls | Adjust the current operation without leaving the canvas | Paint controls when painting; projection transforms for fills; suitable path or correction controls in those modes. |
| Assets | Find reusable resources | Library scope, search, type filters, thumbnails, names, and resource actions. |
| Viewports | Paint and inspect | 3D, 2D, split/swap modes; visible inspection label; relevant overlays and cursors. |
| Texture Set List | Choose authoring scope | Active row, independent visibility, isolation, tile hierarchy, disabled status, shader association. |
| Layers | Build and inspect the material | Content/mask thumbnails, hierarchy, visibility, channel selector, blend and opacity, creation actions. |
| Texture Set Settings | Configure the active set | Resolution, channel configuration, map inputs, mixing/padding settings. |
| Properties | Edit the selected target | Context title and applicable sections; avoid an unrelated global inspector. |
| Display Settings | Judge appearance | Environment, camera, post effects, rendering, and visualization settings. |
| Shader Settings | Control channel interpretation | Shader selection/instance, relevant parameters, geometry displacement where supported. |
| History / Log | Recover and diagnose | Understandable operations and actionable processing/import errors. |

Properties is context-sensitive and accessible through dock controls and viewport right-click. Shader configuration is separate from painting properties; Painter also documents independent shader undo history. Sources: [Properties](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/properties), [Shader Settings](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/shader-settings/shader-settings), [History](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/history).

### 3.3 Docking and workspace behavior — Requirement

1. Dragging a panel tab previews its destination before release; tab groups, resizing, floating, closing, reopening, and reset must be predictable.
2. Restore workspace state across launches without changing project pixels or dirty state.
3. Reset Layout restores a complete usable workspace, including panels previously closed or placed off-screen.
4. UI scaling preserves readable labels, usable controls, and viewport interaction coordinates. Test at 100%, 150%, and 200% on representative window sizes.
5. Hiding panels maximizes painting space and restoring them recovers their sizes and active tabs.
6. If a narrow panel overflows, preserve access through scrolling or overflow menus; do not silently omit necessary actions.

## 4. Layer, mask, effect, and channel interaction

### 4.1 Layer anatomy

```text
Channel being inspected: Base Color              [effect] [mask] [paint] [fill] [+]

[eye] [expand] [content thumbnail] [mask thumbnail]  Painted metal     Normal 100
                  ^                       ^
             select content          select mask
         [indented effect row for the selected content OR mask]
         [indented effect row]
```

**Reference:** the stack composites from bottom upward. Paint layers accept brush operations; fill layers are parameter/resource driven; folders organize layers. Blend and opacity are channel-specific. The stack's channel selector changes thumbnail/blend inspection, not which material channels the brush writes. Source: [Layer stack](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/layer-stack/layer-stack).

**Requirement:** separate the selected row, selected content/mask thumbnail, and selected effect visually and in state. Clicking one target must update Properties and eligible tools atomically. Painting on fill content must give a clear explanation and route to a paint layer or paint effect; never create hidden paint storage inside a fill.

### 4.2 Selection and structural editing

**Reference:** dragging layers uses insertion bars; dropping onto a folder nests the layer. Ctrl-click provides additive selection, Shift-click selects a range, and Ctrl+G groups selected layers. Source: [Managing layers](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/layer-stack/managing-layers).

**Requirement:** implement rename, visibility, duplicate, copy/paste, delete, grouping, collapse/expand, reordering, and context menus consistently. Show whether a drop inserts above/below or nests. Prevent cycles, preserve relative order in multi-selection, and keep selection anchored to stable IDs after reordering. Distinguish layer copy from content-only copy and mask-content copy. Verify exact reference keyboard variants before assigning them.

### 4.3 Masks and effect stacks

**Reference:** masks are grayscale. Alt-clicking their thumbnail isolates the mask; Shift-clicking temporarily disables it. Content and mask have separate effect stacks. Painter documents an indicator beneath each thumbnail: gray for no effects and red when effects exist. Adding/replacing a mask can destroy its existing effects. Smart-mask drops accumulate effects; Ctrl-drop replaces them. Source: [Masking and effects](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/layer-stack/masking-and-effects).

**Requirement:** preserve the content/mask distinction across selection, copy, save, and undo. A mask's disabled, isolated, selected, and modified states must be independently legible. A generator followed by manual correction and filtering must remain an editable ordered stack. Destructive replacement must be undoable and must not masquerade as adding another effect.

**Reference:** effect types include Generator, Paint, Fill, Levels, Compare Mask, Filter, and Anchor Point. Effects can be reordered, and most have blend/opacity controls. Sources: [Effects](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/effects), [Compare Mask](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/compare-mask).

### 4.4 Generators and anchors

**Reference:** generators derive results from inputs such as baked Position, Curvature, and World Space Normal. Adding a generator creates an effect; selecting that effect exposes the generator resource and its parameters. Selecting content versus mask exposes the corresponding effects. Source: [Generators](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/generator).

**Reference:** anchors expose content/masks to other inputs within the same Texture Set. The source must be below its consumer; moving it above breaks the reference. Properties provides reference navigation. Source: [Anchor Point](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/anchor-point).

**Requirement:** distinguish missing mesh-map inputs, missing resources, invalid anchor order, and unsupported procedural evaluation. Show actionable diagnostics at the affected effect. Preserve stable references on rename and provide navigation to the source. Detect unsupported dependency cycles before evaluation.

### 4.5 Texture-set configuration

**Reference:** Texture Set Settings controls resolution, channels, and mesh maps. Channels expose storage precision and color-management status. Channel removal retains Painter's authored information for later restoration. Normal and AO mixing and UV-padding strategies affect the result. Source: [Texture Set settings](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/texture-set/texture-set-settings).

**Requirement:** show the active set beside resolution changes, make recomputation progress visible, and preserve authored detail through supported resolution changes. A destructive operation must disclose its impact before commit. Do not make a preview-channel dropdown act as a channel-enable editor. Unsupported shader channels must remain distinguishable from missing channels and disabled material inputs.

## 5. How artists operate Painter: end-to-end workflows

Each sequence below is a **Strata acceptance requirement** based on the cited reference concepts. It is not a transcript of a measured Adobe session.

### W01 — Create a project and establish scope

1. Invoke File > New; choose a mesh and project template.
2. Configure resolution, normal convention/tangent settings, UV workflow, physical units, and color handling as applicable.
3. Inspect material-derived sets and UVs before authoring. Missing UVs must lead to an explicit unwrap choice or diagnosis.
4. Select a set and verify that its stack/settings are the active authoring context.
5. Save, reopen, and recover the same scope and authored data.

Painter's new-project configuration exposes these categories, including imported baked maps and optional automatic UV generation. The preserved-tile workflow groups tiles by material; the legacy tile-to-set workflow is different. Source: [Project Creation](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/getting-started/project-creation).

### W02 — Bake and inspect geometry-derived maps

1. Enter Baking mode; select target sets/tiles and baker outputs.
2. Configure shared resolution/dilation and high-poly source or low-poly-as-high-poly behavior.
3. Choose and inspect the cage strategy; adjust projection distances or an imported cage.
4. Run the bake and inspect individual maps and the log.
5. Resolve errors and return to Painting mode without losing authoring context.

Painter documents a dedicated baking workspace, selectable targets/bakers, common settings, and links from errors to relevant settings. Source: [How to bake mesh maps](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/baking/how-to-bake-mesh-maps).

Visual diagnostics should include distinct low/high/cage displays, cage surface/wireframe opacity, matching errors, and hard-edge/UV-seam warnings. Source: [Baking visualization settings](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/baking/baking-visualization-settings).

### W03 — Build a reusable material stack

1. Find a material or smart material using asset scope, type, and search.
2. Insert it at an explicit stack location.
3. Adjust the resulting fill parameters or expand the smart-material folder.
4. Add a mask; combine procedural coverage with hand correction.
5. Reorder/disable effects, compare the result, and save a reusable preset.

Painter's smart materials are reusable layer-folder presets; smart masks are effect presets. A smart material instance is not a live link to the original preset. Sources: [Smart Materials and Masks](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/smart-materials-and-masks), [Assets navigation](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/assets/navigation).

### W04 — Paint and correct in 3D and 2D

1. Select editable paint content or a paintable mask/effect.
2. Choose a brush/alpha and enabled material channels.
3. Paint on the model; adjust the camera and brush without accidental marks.
4. Continue in UV space and inspect the same underlying result in 3D.
5. Use erase, clone, smudge, straight strokes, symmetry, or temporary masking as appropriate.
6. Undo/redo and save/reopen without changing the result.

Painter's 2D view is an editing surface, not merely a UV preview. Regular projects restrict painting to the supported 0–1 domain; UV Tile projects expose tile grids and UDIM labels. Source: [2D view](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/viewport/2d-view).

### W05 — Place a decal or repeated fill

1. Choose a material/resource and the appropriate projection.
2. Edit numeric transforms or use a viewport manipulator.
3. Inspect orientation, repeat, seam behavior, and physical scale.
4. Add/edit coverage separately from the material.

Painter distinguishes fill projection from brush projection. Its documented fill options include UV, tri-planar, planar, spherical, cylindrical, warp, and match-per-tile fill. Source: [Fill projections](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/fill-projections/fill-projections).

### W06 — Revise the mesh or resolution

1. Open project configuration and select the revised mesh.
2. Choose stroke preservation/reprojection behavior; inspect material reassignment.
3. Preview unresolved sets/resources and likely consequences before applying.
4. Recompute/rebake as required; compare authored details after revision.
5. Save/reopen and verify exported results.

Painter provides mesh reimport while retaining project work, stroke-position preservation, and reassignment for disabled sets after material-ID changes. Source: [Project configuration](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/project-configuration).

### W07 — Deliver textures

1. Open File > Export Textures.
2. Choose target sets/tiles, destination, output template, resolution, format/precision, and padding.
3. Inspect the resolved output list and channel packing before writing.
4. Export; inspect per-output progress/errors and the destination.
5. Reopen the project and reproduce the delivery configuration.

Painter exports bitmap collections through output templates. Its export window has Export settings, Output templates, and List of exports tabs, with distinct Save settings and Export actions. Sources: [Export](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/export/export), [Export window](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/export/export-window/export-window).

## 6. Painting tools and parameter semantics

### 6.1 Tool families

| Tool | Expected operation | Strata acceptance focus |
|---|---|---|
| Paint | Apply multichannel brush marks | Correct target, alpha, channel enables, and stroke accumulation. |
| Eraser | Remove authored paint information | Reveal the underlying result; do not simulate erasure by painting a background color. |
| Projection | Apply view-aligned material/texture | Visible placement overlay and unambiguous source/transform. |
| Polygon Fill | Commit coverage/material to geometry regions | Distinguish fill operation from a persistent selection. |
| Smudge | Move/mix existing material information | Define sampled channels and seam behavior. |
| Clone | Copy material information from a chosen source | Visible source, relative/absolute modes, predictable source persistence. |
| Material Picker | Sample material properties | Temporary operation returns to the preceding tool. |
| Quick Mask | Temporarily constrain painting | Separate temporary coverage from saved layer masks. |
| Path | Editable surface curves driving detail | Visible points/handles, selectable paths, reusable settings. |
| Physical/particle modes | Simulated particle-driven marks | A real simulation workflow and controls are needed before claiming support. |

Reference tool roles: [Tool list](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/paint-tools/tool-list). Exact sampling/compositing semantics for clone, eraser, and smudge require tool-specific reference fixtures before numerical-parity claims.

### 6.2 Brush semantics

**Reference:** Flow affects individual dabs; Stroke Opacity caps the stroke as a whole. Size, spacing, angle, jitter, alignment, culling, alpha, stencil, and enabled material channels affect painting. Object, viewport, and texture size spaces differ. Pressure may drive supported parameters. Source: [Paint brush](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/paint-tools/paint-brush).

**Requirement:** controls need the same operational meaning, not just matching labels. Compare overlapping dabs and separate strokes, pressure ramps, camera zoom, UV seams, and disabled channels. Brush preview, cursor footprint, and applied footprint must agree for the chosen size space. Distinguish per-dab alpha, viewport stencil, and material image.

### 6.3 Current Polygon Fill behavior

**Reference:** 12.2 includes rectangular, full-loop, and partial-loop selection modes; triangle, polygon, connected-mesh, and UV-chunk fill scopes; intersection/contained-center tests; visibility filtering; blend/opacity; and multichannel filling. Loop modes require quads. Only the active set is fillable. Source: [Polygon Fill](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/paint-tools/polygon-fill).

**Requirement:** hover feedback must predict the committed region. Test occluded faces, backfaces, UV borders, disconnected components, triangulated meshes, and wrong-set geometry. Basic island fill alone does not satisfy 12.2 parity.

### 6.4 Paths

**Reference:** paths are editable curves on the 3D mesh, with paint/ribbon/filled/erase/smudge variants. Points adhere to the surface. Painter exposes path selection/management, tangents, direction, and display controls; UV-space path creation is not supported. No default path-tool shortcut is documented. Source: [Path tool overview](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/path-tools/path).

**Requirement:** preserve editable geometry, point identity, settings, and resources across save/reopen and supported resolution changes. Rasterized approximations must be labeled as such.

## 7. Default Windows interaction profile

Compact essential mappings below come from [Adobe's shortcut reference](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/settings/shortcuts). The linked table is authoritative for the complete mapping and macOS differences. Do not implement macOS by blindly replacing every Ctrl with Cmd.

| Action | Input |
|---|---|
| Paint / erase / projection / polygon fill / smudge / clone | 1 / 2 / 3 / 4 / 5 / 6 |
| Orbit / pan / zoom | Alt+LMB / Alt+MMB / Alt+RMB drag |
| Snapped orbit | Alt+Shift+LMB |
| Size/hardness | Ctrl+RMB: horizontal/vertical |
| Flow/rotation | Ctrl+LMB: horizontal/vertical |
| Size | [ / ] |
| Straight/snapped line | Shift+LMB / Ctrl+Shift+LMB |
| Environment rotation | Shift+RMB |
| Stencil rotate/move/scale | S+LMB/MMB/RMB |
| Clone source | V+LMB |
| Material picker / grayscale invert | P / X |
| Lazy mouse / symmetry | D / L |
| Quick mask edit/clear/invert | U / Y / I |
| Material / channels / maps | M / C / B; Shift reverses cycling |
| Split / 3D / 2D / swap | F1 / F2 / F3 / F4 |
| Perspective/orthographic | F5 / F6 |
| Frame / hide UI | F / Tab |
| Baking / painting / rendering | F8 / F9 / F10 |
| Bake settings / export | Ctrl+Shift+B / Ctrl+Shift+E |
| Manipulator show/translate/rotate/scale/space | Q / W / E / R / T |
| Undo/redo | Ctrl+Z / Ctrl+Y |

### 7.1 Input dispatch — Requirement

- Bind discrete actions through the existing command registry. Define continuous mouse gestures in one shared input policy.
- Resolve tool modifiers, camera modifiers, text fields, popups, and modal capture before changing pixels. A camera gesture must not begin a brush stroke.
- Evaluate more specific chords before overlapping simpler ones; define ownership for the entire drag, including modifier release.
- Consume painting only within the active viewport and eligible target; retain safe capture if the pointer leaves the viewport during a drag.
- Typing a name or number must not trigger tools, deletion, or painting commands.
- Keep documented defaults as the compatibility profile. Extra Strata bindings must not steal them.
- Display customized bindings in menus/tooltips and provide conflict detection and reset.
- Reserved shortcuts and explanatory messages are useful for discoverability but do not count as functional support.

### 7.2 Numeric editing

**Reference:** Painter sliders support drag, Shift precision, click-to-jump, arrow-key increments after focus, and direct text entry. Source: [Sliders](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/miscellaneous/sliders).

**Requirement:** show units, effective ranges, and reset values. Commit one undo operation per drag; cancellation restores the previous value. Validate typed values without silently substituting unrelated defaults. Verify exact modifier sensitivity and reset gestures in the reference build.

## 8. Assets and drag-and-drop

**Reference:** Assets combines library navigation, search, and type filtering. Search includes names, locations, and tags. Resource families include materials, smart materials/masks, filters, brushes, alphas, textures, and environments. Filters combine; an empty intersection can legitimately show no results. Sources: [Assets](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/assets/assets), [Assets navigation](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/assets/navigation).

The following destination matrix is a **Requirement**; reference-specific modifier and replacement semantics must be qualified before claiming exact compatibility.

| Dragged resource | Destination | Required result |
|---|---|---|
| Material | Stack insertion point | Create an editable fill at the indicated location. |
| Material | Compatible material/resource slot | Assign to that target; do not alter unrelated selections. |
| Smart material | Stack insertion point | Insert an editable folder and its dependencies as one action. |
| Smart mask | Layer/mask | Apply mask effects with documented merge/replace policy. |
| Brush/tool preset | Compatible tool context | Load settings and show the resulting active tool. |
| Alpha | Alpha slot | Change dab coverage only. |
| Texture | Channel/stencil/resource slot | Assign with explicit interpretation appropriate to that slot. |
| Environment | Viewport/environment slot | Change lighting/display resource, not authored color. |
| Unsupported resource | Any target | Reject with a reason; preserve the project. |

Provide drop previews, compatible-target highlighting, insertion indicators, and an intelligible rejection state. Define click, double-click, stack drop, viewport drop, modifier-drop, and resource-slot drop separately; do not assume they all mean “apply to selection.” Imported resources need type, project/library scope, availability, and missing-file feedback.

## 9. Visual guidance and feedback

### 9.1 Visual hierarchy — Requirement

Use a neutral dark editing environment, compact readable typography, consistent icons, and restrained selection accents. Keep the model and texture result visually dominant. Use borders/spacing and state contrast to distinguish the viewport, panel headers, editable fields, and selected targets. Do not rely only on color to communicate critical states.

Exact Adobe palette values, spacing, font metrics, selection colors, icon artwork, and panel proportions are **Verify**, not established facts in this document. Reuse Strata's theme tokens; avoid distributing hardcoded style values throughout panels. Keep Strata branding while matching familiar roles, terminology, and interaction hierarchy.

### 9.2 State-to-feedback contract

| State or transition | Required visible guidance | Failure to avoid |
|---|---|---|
| Tool changed | Checked tool, relevant controls, suitable cursor | Icon changes but operation stays stale. |
| Content vs mask selected | Distinct thumbnail outline and Properties context | Painting the wrong target. |
| Mask inspection | Explicit mask-view label and return path | User mistakes grayscale inspection for lost color. |
| Solo channel/map | Persistent channel/map name | User mistakes diagnostic view for material changes. |
| Layer/effect disabled | Stable disabled marker and recoverable toggle | Looking deleted or silently bypassed. |
| Hover vs selection | Different transient/persistent treatment | Hover changes authoring scope. |
| Drag pending | Target highlight and insertion/nesting preview | Drop result cannot be predicted. |
| Geometry fill | Region/wireframe preview; prohibited cursor outside scope | Wrong-set or hidden-face edits. |
| Brush over surface | Readable footprint following alignment/size space | Preview disagrees with applied mark. |
| Symmetry/lazy mouse | Plane/axis or trailing-cursor guide | Invisible duplicated marks or unexplained lag. |
| Projection/path editing | Handles, selected points, bounds/direction | Manipulator exists without a readable editing mode. |
| Bake validation | Cage/high/low distinction, error overlay, linked message | Generic error with no location or fix. |
| Computation | Task label, progress, coherent completed result | Unexplained freeze or mixed old/new output. |
| Invalid resource/anchor | Marker at affected input and repair action | Silent fallback looks like a valid result. |
| Unsaved work | Persistent modified state; clear save/recovery choices | Export appears to save the project. |

These are Strata design requirements. Specific Adobe feedback already documented includes viewport computation progress and diagnostic view modes: [Viewport](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/viewport/viewport), [Display settings](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/display-settings/display-settings).

### 9.3 12.2 details that must be tracked explicitly

Adobe documents cage-offset painting, geometry highlighting from set/tile hover, Polygon Fill wrong-set feedback, additive brush behavior, and optional order-independent transparency. Cage offsets have a green visualization and affect the baking cage itself. Display Settings was reorganized into Environment, Camera, Post effects, Render, and Visualization groups. Source: [12.2 release notes](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/release-notes/version-12-2).

**Requirement:** capture dedicated scenarios for these behaviors. Do not treat a generic paint tool, a cage-distance slider, or a single transparency checkbox as equivalent to the documented workflows.

## 10. Display, color, and export interpretation

**Reference:** material lighting, single-channel inspection, and mesh-map inspection are separate view categories. Shader instances can be shared or set-specific. Color management is a project concern with resource/channel interpretation. Sources: [Display settings](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/display-settings/display-settings), [Shader Settings](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/shader-settings/shader-settings), [Color management](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/color-management/color-management).

**Requirement:** distinguish environment exposure, display transforms, shader response, authored values, and output conversion. Rotating the environment must not dirty painted pixels. Numerical roughness/mask/normal data must not receive color transforms intended for color channels. Explain missing opacity/scattering visibility through channel/shader configuration rather than silently changing the brush.

**Reference:** the output-template editor separates template list, output textures, and available input/converted maps. Inputs are dragged into components, with visual component/source indicators. Converted outputs include combined normals and roughness-to-glossiness conversions. Source: [Creating Output templates](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/export/output-templates/creating-export-presets).

**Requirement:** implement semantic channel packing and a preview of resolved destinations. Show which normal convention and mixing path are exported. Validate duplicate names, unsupported precision, missing inputs, and tile expansion before writing. Preserve existing Strata output staging and failure protections.

## 11. Functionality coverage ledger for future agents

This inventory is a scope checklist, not a declaration of completion or exhaustive shader/preset parity. Each row needs separate engine, UI, persistence, delivery, and reference evidence.

| Capability family | Required qualification scope | Starting references in this repository |
|---|---|---|
| Workspace/navigation | Docking, reset, scale, input, camera, split views, shortcuts | `strata/app.py`, `strata/viewinput.py`, `strata/ui/theme.py`, `strata/ui/commands.py` |
| Project lifecycle | New/open/save, recovery, portability, resources, templates, revisions | `docs/PERSISTENCE.md`, `docs/MESH_REVISIONS.md` |
| Sets/channels/tiles | Material scope, channels/precision, shader bindings, UDIM selection and cross-tile work | `docs/CHANNELS.md`, `docs/SHADER_WORKFLOWS.md`, `docs/architecture/TILES.md` |
| Layers/masks/effects | Hierarchy, per-channel blending, mask tools, ordered effects, anchors, instancing | `strata/layers.py`, `strata/ui/effects.py`, `docs/EFFECTS.md` |
| Brush authoring | Tablet, alpha, flow/opacity, jitter, spaces, stencils, symmetry | `docs/BRUSHES.md`, `docs/PAINT_OPERATIONS.md`, `strata/painter.py` |
| UV painting | Direct UV input, pan/rotate/zoom, domain limits, shared result | `docs/UV_PAINTING.md`, `strata/ui/uvview.py` |
| Projection/details | Fill mappings, transforms, warp, paths/ribbons/regions, labels | `docs/FILL_MATERIALS.md`, `docs/AUTHORED_OBJECTS.md` |
| Baking/correction | Set/map configuration, high/low matching, cage/skew correction, diagnostics | `docs/BAKE_DISPLAY_LIBRARY.md`, `docs/ADVANCED_BAKING.md` |
| Resource ecosystem | Search/filter/import, preset creation, scope, relink/update | `strata/library.py`, `strata/resources.py`, `docs/PROCEDURAL_IMPORTS.md` |
| Procedural fidelity | Native generators, external graph runtime, unsupported inputs | `docs/PROCEDURAL_IMPORTS.md`, `strata/substance/backends.py` |
| Look development | Environment, cameras, shader channels, color, transparency, displacement | `docs/SHADER_WORKFLOWS.md`, `docs/architecture/COLOR.md`, `strata/renderer.py` |
| Delivery | Export templates/packing, mesh export, pipeline setup, reproducibility | `docs/EXPORT.md`, `docs/DELIVERY.md` |
| Specialist extensions | Particles, offline rendering, custom shaders/scripts, USD variants, devices | `docs/EXTENSIONS.md`, `docs/FEATURE_PARITY.md`; define separate reference cases |

Adobe's [documentation index](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/home) also identifies physical size, automatic UVs, dynamic material layering/strokes, scattering, post processing, Iray, sparse virtual textures, custom shaders, SpaceMouse, USD, and scripting. Agents must evaluate these explicitly rather than infer coverage from the basic painting loop. Follow the linked specialist documentation before implementation.

## 12. Implementation strategy in Strata

### 12.1 Preserve the existing architecture

Repository inspection confirms an existing docking workspace, theme system, command registry, painting engine, and many dedicated feature panels. Extend these paths. This document does not authorize replacing the renderer, project format, or UI framework.

| Concern | Existing code entry point | Agent instruction |
|---|---|---|
| Layout, menus, context, stack/assets | `strata/app.py` | Inspect dock construction and existing target state before changing layout. |
| Commands and bindings | `strata/ui/commands.py` | One action identity shared across menus, shortcuts, and search. |
| Style and density | `strata/ui/theme.py` | Centralize tokens and scaling; compare state visibility. |
| Camera/UV gestures | `strata/viewinput.py`, `strata/ui/uvview.py` | Share gesture priority and correct viewport coordinates. |
| Paint behavior | `strata/painter.py`, `strata/journal.py` | Preserve stroke semantics and replay provenance. |
| Material/effect/bake controls | `strata/ui/material.py`, `strata/ui/effects.py`, `strata/ui/bake.py` | Route changes through existing engine transactions. |
| Authoring model and storage | `strata/engine.py`, `strata/layers.py`, `strata/projectio.py` | Stable IDs, undo, dirty state, cache invalidation, migration. |

Existing documentation contains qualification limits and some stale descriptions. Reproduce each behavior before classifying it. The working tree already contains extensive in-progress changes; preserve unrelated work.

### 12.2 Suggested work order

1. **UX01 Target clarity:** active set/tool/content/mask/effect state, eligibility, Properties synchronization.
2. **UX02 Muscle memory:** gesture dispatch, default bindings, numeric editing, focus and drag capture.
3. **UX03 Workspace:** default layout, docking/reset, scaling, viewport labels and overlays.
4. **UX04 Material construction:** layer menus, structural drops, mask/effect ordering, anchors, assets.
5. **UX05 Complete workflows:** baking, projection/path editing, revision, and output configuration.
6. **UX06 Specialist parity:** current 12.2 additions and advanced features identified in the ledger.

These IDs describe UX work; they supplement rather than replace T00–T21 in the implementation plan. A high-risk correctness issue takes priority over visual polish.

For every assignment, record reference version/source, existing behavior, intended behavior, changed modules, persistence/undo implications, validation evidence, and remaining differences. Use the established compatibility labels: **workflow equivalent**, **numerically validated against a reference**, or **approximate**.

## 13. Acceptance scenarios and handoff evidence

Use a two-material prop with multiple UV islands, a seam test, an occluding shell, a quad loop, a low/high bake pair, a small multi-tile fixture, asymmetric alpha, and distinct channel values. Keep fixture/resource hashes and deterministic seeds. Do not depend on Adobe starter assets being installed.

| ID | Scenario | Pass condition |
|---|---|---|
| A01 | Start/reset/resize workspace | Necessary panels remain reachable; selected context survives layout changes. |
| A02 | Move between sets and content/mask/effects | Highlight, Properties, tools, and actual edit target agree. |
| A03 | Navigate during a paint session | Every camera/modifier gesture changes only its intended state; no stray mark. |
| A04 | Paint Color + Roughness while inspecting another channel | Only enabled authoring channels change; inspection has no write side effect. |
| A05 | Compare low flow and low stroke opacity | Accumulation differs correctly and survives undo/save/reopen. |
| A06 | Build/reorder a generator + paint + filter mask | Operation order is visible and affects pixels; target remains correct. |
| A07 | Isolate/disable/re-enable a mask | Each state is distinguishable and reversible without losing effects. |
| A08 | Reorder/nest multiple layers | Preview matches final hierarchy; undo restores IDs, order, pixels, and selection. |
| A09 | Apply material, smart material, smart mask, alpha, environment | Each resource changes its intended target; rejected drops leave no partial edits. |
| A10 | Paint through 3D/UV seam and tile transitions | Views update coherently with documented domain and occlusion rules. |
| A11 | Use Polygon Fill on quads, UV islands, hidden and wrong-set faces | Scope/visibility settings predict committed coverage; unsupported topology is explained. |
| A12 | Correct cage and inspect bake failures | Preview reflects correction; logs identify affected set/map and repair settings. |
| A13 | Edit a projection/path, then save and resize | Supported editable data and placement survive; limitations are explicit. |
| A14 | Revise mesh/UVs/material names | Reprojection/reassignment behaves as declared; failure preserves the original. |
| A15 | Export packed multi-set/tile textures | Resolved names, dimensions, precision, components, and normal convention match preview. |
| A16 | Missing resource, invalid anchor, unsupported procedural | Visible specific diagnosis; repair possible; no silent fidelity claim. |
| A17 | Type into fields with modal/popup open | Editing shortcuts do not leak into paint, tools, deletion, or global actions. |
| A18 | Repeat at high DPI and with a tablet | Controls, hit regions, brush footprint, pressure, and focus remain coherent. Record untested hardware separately. |

For each changed workflow, supply: before/after screenshots at the same viewport size and scale; a short action sequence; expected state/pixel changes; undo/redo evidence; saved/reopened result; exported output where relevant; and explicit failures/skips. Prefer meaningful targeted regression checks over tests that merely assert a widget or method exists.

### 13.1 Reference capture still required

Before describing the UI as visually identical, capture the exact Painter build, operating system, display scaling, window size, workspace preset, and customized bindings. Record these states:

1. Default painting workspace and all three viewport layouts.
2. Paint, fill, folder, selected mask, disabled mask, isolated mask, and expanded effect stacks.
3. Asset search/type filtering and every relevant drop destination/modifier.
4. Brush quick properties, numeric editing, selection/hover/focus/disabled states.
5. Baking setup, cage/skew correction, errors, completion, and return to painting.
6. Export settings, template component editor, and export progress/failure list.
7. Narrow-window, high-DPI, floating-panel, and reset-layout states.

Annotate panel bounds, spacing, icon purpose, interaction target, and transient feedback. Treat documentation illustrations as supporting reference, not proof of installed-build defaults. Compare artist task completion and editing correctness alongside visual similarity. Do not claim all Painter users can migrate without friction until representative artists have completed these workflows and their observed problems have been resolved.
