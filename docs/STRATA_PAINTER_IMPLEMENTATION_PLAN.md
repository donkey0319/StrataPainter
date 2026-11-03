# StrataPainter implementation plan for AI agents

Additional scoped extension: **T22 — live AI assistant** adds a dockable provider
chat, a bounded native tool contract, project documentation/state/viewport access,
an authenticated local MCP bridge, native undo/cancellation and project-scoped
conversation resume. Source acceptance requires real signed-in Codex and Claude
Code edits plus resumed turns, a real-UI MCP/save/reopen check, input validation
and native transaction regression. Qualification and remaining packaging/provider
limits are recorded in IMPLEMENTATION_STATUS.md and AI_ASSISTANT.md.

Date: October 25, 2026  
Starting baseline: `cefb609`, plus the local capability review  
Reference product: Adobe Substance 3D Painter 12.2 workflows

## Mission and target outcome

Develop StrataPainter into a production-capable material and texture authoring application with workflows familiar to Substance Painter users. Preserve the existing Python/OpenGL engine and build on its implemented capabilities. Prioritize correct delivery, editable materials, reliable project revisions and predictable rendering before specialized tools.

This document is an execution specification for future implementation agents. It does not mean any work package has already been implemented. Reinspect the checkout before starting because source, APIs and feature availability may have changed.

Read [the capability review](STRATA_TEXTURE_PIPELINE_REVIEW.md) and [the engine API](ENGINE_API.md) first. The review links the implementation and Adobe reference documentation. Use source code and reproducible tests to establish current behavior; the README contains stale limitations.

### What emulating Painter means

Match the artist's production tasks, data preservation and observable results. Familiar menus, panels and shortcuts help, but visual resemblance alone does not satisfy a work package.

The target workflow is:

1. Import a mesh, identify materials and UV tiles, and validate texture prerequisites.
2. Bake or import mesh maps and diagnose projection errors.
3. Build editable multichannel materials, masks, filters, anchors and reusable assets.
4. Paint in 3D or UV space with responsive brushes and real tablet input.
5. Change resolution or revise geometry without silently losing authored detail.
6. Preview through a documented color and shading pipeline.
7. Save a portable, recoverable project and export correct, uniquely named outputs.

Use three explicit compatibility levels: **workflow equivalent**, **numerically validated against a reference**, and **approximate**. Do not describe an approximate generator, imported stroke or shader as identical to Adobe's implementation. An optional external Substance evaluation backend must have a verified available runtime; the native workflow must continue to function without it.

## Execution rules for implementation agents

### Before editing

- Read applicable repository instructions and inspect Git status. Preserve unrelated local changes, including the capability review and this plan.
- Select one work-package ID and inspect its prerequisites. A prerequisite is complete only when its acceptance evidence exists.
- Reproduce the current behavior with a small fixture. For an existing feature, extend it rather than adding a parallel implementation.
- Inspect the relevant existing tests and API call sites. Preserve backward compatibility unless the package explicitly requires migration.
- Verify current official documentation before introducing a third-party dependency or relying on a particular library API. Record dependency and platform implications in the handoff.
- Use a working native Python with the project's dependencies and an OpenGL 3.3 context. The `.venv` executable failed to launch during the review; do not assume that environment works. Do not report GPU checks as passed when they did not run.

### During implementation

- Keep `engine.py`, project data and rendering independent of ImGui. UI panels call engine operations; they do not implement a second material pipeline.
- Keep GPU creation, mutation and destruction on the owning context thread. Background jobs may decode files or prepare CPU data and then enqueue GPU work.
- Reuse the command registry for actions that belong in menus, shortcuts and command search.
- Route user edits through undoable transactions with dirty-state and cache invalidation. A slider drag is one history action, not hundreds.
- Treat serialization, dependency ownership and undo behavior as part of every new editable feature.
- Use stable resource/layer/effect/set identities. Display names and list positions are not durable references.
- Do not replace the entire renderer, UI or project format to complete a narrowly scoped package. Extract bounded modules when needed.
- Put test outputs and caches in task-local directories. Do not modify the user's asset shelf, normal settings or source assets during verification.

### Definition of done for every package

The implementation must satisfy its acceptance criteria, include meaningful regression coverage for its failure modes, update relevant API/user documentation, and provide a handoff. Visually verify changed artist workflows in the running application. Report checks that could not run separately from failures and passes.

A UI feature is complete only when an artist can perform the task through the UI, save, reopen, continue editing and obtain correct exports. A data-model field or reserved shortcut does not establish feature completion.

Do not publish releases or claim overall Painter parity merely because one package is complete.

## Architecture contracts

Introduce these contracts incrementally. Suggested new module names below are proposals, not files that already exist.

| Contract | Required behavior |
|---|---|
| Edit transaction | Captures before/after state or deltas; commit, undo and redo invalidate the same dependent outputs and update modified state. Cancellation restores the original state. |
| Stable identity | Persistent IDs for sets, layers, effects and resources. References survive rename, reorder, save/load and migration. Copying defines when IDs are regenerated versus intentionally shared. |
| Channel descriptor | Stable key, semantic, component count, default, storage precision, color/data classification, blend rules and export eligibility. Existing `C/R/M/H/N/E/O` remain compatible. |
| Resource record | ID, content hash, kind, source path, embedded location when present, relevant color interpretation, and missing/changed status. Cache paths are not project identity. |
| Evaluator request | Explicit set, tile, resolution, channel subset and revision. Interactive preview and export share evaluation semantics. |
| Dependency invalidation | A change to a layer, resource, anchor, mesh map or color setting invalidates affected dependents; references detect cycles and stale sources. |
| Export manifest | Resolve all set/tile/map destinations and settings before writing. Preview and writer consume the same manifest. Duplicate paths are errors. |
| Durable project | Versioned schema, explicit migrations, atomic writes, resource manifest and deterministic restoration. Old raster paint remains valid even after replayable operations are introduced. |
| Paint operation | Versioned settings snapshot, resource IDs, seed, samples and coordinate provenance; declares replayable versus raster fallback behavior. |
| Tile address | Explicit `(texture_set_id, u, v)` and local UV. A material set can contain multiple tiles. A single legacy set defaults to tile `(0, 0)`. |

Avoid converting all shaders to a speculative fully dynamic implementation immediately. A channel registry may initially drive existing fixed GPU layouts through adapters; user-defined channels require real allocation and evaluation support later.

Before the stroke journal, reimport or UDIM package lands, document its schema and migration in `docs/architecture/`. Before two agents touch the same contract, agree on the contract and file owner.

## Milestones and dependency order

| Milestone | Packages | Exit condition |
|---|---|---|
| M0 Reliable core | T00–T03 | Reproducible baseline, safe multi-set exports, durable save/load and consistent undoable edits. |
| M1 Complete prop authoring | T04–T09 | Existing engine features accessible to artists, 2D paint, real brush controls, bake setup and reusable resources. |
| M2 Production revisions | T10–T13 | Bounded memory, managed color/tangents, persistent paint and validated mesh revisions/high-resolution evaluation. |
| M3 Large assets and content | T14–T16 and T21 | UDIM workflow, advanced bake correction, UV preparation and explicit procedural/import fidelity. |
| M4 Broader Painter workflows | T17–T19 | Editable detail tools, broader shading/channels and tested delivery integrations. |

T20 maintains CI, documentation and release gates throughout all milestones. It is not a final cleanup task. Each milestone is a usable release boundary, subject to its actual validation evidence.

## M0 Reliable core

### T00 Establish reference fixtures and the baseline

**Dependencies:** none.  
**Entry points:** `tests/feature_check.py`, `tests/headless_check.py`, `tests/ui_logic_check.py`, `tests/substance_check.py`, `.github/workflows/release.yml`.

1. Establish runnable CPU, offscreen GPU and interactive UI test commands on the execution host. Document Python/GPU/driver/context details and optional dependencies.
2. Create small deterministic fixtures: a two-material prop; a UV-seam and mirrored-UV mesh; a low/high pair; a project with distinct per-set bake settings; bitmap resources; a painted mask; and nested groups with anchors.
3. Record existing failures independently of new regressions. Capture reference channel exports and UI screenshots with a manifest of fixture hashes and settings.
4. Add a capability ledger identifying engine support, UI support, serialization and validation separately.

**Acceptance:** another agent can regenerate the baseline using documented commands. Fixture generation uses fixed seeds. Expected artifacts and known failures are explicit. No Adobe installation is required for the native baseline.

### T01 Replace the unsafe UI export path

**Dependencies:** T00.  
**Entry points:** `exporter.py` templates, `_expand`, `export_textures`, legacy `export`; `app.py` export dialog and `_export_files`.

1. Extract a pure export-manifest builder. Include set ID/name, map, destination, format, depth, size, padding and channel packing.
2. Make the desktop dialog use modern templates and include `$textureSet` in multiset filenames. Keep the legacy API callable, but reject ambiguous paths or expand them safely with documented behavior.
3. Validate duplicate names after token expansion, sanitization and platform-aware path normalization. Check invalid paths before creating output files.
4. Expose set selection, formats/depths, resolution, padding, map enables and template load/save. Add a template editor after the basic export flow is correct.
5. Generate the visible output list from the same manifest used by the writer. Stage outputs so an evaluation failure does not silently present a partial export as successful.

**Acceptance:** Metal and Rubber sets produce separate outputs with different verified pixel values. Sanitized-name collisions fail before writing. UI preview exactly lists the outputs. DirectX/OpenGL normals, ORM and Unity smoothness packing pass content checks. Existing single-set exports retain documented behavior.

### T02 Make projects portable and restoration reliable

**Dependencies:** T00; coordinate resource identity with T03.  
**Entry points:** `engine.py` save/load, `_high_for`, `new_project`; `resources.py`; `library.py`; `substance/convert.py` bitmap cache.

1. Reproduce and fix restoration of distinct bake settings for each texture set. Preserve the mesh normalization transform needed to align external high-poly sources on reload.
2. Add a resource manifest and project-relative/embedded resolution policy. Offer a portable save mode that collects referenced textures, alphas, environments and optional high-poly sources.
3. Store validated baked-map caches with provenance; rebuild only when dependencies/settings require it. Missing source geometry must not silently replace a valid cached bake with a different result.
4. Write to a temporary sibling file, verify the archive and then atomically replace the destination. Add backup rotation and recoverable autosave through the same serialization path.
5. Load into staged state. Corrupt files, unsupported schema versions and missing resources produce actionable diagnostics without destroying the open project. Add relink/collect controls.

**Acceptance:** save/reopen preserves each set's maps/settings, layers and resource interpretation. A portable project opens after its source directory is moved. Injected save failure preserves the previous valid archive. An invalid load preserves the current session. Autosave recovery is exercised, not only configured.

### T03 Unify edits and persistent identities

**Dependencies:** T00; shared schema agreement with T02.  
**Entry points:** `engine.py` history and layer operations; `layers.py` IDs/serialization; `app.py` property helpers and commands.

1. Introduce persistent IDs and migrate existing projects without breaking shared instances or anchor references. Keep names editable independently.
2. Provide transaction-based engine operations for property edits, effect edits, tree operations and resource assignments. Replace direct UI assignments incrementally.
3. Define undo boundaries for continuous controls, compound actions and canceled dialogs. Ensure cache invalidation follows undo/redo as well as forward edits.
4. Define instance semantics explicitly. Shared material parameters and resolution-dependent GPU paint storage must not accidentally share/release incompatible buffers across sets.

**Acceptance:** rename, reorder, copy, instance, undo, redo and save/reopen preserve intended references. A canceled slider/operation restores state. Editing one set does not invalidate another set's GPU ownership. Modified state reflects effective edits and recovery correctly.

## M1 Complete prop authoring

### T04 Consolidate channel behavior

**Dependencies:** T02, T03.  
**Entry points:** `layers.py` channel constants, compositor, painter, exporter and channel property controls.

Create channel descriptors for the existing seven channels and remove conflicting assumptions about their count, precision and color interpretation. Preserve old channel keys and saved data. Drive labels, default values, controls and export source eligibility from descriptors. Document normal and height semantics and independent layer opacity versus the opacity channel.

**Acceptance:** all seven channels can be independently enabled, assigned, painted, blended, saved and exported. Defaults and migration preserve existing appearance within declared precision tolerances. Do not claim user-channel support yet.

### T05 Expose fill materials and projections

**Dependencies:** T01–T04.  
**Entry points:** `app.py` `_props_fill`, material properties and Assets panel; `layers.Projection`; `compositor._set_proj`; `resources.py`.

Add bitmap slots, clear/relink actions and constant values for every existing channel. Expose all implemented mapping modes, scale, offset, rotation, axis and tri-planar sharpness. Add resource previews and imported-resource selection. Add direct manipulation by calling the same projection-edit transaction as numeric controls; begin with translation/rotation/scale, leaving warp to T17. Expose per-channel blend/opacity and per-set resolution changes.

**Acceptance:** an artist assembles an external PBR map set, changes its projection, edits normal/emissive/opacity values and exports it without Python. Undo and save/reopen retain mapping and channel configuration. No editable UI control is a no-op.

### T06 Expose the mask and effect graph

**Dependencies:** T03–T05.  
**Entry points:** `layers.py` effects, `engine.py` effect APIs, `compositor.py` effect/anchor evaluation, layer stack and properties UI.

1. Add effect rows and property editors for all implemented content/mask effects, with enable, reorder, blend, opacity, copy and delete.
2. Implement stable anchor creation/reference selection, source-channel selection and missing-source/cycle diagnostics. Specify whether each anchor captures layer content, mask or accumulated output; migrate existing semantics explicitly.
3. Add independent paint effects inside mask stacks. Give each paint effect its own resource, target selection and undo history so filters can run before or after that paint.
4. Expose geometry masks and ID color selection, including picking colors from the viewport.

**Acceptance:** create painted height, reference it in another layer's mask, place a painted correction between two filters, rename/reorder sources and save/reopen. The result remains editable and stable. Cycles fail clearly; they never reuse stale cached textures silently.

### T07 Complete brush controls and tablet input

**Dependencies:** T03, T04; resources from T02.  
**Entry points:** `layers.Brush`, `painter.Stroke`, `app.py` brush properties/input, `resources.py` alpha loading.

Expose alpha selection/inversion, stroke opacity, jitter, alignment, pressure response, angle following, size spaces and symmetry center/count. Add multichannel projection slots. Integrate a tablet input adapter that feeds real pressure into stroke samples, with a mouse fallback of pressure 1.0. Keep input capture separate from brush evaluation and record deterministic seeds.

**Acceptance:** synthetic pressure samples produce expected coverage/size changes; a physical tablet smoke check verifies the actual event path when hardware is available. Verify seam crossing, backface behavior, stencil placement, mirror/radial painting, clone and smudge. A synthetic event test alone does not certify hardware support.

### T08 Implement full UV-space painting

**Dependencies:** T03, T04, T07.  
**Entry points:** active `ui/uvview.py`, renderer 2D APIs, UI input dispatch, painter; imported UV replay may inform shared math.

Create a shared view-to-surface/UV input abstraction. Route 2D paint, erase, mask paint, projection, clone and supported smudge through the engine. Add UV-space cursor sizing, wireframe and complete channel diagnostics. Define behavior for overlapping UVs and input on empty UV background. Keep split-view coordinate handling correct under UI scaling and view swapping.

**Acceptance:** pan/zoom and split layouts do not offset strokes. 2D and 3D edits update each other immediately, survive undo and save, and produce expected exports. Explain tool-specific unsupported cases in the UI instead of dropping input.

### T09 Complete baking, display and native library controls

**Dependencies:** T02–T07; T01 for mesh-map export.  
**Entry points:** `baker.BakeSettings`, `engine.set_high_poly/rebake`, bake dialog, display panel, `library.py` APIs.

Add high-poly source management, frontal/rear distances, map selection, ID settings, per-set/all-set targets and bake progress. Add external mesh-map assignment/replacement with channel, dimensions, color/data interpretation and set-matching validation; generators must consume these assigned maps through the same map interface as native bakes. Display hit coverage and preview baked channels. Expose environment import/rotation/exposure and alpha/emissive settings. Connect native smart-material, smart-mask, brush and template save/load to searchable Assets UI, with thumbnails, dependency collection and drag/drop.

**Acceptance:** build a reusable weathered material, save it, apply it to a second mesh, load a high-poly source, bake, change environment and export through the UI. Cancel/failure leaves usable project state. Distinct per-set bake settings survive this workflow.

## M2 Production revisions

### T10 Bound GPU memory and incremental evaluation

**Dependencies:** T03, T04, T06; can start profiling during M1.  
**Entry points:** `gpu.py`, paint allocation/history in `engine.py` and `painter.py`, compositor caching.

1. Instrument estimated allocations, live resource ownership, evaluation timings and undo storage. Add configurable resource/history budgets with visible diagnostics.
2. Allocate paint channels lazily. Missing storage must resolve to descriptor defaults without allocating full-size textures.
3. Store undo deltas for changed regions or internal tiles. Internal storage tiles are not UDIM tiles; keep those concepts separate.
4. Invalidate/evaluate only dependent outputs. Reuse resources safely and release them on project close, deleted layers and history eviction.
5. Preserve instance semantics across different set resolutions. Prefer shared definitions with separately owned evaluated buffers.

**Acceptance:** the existing four-channel painting path no longer snapshots all seven channels. Stress tests show bounded history, no continuing resource growth after repeated open/close, and measurable improvement over T00. Record timings and peak memory for fixed 2K/4K workloads on named hardware; do not compare different GPUs as if results were equivalent. Set a documented product budget from measured hardware before declaring performance complete.

### T11 Establish color and tangent-space correctness

**Dependencies:** T02, T04, T05, T09.  
**Entry points:** image/resource interpretation, shader color conversions, renderer environment, compositor blending, exporter and `mesh.compute_tangents`.

1. Write the color contract first: interpretation of every input, working-space blending, UI color picking, display transform and export transform. Data maps bypass color transforms.
2. Add an OCIO-backed managed mode with a verified platform-compatible integration. Keep an explicit legacy mode for old projects; do not silently change their appearance.
3. Apply display transforms only to display output. Packed data maps and normals must never receive a display tone curve. Include color configuration in cache/provenance keys.
4. Establish target tangent conventions and integrate or validate a MikkTSpace-compatible implementation. Handle mirrored UV handedness and normal convention conversions explicitly.

**Acceptance:** known swatches and linear/HDR ramps survive intended import/export transforms; roughness/normal values remain unchanged. A reference mesh rendered in Strata and the named target engine agrees under matched settings. Document tolerances, exclusions and reference versions. Test legacy migration separately from managed mode.

### T12 Persist native paint operations and resolution-aware evaluation

**Dependencies:** T02–T04, T07, T08, T10; coordinate color provenance with T11.  
**Entry points:** `painter.Stroke`, stroke begin/end in engine, save schema, resolution changes and export evaluation.

1. Add a versioned operation journal independent of undo history. Capture brush settings/resources, channel selection, seed, pressure/time samples, view matrices, viewport dimensions, surface/UV coordinates, mesh revision and target layer/effect.
2. Preserve coordinate provenance: native 3D operations and native UV operations have different re-evaluation/reprojection policies. Snapshot resource content or immutable IDs so later file changes do not rewrite old strokes unexpectedly.
3. Store checkpoints for fast replay and legacy raster bases. Imported Painter replay may feed the journal, but do not assume it supplies equivalent brush information.
4. Define clone/smudge inputs and source revisions. Either replay deterministically against recorded dependencies or preserve explicit raster checkpoints and disclose their limits. Never discard those tools' results to obtain nominal replay support.
5. Evaluate procedural fills and supported operations at requested output resolution. Exporting at 4K must not temporarily damage a 2K editing session or merely resize its final composite.

**Acceptance:** a replayable alpha stroke exported from a 1K editing session at 4K matches direct 4K evaluation within a declared tolerance and contains regenerated detail. Undo-history eviction does not delete the journal. Old raster-only projects open and retain their appearance; increasing their size is honestly classified as resampling.

### T13 Add transactional mesh reimport and reprojection

**Dependencies:** T02, T03, T09, T12; validate normals using T11.  
**Entry points:** mesh loaders/normalization, texture-set mapping, operation journal, bake resources and project replacement UI.

1. Preview old/new mesh correspondence, material/set mapping, UV changes and changed bounds. Preserve physical scale and normalization transforms deliberately.
2. Reproject 3D operations with their recorded provenance; preserve UV operations when UV correspondence permits it. Define behavior for raster-only layers and imported/baked resources.
3. Stage reimport, rebake and replay before committing. Provide a report for unmapped sets, missed samples and changed dependencies. Offer commit/cancel and undo or a recoverable pre-reimport checkpoint.
4. Retain unmapped authored content for reassignment rather than deleting it silently.

**Acceptance:** UV-only mesh revision, changed bounding box, renamed material, removed material and a modest geometry revision each have deterministic documented results. Cancellation and projection failure preserve the original project. No blanket guarantee of arbitrary topology-change preservation is allowed.

## M3 Large assets and procedural content

### T14 Implement UV tiles and UDIM delivery

**Dependencies:** T01–T04, T08, T10, T12, T13.  
**Entry points:** mesh UV handling, TextureSet, bake/evaluation storage, painter, compositor, UV view, exporter and schema.

1. Model a texture set as a material with one or more tile addresses. Migrate legacy projects to tile `(0, 0)`.
2. Define tile addressing and validation, including boundaries, faces crossing tiles and unsupported coordinates. UDIM numbering applies only where its supported convention is valid.
3. Bake/evaluate tiles independently, cache by set/tile/revision and stream within the memory budget. Handle cross-tile painting and masks without treating each tile as a different material.
4. Add tile list/isolation, UV-grid navigation, per-tile diagnostics and explicit resource assignment for image sequences.
5. Add tile-aware export naming and manifests, including collision detection and `$udim` or an equivalent documented token. Audit anchors and instances for tile context.

**Acceptance:** one material spans 1001/1002/1011; a stroke across the 1001/1002 boundary paints continuously. Saving, reimporting, changing resolution and exporting preserve tile identity. Test a boundary-touching face, several materials, missing tile resources and memory eviction.

### T15 Add advanced bake control and correction

**Dependencies:** T09–T11, T13; tile support requires T14.  
**Entry points:** baker/raycast, BakeSettings, bake UI and map provenance.

Add high/low mesh-name pairing, custom cage import and validation, cage-intersection/miss visualization, configurable supersampling and per-baker controls. Then add painted ray-direction/skew correction and painted cage-distance correction as editable fields with undo and persistence. Define self-occlusion and cross-part occlusion explicitly. Automatic cage generation is a separate enhancement after custom/distance-based cages are reliable.

**Acceptance:** thin gaps, nearby unrelated parts, skewed surface details, inverted cage areas and unmatched names have targeted tests and visible diagnostics. Corrections survive rebake and save/reopen. Measure geometric outcomes and reference maps; do not require Adobe pixel identity for a different baker.

### T16 Expand native procedural content and import fidelity

**Dependencies:** T02, T04–T06, T09, T11, T12; tile-aware imports require T14.  
**Entry points:** generator/effect shaders, presets/resources, `substance/convert.py`, `substance/replay.py`, import reports and compatibility checks.

1. Build a fixture-based compatibility matrix by source feature and file version. Separate read success, retained editability, appearance deviation, skipped operations and truncation.
2. Extend native procedural nodes/filters according to real material needs: richer grunge, ramps/gradient maps, transforms, directional warp and sharpen with documented parameters. Store native graphs explicitly instead of growing name-guessing rules indefinitely.
3. Improve bitmap extraction, source projections, channel mappings and imported stroke alpha/jitter/symmetry when source data is available. Retain unsupported metadata for diagnostics and future migration.
4. Replace hard silent replay limits with visible budget controls, progress/cancel, checkpointed continuation and explicit incomplete-import state.
5. Evaluate an optional external graph backend only after confirming its actual runtime/API availability and deployment constraints. Keep adapters isolated; native graphs and baked bitmap fallbacks remain supported.

**Acceptance:** curated available fixtures produce a report tied to exact feature coverage and reference images. No unsupported operation is silently dropped. Source `.spp/.spsm/.spmsk` files remain unchanged. Native assets are editable without Adobe; exact graph reproduction is claimed only for validated execution paths.

### T21 Add automatic UV preparation and physical scale

**Dependencies:** T02, T05, T13; coordinate multi-tile packing with T14. This package's number is an identifier, not a requirement to run after T20.  
**Entry points:** `mesh.py` loaders/finalization, new-project/reimport UI, projection scale and mesh export.

Add an optional automatic unwrap path for meshes with missing UVs, using a verified available geometry backend. Preserve valid UVs unless regeneration is explicitly selected. Expose seam/unwrap/packing choices supported by that backend, padding and resolution-aware packing. Show mixed UV availability rather than silently dropping unwrapped-free submeshes. Preserve source physical units separately from normalized render coordinates and expose material scale in documented units. Export generated UVs with the mesh.

**Acceptance:** a mesh without UVs and a mixed-validity multi-material mesh retain all expected geometry and receive usable layouts. The preserve-existing option leaves valid UVs unchanged. Degenerate/nonmanifold input produces actionable errors. Auto-unwrapped reimport uses the T13 transaction/reprojection policy. A material with a known physical repeat size has consistent scale on differently sized assets. Do not advertise multi-tile packing until its tile behavior is validated.

## M4 Broader Painter workflows

### T17 Add persistent paths, text and warp tools

**Dependencies:** T03–T08, T12; UV/tile-aware behaviors use T14.  
**Entry points:** current `paint_path` helper, layer/effect schema, projection model and tools/commands.

Implement editable surface-path objects with control points, width/pressure profiles, material/resource references and deterministic evaluation. Add paint-along-path first, then ribbons and filled regions. Add font-backed text resources with editable text/typography and portable resource records. Extend the shared projection manipulator to warp/decal placement, keeping underlying material parameters editable.

**Acceptance:** change a path point or label text after reopening and regenerate output at another resolution. Paths survive the supported mesh-reimport cases; unsupported cases are reported. Ribbon UVs and projection transforms remain stable under camera movement. The existing one-shot path helper remains usable.

### T18 Extend channel and shader workflows

**Dependencies:** T04, T10–T12; T14 for tiled assets.  
**Entry points:** channel descriptors/storage, renderer/shaders, material UI, compositor, exporter and project schema.

Implement genuinely user-defined channels through allocation, painting, effects, persistence and packing. Add shader-selected material semantics for independently authored specular/glossiness and target-relevant clearcoat, transmission, scattering or anisotropy. Add height displacement/tessellation where supported, with physical units and matching output conventions. Preview controls and export templates must derive from the same semantics.

**Acceptance:** a user channel can be painted and packed to an arbitrary output component; it survives reopen/replay. Each added shading model has a reference asset and target-renderer validation. Creating extra channel names without evaluation or preview support does not complete the task.

### T19 Add delivery integrations and optional specialist tools

**Dependencies:** T01, T02, T11, T18; others depend on integration scope.  
**Entry points:** exporter, mesh exporter, engine API, command/UI extension points and packaging.

Add material manifests and target-application setup scripts for the chosen Unreal/Unity/Blender workflows, with explicit normal and color interpretation. Implement genuine mesh/material interchange separately from texture presets; a glTF-named map template is not glTF export. Publish a documented extension API and CLI batch entry points using the same engine operations.

Treat particle brushes and offline rendering as independent optional subpackages with their own fixtures and requirements. An offline backend can provide the rendering workflow without using Iray specifically. Neither is a prerequisite for a reliable conventional texture painter.

**Acceptance:** a reference asset exported from Strata reconstructs the intended material in each claimed target application without hand-correcting channel packing. Optional backends fail gracefully when unavailable. Do not advertise integrations tested only by checking output filenames.

## T20 Continuous validation documentation and release gates

**Dependencies:** starts with T00 and continues through every milestone.

Split verification into CPU contracts, offscreen GPU behavior, interactive input/UI behavior and representative asset qualification. Add PR CI for portable CPU checks and a supported offscreen GL lane. Use a documented hardware/manual lane for features that require tablets or a physical GPU. Keep release packaging separate from evidence that the product actually works.

Maintain these proposed artifacts as execution proceeds:

- `docs/IMPLEMENTATION_STATUS.md`: package owner, status, dependencies, linked change, actual checks and remaining limits.
- `docs/FEATURE_PARITY.md`: engine/UI/save/export/reference coverage by feature, using evidence rather than a single overall percentage.
- `docs/architecture/`: schema and subsystem decisions for identity, resources, evaluation, color, strokes and tiles.
- `tests/fixtures/`: small generated/native fixtures, expected manifests and reference provenance.

Statuses are `not_started`, `in_progress`, `blocked`, `implemented_unverified`, and `verified`. Record the specific reason for `blocked`; do not use it merely because work is substantial. Each package above initially has status `not_started`.

### Existing test entry points

Run only the checks relevant to the change, then the milestone integration checks. These commands use the Python environment established by T00; `python` is a placeholder for that verified executable. GPU tests need an appropriate context; UI tests open a real window on Windows.

```powershell
python tests/feature_check.py .artifacts/feature --res 512
python tests/headless_check.py .artifacts/headless
python tests/ui_logic_check.py
python tests/ui_smoke.py .artifacts/ui
python tests/unsaved_ui_check.py
python tests/substance_check.py <available-fixture-directory>
```

Inspect individual scripts' argument handling before use. Supply a real fixture directory instead of the placeholder. On Linux, use a supported headless/window-server arrangement as required. New CPU contract checks should not import the full GPU engine unnecessarily.

### Required verification cases

| Area | Minimum evidence |
|---|---|
| Export | Two sets with different pixels; sanitization collision; exact preview/manifest agreement; packing, normal convention, depth and padding checks. |
| Persistence | Old-version migration, different per-set settings, moved dependencies, corrupted input, interrupted save and recovery. |
| Undo and references | Continuous edit grouping, canceled edits, anchor rename/delete, instances across resolutions and history eviction. |
| Painting | Seams, mirrored UVs, alpha placement, screen/object/UV size, symmetry, stencil, real/synthetic pressure, 2D/split input and mask effects. |
| Resolution/reimport | Direct-versus-replayed high-resolution output; old raster fallback; UV-only revision; changed bounds; missing material; cancel/failure rollback. |
| Rendering | Color versus data treatment, managed/legacy modes, HDR behavior, target tangent basis and opacity semantics. |
| UDIM | Cross-tile stroke, tile-specific sources, save/replay/reimport, unique exports and cache eviction. |
| Compatibility | Source file unchanged; supported features retained; approximation report; missing resources; incomplete replay visibly flagged. |
| Performance | Fixed fixture/hardware, warm/cold runs, p50/p95 latency, peak estimated/measured memory, resource release and OOM/cancel behavior. |

Use semantic comparisons and documented tolerances for GPU output. Exact file bytes are appropriate for manifests and deterministic serialization, but not a universal cross-driver image criterion. For each image test define channel space, mask, metric and tolerance before accepting a changed reference. Never regenerate golden images just to make a failing implementation pass.

### Milestone integration scene

Carry one small two-material prop through import → bake → bitmap fill → masked wear → anchor → 3D paint → UV correction → native asset save → project reopen → texture export → target-application check. Extend this scene with reimport and UDIMs only when their milestones arrive. This proves that subsystems work together; a collection of isolated engine calls does not.

## Coordination and handoff between AI agents

This plan permits future task assignment but does not require simultaneous agents. If parallel agents are used, assign distinct work packages and file ownership. Most early packages touch `engine.py`, `app.py` or serialization; do not have several agents edit those sections without an agreed integration owner.

Useful parallel lanes after the relevant contracts are merged:

- Export work versus fixture generation.
- Material/effect UI versus tablet adapter, with a shared transaction interface.
- Memory profiling versus color/tangent validation.
- Compatibility fixtures versus native content development.

Keep project schema, paint journal, reimport and UDIM contract changes sequential until their interfaces stabilize. A dependent agent must integrate and validate the actual prerequisite change, not an assumed future API.

### Copyable work assignment

```text
Implement work package <ID> from docs/STRATA_PAINTER_IMPLEMENTATION_PLAN.md.
Read the capability review, engine API and applicable repository instructions.
Reinspect the current source and dependency status before editing.

Scope: <specific package or independently verifiable slice>.
Owned files or subsystem: <agreed ownership>.
Prerequisite changes available: <commits or current verified state>.
Required acceptance cases: <criteria copied from the package>.

Preserve existing projects and unrelated changes. Reuse the engine and command
registry. Include UI, persistence, undo and export behavior where the package
requires them. Verify the actual behavior with targeted tests and the running
UI when relevant. Do not claim unsupported fidelity or unexecuted checks.

Finish with the handoff format below and update implementation status.
Do not implement dependent packages or publish a release as part of this task.
```

### Required handoff format

```text
Package and scope:
Result and observable artist behavior:
Changed files and API/schema changes:
Prerequisites consumed:
Acceptance criteria satisfied and evidence paths:
Checks run with actual results and environment:
Checks not run and why:
Migration/backward compatibility behavior:
Known limits and reproducible remaining failures:
Next package unblocked and exact integration instructions:
```

## First assignment

Start with **T00**, then **T01**. The first concrete product change should eliminate multi-texture-set export collisions and give the artist an accurate output preview. Follow with **T02** and **T03** before expanding the UI or adding new data types. This establishes a trustworthy foundation for the remaining Painter-style workflows.
