# StrataPainter texture production capabilities and Substance Painter comparison

Review date: October 25, 2026  
Project baseline: local source at Git commit `cefb609`  
Adobe baseline: Substance 3D Painter 12.2.0, released October 21, 2026

## Executive assessment

StrataPainter already implements a substantial texture authoring engine: mesh import, material-based texture sets, mesh-map baking, high-to-low projection, seven PBR channels, layered materials, procedural masks, 3D painting, reusable assets, project persistence, and configurable texture export. It is more capable than the README's older limitations suggest.

Its strongest current application is authoring conventional metallic–roughness textures on UV-unwrapped props, especially painted metal, rust, dirt, rubber, and ceramic. Its Python engine also makes it useful as an extensible texture-processing foundation.

However, it is not yet a dependable replacement for Substance 3D Painter across a production pipeline. The largest immediate issue is the gap between the engine and the desktop interface. Many implemented capabilities cannot be fully authored or configured in the UI. There is also a confirmed filename collision in the UI export path for multiple texture sets. Beyond those issues, the largest missing systems are asset reimport with stroke reprojection, resolution-independent native paint, UDIMs, managed color, advanced bake correction, and genuine Substance graph evaluation.

The recommended direction is to make the existing single-tile prop workflow complete and reliable before pursuing broad Painter feature parity.

## Scope and evidence

This is a source-level capability assessment, with targeted CPU verification. The review covers the application's 32 Python source files, the engine API document, the test suite's coverage, and build configuration. Source links below identify implementation locations. Adobe comparisons use official documentation checked on the review date; the [Adobe release notes](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/release-notes/all-changes) establish the version baseline.

Status terms used throughout:

| Status | Meaning |
|---|---|
| Implemented | A substantive implementation exists; this does not certify runtime quality. |
| Engine only or limited UI | The engine can perform the operation, but the desktop interface exposes little or none of its configuration. |
| Approximate | A substitute produces similar intent without reproducing the original system. |
| Missing | No corresponding production workflow was found in the reviewed source. |
| Needs validation | Source establishes a risk or capability, but representative runtime testing remains necessary. |

The full GPU and interactive test suites were not executed. The repository's virtual-environment Python could not launch, and the bundled analysis runtime lacks ModernGL. All 32 application Python files parsed successfully. A targeted CPU check verified the export filename collision described below without writing textures. No visual-equivalence, speed, tablet, or large-asset benchmark is claimed.

## 1 The production workflow Strata supports

The implemented workflow is:

**Prepare UVs externally → import mesh → create texture sets from materials → bake mesh maps → build fill and paint layers → add masks and wear → paint and inspect in 3D → save a Strata project → export texture maps → assemble and validate materials in the target application.**

Some stages currently require Python calls rather than the desktop interface.

### Mesh intake and project setup

- Native OBJ import reads geometry, UVs, normals, object or group parts, and material assignments.
- Optional Assimp-based import dispatches FBX, glTF, GLB, DAE, PLY, STL and additional formats. Extension recognition is not a guarantee that the installed Assimp build supports every listed format, particularly USD.
- Imported material assignments become separate texture sets, each with its own layer stack and resolution. Mesh parts remain available for geometry masking and selection.
- Built-in meshes support experimentation, including a two-texture-set example.
- Low-poly meshes need existing UVs. OBJ import rejects a completely unwrapped-free mesh; Assimp import skips submeshes without UVs, which can also omit parts of a mixed asset.
- The engine supports per-set resolution changes by resampling stored paint and masks. The UI offers initial resolutions of 512, 1024, 2048 and 4096, but its Texture Set Settings panel currently only displays the resolution.

Evidence: [mesh loading](../strata/mesh.py#L477), [project and texture-set creation](../strata/engine.py#L140), [resolution changes](../strata/engine.py#L239), [texture-set UI](../strata/app.py#L2203).

### Mesh-map baking and high-to-low transfer

Strata generates position, world-space normal, curvature, ambient occlusion, thickness, ID, UV coverage, tangent and mesh-part data. IDs can derive from vertex color, mesh part or material. AO and thickness use sampled depth-map directions; they are custom implementations rather than Adobe's bakers.

The high-to-low implementation is real: it builds a triangle grid for high-poly sources, traces projection rays on the GPU, and produces tangent-space normals and height. It can transfer high-poly vertex colors to ID, use high-poly geometry for AO and thickness, and add normal-map detail to curvature. Settings include frontal and rear ray distances, backface rejection, dilation and AO controls. High-poly sources do not require UVs.

The desktop bake dialog exposes basic AO, thickness, ID and dilation controls, but no high-poly source picker or full high-to-low configuration. This capability therefore belongs primarily to the engine API today. There is no custom cage input, painted cage or skew correction, mesh-name pairing, or dedicated cage-intersection preview comparable to Painter's bake workflow.

Evidence: [bake settings and map definitions](../strata/baker.py#L25), [high-poly ray projection](../strata/baker.py#L159), [high-poly engine entry point](../strata/engine.py#L218), [bake dialog](../strata/app.py#L3520).

### Material channels and surface construction

The data model supports **base color, roughness, metallic, height, normal, emissive and opacity**. Layers and brushes have channel enables; layers also have channel-specific blending and opacity. Height contributes to a final tangent-space normal combined with painted or imported normal information and the high-poly bake.

Fill layers accept constant values, bitmap maps, procedural variation and height noise. Mapping modes include UV, tri-planar, planar, spherical and cylindrical projection. Fill maps can also reference baked mesh maps. The built-in library contains 15 basic material presets and six smart-material recipes.

The UI is narrower: its fill and brush material editors primarily expose color, roughness, metallic and height. Seven channel toggles exist, but there are no equivalent value editors for every channel, general fill-map slots, or projection settings. A material preset is also a collection of fixed values and noise settings; it is not a full Substance procedural material.

Evidence: [channels and layer model](../strata/layers.py#L16), [fill compositing](../strata/compositor.py#L182), [normal combination](../strata/compositor.py#L151), [material recipes](../strata/presets.py), [material UI](../strata/app.py#L2683).

### Layers and nondestructive masking

The engine provides paint layers, fill layers, nested folders, visibility, duplication, ordering, grouping, masks, geometry restrictions and cross-texture-set layer instances. Its 32 blend-mode entries include normal-map operations, and per-channel settings allow channels to behave differently within one layer.

Mask construction includes a paintable base mask, procedural generators and ordered effects. There are 13 active generator types plus None: edge wear, dirt or cavity, AO, upward-facing dust, height gradient, noise, thickness, position gradient, directional light, curvature cavities, world-normal axis, ridged grunge and cellular spots.

Mask effects include fill, generator, levels, invert, blur, color selection, anchor references, mesh-map input and threshold. Content effects include HSL, levels, invert, blur, brightness or contrast, and anchor creation. These make reusable procedural wear and linked masks possible.

The UI supports everyday layer operations and a basic painted-mask plus generator editor. It does not expose a general effect-stack editor, anchor authoring, full per-channel blend or opacity editing, or cross-set instancing controls. Imported stacks may therefore render with structure that cannot be fully edited through the UI. A separate paint effect placed at an arbitrary position inside a mask effect stack is also missing; the existing base painted mask is not equivalent to that workflow.

Evidence: [layer and effect definitions](../strata/layers.py#L92), [layer operations](../strata/engine.py#L465), [mask effect evaluation](../strata/compositor.py#L336), [basic mask properties](../strata/app.py#L2743).

### Painting and local corrections

The engine supports projection-based 3D painting with visibility checks, backface control and painting across UV seams. Tools include paint, erase, smudge, clone and image projection. Polygon fill can target triangles, connected polygons, UV islands, mesh parts or a texture set; the engine also has rectangle and lasso selection helpers.

Brush functionality includes size, hardness, flow, spacing, stroke opacity, grain, angle, directional following, jitter, image or built-in alphas, several alignments, screen/object/UV size spaces, lazy mouse, and mirror or radial symmetry. Stencils and projection images support placement transforms. Quick masks restrict painting, and a material picker samples the composited surface.

Several of these are not exposed as complete artist tools. The UI includes basic brush settings, symmetry, stencils, clone, smudge, projection, polygon fill and straight-line strokes. Alpha selection, jitter, alignment, pressure configuration and several advanced settings lack corresponding editors. Image projection UI currently loads the color image, while the engine supports a channel-map dictionary.

The engine accepts pressure values for size and flow, but the UI calls `begin_stroke` and `stroke_to` without supplying tablet pressure. Consequently, pressure response in the engine should not be advertised as working tablet support in the desktop app.

There is a smooth-curve `paint_path` API that rasterizes a stroke, but no persistent editable path object or path-editing UI. “Follow path” in brush settings means orienting brush dabs to stroke direction; it is not an editable path tool.

Evidence: [brush model](../strata/layers.py#L279), [stroke implementation](../strata/painter.py#L366), [path helper](../strata/engine.py#L897), [brush UI](../strata/app.py#L2592), [UI stroke input](../strata/app.py#L3282).

### Inspection and look development

The renderer provides a GGX-style metallic–roughness preview, a procedural studio environment, external HDR or EXR environments, exposure and environment rotation, AO, emissive intensity and alpha testing. Display modes cover material channels and diagnostic mesh maps. Cameras support perspective, orthographic views and axis snapping.

The application offers 3D, 2D and split layouts. Its active 2D UV view supports inspection, pan and zoom, but does not accept paint strokes. It also exposes fewer channel visualizations than the main renderer. External environment loading exists in the renderer API without a corresponding load control in the current display panel.

Height changes shading through generated normals; it does not displace the viewport geometry. The preview uses fixed color conversions and an ACES-like tone-mapping formula, not an OCIO or ACES-managed pipeline. An ACES-style curve alone does not establish ACES color correctness.

Evidence: [renderer and environment loading](../strata/renderer.py#L95), [active UV view](../strata/ui/uvview.py#L1), [viewport shader](../strata/shaders.py), [display controls](../strata/app.py#L2782).

### Persistence and reusable assets

Native `.strata` projects store mesh arrays, texture sets, layer trees, paint and mask pixels, brush settings, camera settings and an environment path. Shared layer instances have serialization support. Older version-one projects have a migration path. Undo and redo use GPU snapshots and keep up to 24 history entries; the UI also has history and unsaved-change prompts.

The library module can save and load native smart materials, smart masks, brush presets and export templates, and import image resources. Native formats include `.ssmat`, `.ssmask` and `.sbrush`. Much of this library API is not connected to the current Assets panel, which mainly exposes built-in assets and imported Adobe content.

Projects are not fully packaged assets: bitmap, environment and high-poly references can remain external paths. Bakes are regenerated on load rather than stored as a complete native bake cache. There is no evident autosave, backup rotation, dependency collection, missing-resource relinking or crash-recovery workflow.

Evidence: [project save and load](../strata/engine.py#L1056), [history limit](../strata/engine.py#L29), [native asset library](../strata/library.py), [resource loading](../strata/resources.py#L103).

### Texture delivery

The engine exporter is substantially broader than the desktop dialog. It supports custom JSON templates, RGB/A packing, naming tokens, selected texture sets, per-map format and bit-depth overrides, padding variants, output resizing and an optional material-description JSON. Stock templates target Unreal, Unity URP/HDRP, Blender, glTF-style maps, Sketchfab, Arnold and specular–glossiness delivery.

Supported output encodings include PNG 8/16-bit, TGA, TIFF 8/16/32-bit float, JPEG, BMP, WebP, EXR half/full float, HDR and PFM, with depth choices varying by format. OpenGL and DirectX normal outputs are available. Specular and diffuse outputs are derived from metallic–roughness data; this is not independent specular-workflow authoring.

Two distinctions matter:

1. The glTF, Blender and Arnold template names describe texture-map conventions. They do not create a complete glTF asset, Blender material graph or Arnold scene. Mesh export is a separate OBJ writer.
2. Exporting a larger size resizes the existing composited pixels. It does not re-evaluate the entire authoring history at that higher size. An 8K image export therefore does not guarantee 8K authored detail.

The UI only offers three legacy presets with fixed PNG-oriented output and no general template editor, format/depth controls, texture-set selection or output-resolution controls. Those legacy names lack a texture-set token, creating the multi-set overwrite problem described next.

Evidence: [template definitions](../strata/exporter.py#L43), [image formats](../strata/imageio.py#L25), [resizing](../strata/exporter.py#L200), [template export](../strata/exporter.py#L349), [desktop export dialog](../strata/app.py#L3759).

## 2 Highest impact issues in the existing workflow

### Multiple texture sets can overwrite each other during UI export

The UI calls the legacy `export()` wrapper. It exports all texture sets using names such as `T_$project_BC`, without `$textureSet`. For an asset with Metal and Rubber sets, both write `T_Asset_BC.png`, and the later write replaces the earlier one. The preview also lists one generic group of maps rather than each set's outputs.

A CPU filename-expansion check produced **four unique names for eight intended files** using the legacy Unreal preset. The modern Unreal template produced **ten unique names for ten files** because it includes the texture-set name. The same structural collision exists in the other two legacy presets.

**Recommended fix:** connect the UI to `export_textures()` using texture-set-aware defaults; resolve the entire output manifest before exporting; reject duplicate paths; preview every set and map. This should precede treating multi-material assets as a supported delivery workflow.

### Native paint cannot follow mesh or UV revisions

Native projects store paint pixels, not a persistent record of native brush operations. The temporary `Stroke` object handles the current stroke and undo snapshot; it is not serialized as a replayable authoring history. There is no existing-project mesh replacement workflow that reprojects prior painting onto changed geometry or UVs.

**Production consequence:** a UV revision after detailing can invalidate painted content. Resampling to a larger resolution also cannot recreate lost fine detail. Imported Painter stroke replay solves initial conversion, not subsequent native mesh revision.

**Recommended fix:** design persistent stroke records and mesh replacement together, including brush resources, pressure, camera/surface coordinates, random seeds and reprojection policy. Validate with a UV-only revision before attempting major topology changes.

### Resource portability and bake restoration need hardening

The native archive embeds paint pixels but not every referenced source image or high-poly mesh. Loading creates fresh bakes, and a missing high-poly path is logged and skipped. Additionally, `load()` uses the first saved texture set's bake settings when creating all sets; it does not visibly restore each remaining set's distinct bake settings afterward.

**Production consequence:** reopening or moving a project can change generator inputs or normal detail even when layer data survives. The per-set settings issue is a source-level finding that needs a focused runtime regression test.

**Recommended fix:** package or explicitly track dependencies, restore each set's bake settings independently, retain a bake cache, and show actionable missing-resource errors. Save via a temporary file and replace the destination atomically; the current save writes the destination archive directly.

### Paint memory grows rapidly with resolution and history

Every paint layer allocates all seven channel textures. Their component counts total 20; at the default half-float storage, one 4096² paint layer uses about **640 MiB** just for its channel pixels. A stroke also snapshots all seven textures. Twenty-four full layer snapshots could therefore account for roughly **15 GiB**, before live layers, stroke buffers, masks, bakes, compositors or driver overhead.

These are allocation estimates from the code, not measured GPU usage. They show why nominal 4K support and an existing performance test are insufficient evidence of production scalability.

**Recommended fix:** allocate only needed channels, store undo changes by affected regions or tiles, add a memory budget, and benchmark realistic stacks and texture-set counts. Evidence: [paint allocation](../strata/engine.py#L335), [stroke snapshots](../strata/painter.py#L370), [GPU texture defaults](../strata/gpu.py#L60).

## 3 Comparison with Adobe Substance 3D Painter

The table distinguishes similar workflow concepts from equivalent implementations. Adobe references are linked in the final column.

| Pipeline area | StrataPainter today | What Painter provides beyond it | Reference |
|---|---|---|---|
| Material-based texture sets | Implemented; delivery through the UI has a filename collision | Integrated per-set setup and output workflows | [Project creation](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/getting-started/project-creation) |
| UV preparation | Existing UVs required | Automatic UV unwrapping | [Project creation](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/getting-started/project-creation) |
| UDIM authoring | Missing; multiple materials are not UDIM support | Several tiles within a material and painting across those tiles | [Project creation](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/getting-started/project-creation) |
| High-to-low baking | Implemented in engine; limited UI | Dedicated bake workspace, cage workflows and diagnostics | [Baking guide](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/baking/how-to-bake-mesh-maps) |
| Local bake correction | No painted cage or skew workflow | Painter 12.2 adds cage painting; earlier 12.1 adds skew painting | [Release notes](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/release-notes/all-changes) |
| Channel authoring | Seven fixed channels; incomplete value controls in UI | Broader shader-related channels, user channels and channel precision controls | [Texture Set settings](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/texture-set/texture-set-settings) |
| Layers and masks | Strong engine primitives; basic UI | General effect-stack and anchor editing integrated into authoring | [Layer-stack API](https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/substancepainter-package/layerstack-module/edition) |
| Brush engine | Many familiar controls implemented; several lack UI | Broad parameter access and tablet-pressure integration | [Paint brush](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/paint-tools/paint-brush) |
| 2D painting | Inspection only | Painting workflows in 2D as well as 3D, with tool-specific limitations | [Symmetry documentation](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/symmetry/symmetry) |
| Paths and repeated detail | One-shot engine curve helper | Editable surface paths, filled paths and ribbon paths | [Path tools](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/path-tools/path) |
| Projection placement | Screen-space stencil/projection gestures; engine fill projections | On-screen manipulation and warp-to-geometry workflows | [Shortcuts](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/settings/shortcuts), [release notes](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/release-notes/all-changes) |
| Text and labels | Bitmap preparation outside the app | Font-based text resources with editable content and typography | [Text resource](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/text-resource) |
| Simulated effects | Noise and map-driven wear | Particle brushes and particle animation | [Shortcuts](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/settings/shortcuts) |
| Resolution changes | Native paint is resampled; larger export resizes the composite | Recalculation from authoring data for higher-resolution output | [Adobe workflow explanation](https://www.adobe.com/products/substance3d/magazine/go-scan-the-world-photogrammetry-with-a-smartphone.html) |
| Mesh revision | No native reimport/reprojection workflow | Mesh reimport with stored-stroke reprojection, subject to geometry changes | [Adobe product-manager explanation](https://community.adobe.com/questions-59/maintaining-brush-strokes-when-geometry-position-has-changed-628618) |
| Managed color | Fixed conversions and tone mapping | OCIO-managed working, display and export color handling | [Color management](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/color-management/color-management) |
| Advanced look development | Fixed metallic–roughness shader, height-to-normal, alpha test | Configurable shaders, displacement settings and Iray rendering | [Shader settings](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/shader-settings/shader-settings) |
| Texture export | Flexible engine templates; narrow UI | Integrated output-template authoring and broader channel sources | [Output templates](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/getting-started/export/export-window/output-templates) |
| Pipeline integration | UI-free Python engine; custom scripts possible | Documented application Python API and plugin workflows | [Python API](https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/substance-3d-painter-python) |

## 4 Substance file compatibility is useful but not equivalent rendering

Strata can read `.spp` projects, `.spsm` smart materials and `.spmsk` smart masks. It discovers installed Painter assets and shelf folders, displays thumbnails, converts layer trees and reports approximations. This is a meaningful migration feature.

### What conversion attempts to preserve

The import path reconstructs mesh parts, texture sets, folders, channel settings, supported blend operations, constant fills, embedded bitmap content, masks, supported effects and anchors. Recorded paint operations are replayed through Strata's brush engine, including imported 2D strokes through a special UV-aligned path. That importer capability does not make interactive 2D painting available in the application.

### What is approximated or omitted

- Compiled Substance graphs are not executed. Recognized generator and material names are translated into Strata generators, mesh-map combinations, constant values and noise.
- Procedural materials may lose their original pattern, parameter behavior and relationships among channels. A plausible rust approximation is not the original rust graph.
- Imported strokes do not reproduce original brush alphas, jitter or symmetry. They use round dabs with selected recorded brush parameters.
- Unsupported operations include smudge replay, decals, some filters such as warp or sharpen, and channels outside the seven-channel model.
- Replay is budgeted: the code defines 40,000 dabs per layer and a 150,000-dab replay limit, with truncation reporting. Large painted assets can therefore be incomplete; the effective total depends on how replay is invoked.
- Painter files are read only. There is no `.spp`, `.spsm` or `.spmsk` authoring or export round trip.

**Practical consequence:** use conversion to recover editable structure and supported bitmap content, then visually compare the result. For appearance-critical migration, export reference textures from Painter and use them to validate or replace approximated content. Do not promise that an arbitrary Painter project will open with the same appearance.

Evidence: [file-level importer](../strata/substance/importer.py), [conversion rules](../strata/substance/convert.py), [stroke replay and limits](../strata/substance/replay.py#L1), [application of converted stacks](../strata/substance/apply.py).

## 5 What StrataPainter is most notably lacking

### Complete artist access to the engine

This is the highest-return area because the underlying functionality often exists already. The application needs an editable effect stack, anchor creation and references, bitmap slots and projection controls, alpha selection, advanced brush settings, complete channel value editors, high-poly bake setup, environment loading, resolution changes, native library management and the modern exporter.

Without those controls, a source-level checklist substantially overstates what a texture artist can do without scripting. The engine API document should not be treated as a user manual for the shipped UI.

### A durable revision and recovery workflow

Persistent native stroke history, geometry/UV reimport, portable dependencies, reliable per-set bake restoration, atomic saves and recovery are more consequential than extra material presets. They determine whether detailed work survives upstream changes, moving machines and interrupted sessions.

### Scalable texture architecture

UDIMs are missing, and the allocation strategy needs work even for several 4K single-tile texture sets. A tile-aware architecture could support both UDIM addressing and localized evaluation/undo, but this is a substantial design change, not a texture-set rename.

### Color and shading agreement with target applications

There is no OCIO configuration, explicit input/working/display/output transform workflow, or user-selectable shader system. Tangents are computed by a custom routine; matching MikkTSpace behavior is not established. DirectX/OpenGL normal conversion flips conventions, but does not by itself solve tangent-basis mismatches.

Advanced materials need more than exported map names. Clearcoat, transmission, scattering, anisotropy and independently authored specular data require corresponding channels and preview behavior. These should be added according to the intended target market rather than as unused toggles.

### Advanced mask and detail authoring

Separate paint effects inside mask stacks, richer filters and procedural content, editable paths/ribbons, text resources, full 2D paint, manipulators and warp workflows would reduce dependence on external applications. Particle simulation is also absent, but it is a lower priority for a conventional prop-texturing MVP.

## 6 Recommended development order

The priorities below are recommendations based on the reviewed implementation, not estimates of engineering effort.

| Priority | Work package | Completion criterion |
|---|---|---|
| P0 | Fix multi-set texture export | Two sets export to distinct paths; the preview matches the actual manifest; duplicate outputs are rejected. |
| P0 | Harden save, load and dependencies | Reopen a multi-set project with different bake settings and verify stable maps; moved/missing dependencies are explicitly handled; interrupted save preserves the previous file. |
| P1 | Connect existing material and effect features to UI | An artist imports a bitmap material, sets projection, stacks mask effects, creates an anchor and edits all seven channel values without Python. |
| P1 | Finish brush and bake UI | Alpha/jitter controls and high-poly source setup work through the desktop UI; real tablet events drive pressure. |
| P1 | Reduce paint and undo memory | Representative 4K multi-set assets stay within a defined GPU-memory budget; repeated painting and undo remain usable. |
| P1 | Establish color and normal validation | Reference swatches and normal-bake test assets agree with named target renderers under documented settings. Add OCIO where the target workflow requires it. |
| P2 | Persistent strokes and mesh reimport | A UV-only mesh revision preserves the intended painting, and resolution increases regenerate supported detail rather than merely scaling pixels. |
| P2 | Native library and full 2D painting | Artists can create/reuse native assets and paint corrections in UV view without scripts. |
| P2 | Better bake correction | Add mesh-name pairing, cage support, diagnostic visualization and local correction as justified by bake failures. |
| P2 or P1 for VFX | UDIMs and tile-aware evaluation | One material spans several tiles with correct cross-tile painting, masks, saving and uniquely named exports. |
| P3 | Specialized authoring and presentation | Editable paths, ribbons, text, warp, additional shaders and offline rendering serve validated user needs. |

For a game-prop-focused first release, defer UDIMs and offline rendering until the P0/P1 workflow is reliable. For film characters or assets that already arrive with UDIMs, tile support becomes an early prerequisite. For Painter-library migration as the central product promise, procedural compatibility and import fidelity testing need a much higher priority.

## 7 Suitability by production task

| Task | Assessment |
|---|---|
| Learning PBR layering and map-driven wear | Strong fit for the implemented concepts and small built-in examples. |
| Single-tile props with simple materials | Closest to a viable artist workflow; verify exports and save/reopen behavior on representative assets. |
| Multi-material game assets | Engine supports them, but fix the UI export collision before relying on delivery. |
| Custom automated texture operations | Promising: the engine is separated from the UI and exposes direct Python operations. |
| Appearance-identical Painter project migration | Poor fit as a guarantee; procedural and stroke approximations are fundamental limitations. |
| Asset work with frequent UV or topology changes | Limited until native reimport and stroke reprojection exist. |
| UDIM characters and film assets | Not currently supported as a complete workflow. |
| Color-managed studio look development | Requires additional color/shader infrastructure and validation. |
| Final displaced or path-traced presentation | Export to another application; Strata's viewport does not supply that workflow. |

## 8 Validation and documentation follow through

The repository already contains useful engine, headless, feature, Substance-import and UI checks. In particular, `feature_check.py` exercises texture sets, blending, effects, projections, brushes, high-poly baking, I/O, export and libraries. Test presence establishes intended coverage; it does not establish that those tests currently pass. The reviewed release workflow builds and packages the application, but does not run these functional checks.

The most useful next validation assets are a two-material prop, mirrored-UV normal-map test, thin intersecting high/low bake, 4K layered stress scene, moved-project dependency test, UV-revised mesh, and several Painter projects with procedural fills and complex paint. Compare actual maps, reopen behavior and target-renderer results, rather than only checking whether an API returns successfully.

Update the README alongside implementation work. Its final Known limits section still says there is one texture set and no folders, alphas, stencils or symmetry; the source now implements those systems to varying degrees. Conversely, the engine API's broad feature list needs a clear UI-availability column. Maintaining separate engine and artist-facing capability lists would make the product's current scope much easier to assess.

Evidence: [feature checks](../tests/feature_check.py), [headless checks](../tests/headless_check.py), [UI logic checks](../tests/ui_logic_check.py), [Substance conversion checks](../tests/substance_check.py), [README](../README.md), [engine API](ENGINE_API.md).

## Source navigation

Local links refer to the reviewed repository. Code line locators are baseline-specific and may move after edits. Adobe links are live documentation and may change after this review.

| Source | Main evidence |
|---|---|
| [engine.py](../strata/engine.py) | Texture sets, layer operations, paint entry points, resolution changes, persistence and history |
| [app.py](../strata/app.py) | Actual desktop controls, command wiring, input paths, bake and export dialogs |
| [layers.py](../strata/layers.py) | Channel schema, blend modes, projections, effects and brush parameters |
| [mesh.py](../strata/mesh.py) | Mesh loaders, material/part handling, normalization and tangent computation |
| [baker.py](../strata/baker.py) and [raycast.py](../strata/raycast.py) | Mesh maps and high-to-low projection |
| [compositor.py](../strata/compositor.py) and [shaders.py](../strata/shaders.py) | Layer/effect evaluation, mask generation, normal combination and shading |
| [painter.py](../strata/painter.py) and [gpu.py](../strata/gpu.py) | Brush execution, symmetry, snapshots and GPU allocation |
| [renderer.py](../strata/renderer.py) and [uvview.py](../strata/ui/uvview.py) | Preview, environment loading, camera and active 2D inspection view |
| [exporter.py](../strata/exporter.py) and [imageio.py](../strata/imageio.py) | Naming, packing, sizing, formats and output behavior |
| [library.py](../strata/library.py), [presets.py](../strata/presets.py) and [resources.py](../strata/resources.py) | Native reusable assets, built-ins and image handling |
| [Substance importer](../strata/substance/importer.py), [converter](../strata/substance/convert.py), [replay](../strata/substance/replay.py) and [apply](../strata/substance/apply.py) | File conversion, approximations, stroke replay and import budgets |

