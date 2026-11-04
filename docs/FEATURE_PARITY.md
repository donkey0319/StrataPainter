# Strata feature evidence ledger

Initial T00 ledger at `cefb609`, October 25, 2026; T01/T02 evidence updated October 26. This separates implementation evidence from user-facing availability. See [baseline commands and failures](BASELINE.md), [current implementation status](IMPLEMENTATION_STATUS.md), [capability review](STRATA_TEXTURE_PIPELINE_REVIEW.md) and [implementation plan](STRATA_PAINTER_IMPLEMENTATION_PLAN.md). Subsequent package owners must update only claims they actually verify.

Painter UX compatibility is tracked separately in [the implementation and remaining-scope guide](PAINTER_UX_IMPLEMENTATION.md): target breadcrumbs, per-channel layer controls, inline effects, atomic forest drops, mask merge/replacement, rotated UV gestures/replay, native projection shortcuts, nonmodal bake controls and visual export authoring with optional v14 saved configuration. These are bounded workflow improvements, not a claim of full 12.2 tool/rendering equivalence.

| Capability | Engine | Desktop UI | Save and export | Current validation |
|---|---|---|---|---|
| Material-based texture sets | Implemented | Set selection and multi-set export controls | Saved; distinct paths or collision rejection | T01 actual two-set pixels/manifest/UI and T02 independent settings verified |
| Seven PBR channels | Shared descriptors across model, painter, compositor and exporter | All seven values, bitmap slots, toggles and channel blend/opacity controls | Stored and exportable with legacy order/defaults preserved | T04/T05 GPU checks and actual controls qualified; legacy reference pixels unchanged |
| Fill maps and projections | Five mapping modes and validated assignments | Seven previewed slots, imported-image picker, numeric mapping controls, viewport translation/rotation/scale | Undo, portable save/reopen and pixel-matched export verified | T05 14 CPU/GPU scenarios and 47 actual UI assertions pass; OS file picker itself not exercised |
| Folders and effects | Ordered content/mask transforms, independent paint, positional mask anchors, bevel ramps and normal-anchor curvature input | Effect editors, source pickers, enable/reorder/copy/delete and blend/opacity controls | Paint arrays require v4; mask captures, bevels and active normal inputs select v15 | T06 coverage plus seven helmet-workflow scenarios and nineteen real UI assertions pass; approximation and seam limits in EFFECTS.md |
| Painted masks and anchors | Base paint plus independent intermediate paint; persistent accumulated-output anchors | Explicit paint targeting, source/channel selection, dependency diagnostics, geometry and ID picking | Undo, copy, native libraries and save/reopen retain pixels/references | T06 six scenarios and 15 actual UI assertions pass; see EFFECTS.md |
| 3D brush, alpha, symmetry | Implemented; deterministic seeds and frozen stroke settings | Advanced alpha/jitter/alignment/pressure/size/symmetry controls, seven projection slots; Windows Ink capture | Portable brush resources/settings and raster paint saved; all seven channels export | T07 7 CPU/GPU scenarios and 35 actual UI assertions pass; physical tablet unverified; known low-flow failure remains |
| Tablet pressure | Accepted by engine API | Windows Ink feeds pressure each frame | Native journal stores pressure/time samples | Physical tablet not tested; no coalesced-event or tilt qualification |
| Clone and smudge | Implemented | Exposed | Raster results stored | T00 tools checks passed |
| 2D painting | Native UV strokes share the engine painter and storage | Paint/erase/masks/projection/clone/smudge, navigation, wireframe and full diagnostics | Existing raster undo/save/export; independent mask paint uses v4 | T08 11 CPU/GPU scenarios and 26 actual UI assertions pass, including split/swapped/scaled input; explicit tool limits in UV_PAINTING.md |
| Mesh-map and high-poly baking | Transactional bake/external-map assignment | High-poly/map controls | Independent settings and portable provenance/cache | T09 eight CPU/GPU scenarios and 21 UI assertions pass; advanced cages/corrections remain T15 |
| Native smart materials/masks/brush library | Portable native assets with profile checks | Search/save/import/apply/drag shelf | Content-addressed dependencies and thumbnails | T09 verified; incompatible raster color modes/image interpretations reject explicitly |
| Project persistence | Version 3; v1/v2 readers, staged load and atomic save | Portable save, resources/relink, autosave/recovery and backups | Content-addressed dependencies, validated bake caches | 13 archive/GPU and 7 controller tests pass; real recovery confirmation and frozen-v2 map equivalence verified |
| Document edits and identity | Persistent IDs, stable anchor references, property/tree/raster/resource undo | Gestures and compound edits share transactions; Escape restores values | IDs and internal copied references retained through save/reopen | T03 27 transaction, 13 identity and 11 actual UI assertions pass; unsafe raster sharing is guarded |
| Texture templates and packing | Shared validated manifest and staged writer | Modern templates, map/set selection, format/depth/size/padding and advanced JSON editor | Correct sparse RGBA packing, unique names, rollback | 21 CPU tests and 10 actual-dialog/output assertions pass |
| Preview and environment | PBR shader and external environment API | Basic display controls | Environment can be packaged in portable project | T00 headless images and UI smoke; no target-renderer equivalence claim |
| Managed color and tangent equivalence | Explicit fixed OCIO managed/legacy pipelines and external Blender Mikk adapter | New-project choices and image interpretation | Managed v6/v7, linear/HDR/data-aware delivery | T11 eight CPU/GPU scenarios, seven UI assertions and Blender 5.1.2 unlit color/mirrored-normal renders pass; full PBR equivalence excluded |
| Native stroke replay and mesh reimport | Durable native dabs/samples, detached evaluation and bounded surface correspondence | Native resize/export; staged revision comparison, mapping, commit/cancel/recovery | Journal v7; portable pre-reimport checkpoint | T12/T13 verified: 1K-to-4K exact fixture match; ten revision scenarios and eight UI assertions pass; arbitrary topology preservation excluded |
| UV preparation and physical scale | Blender single-/multi-tile unwrap, fixed valid UVs and declared source units | Mixed-input inspection, unwrap choices, physical-repeat control and mesh delivery | Generated UVs, source/meter OBJ, physical repeat v8 and tiled raster v9 | T21 fourteen CPU/runtime scenarios and twelve UI assertions on Blender 5.1.2; bounded angle-seam chart allocation, not arbitrary tiled reimport or uniform density |
| UDIM | Material-owned tiles, bounded stores, surface/UV replay/revision, height-normal gutters, picking/fill and independent duplication | Cached 3D/2D, live strokes, browser/grid, image assignment and tiled revision comparison | Portable v9 and atomic UDIM manifests; independent-mask-only projects remain v4 | T14 plan acceptance verified locally: 53 Engine GPU scenarios and 63 tile UI assertions pass, including combined portable/revision/resize/delivery fixtures. Audited guarded tools, instance/topology limits and unqualified workloads are explicit in architecture/T14_ACCEPTANCE.md |
| Adobe project/material import | Implemented conversion and approximate replay | Substance tab and import reports | Read-only source; native result | Corpus not run in T00; fidelity is feature-specific |
| Editable paths, text and warp | Persistent anchored polylines/ribbons/regions, font text and projective mapping | Point capture/move, typography and shared warp/decal controls | Optional v12 objects/font records; regenerate at requested resolution | 14 CPU/GPU scenarios and 12 desktop assertions; limits in AUTHORED_OBJECTS.md |
| Particle brushes / offline rendering | Not implemented | Pending optional specialist tools | No corresponding execution backend | Unqualified; separate T19 subpackages |

T00 evidence is a baseline, not an overall parity percentage. A package is verified only when its engine, UI, restoration and delivery acceptance cases actually run. Presence of a method, field, shortcut or existing test does not establish completion.


### T18 channel/shader extension

| Capability | Engine and preview | Persistence/export | Qualified scope |
|---|---|---|---|
| User-defined scalar channels | Independent lazy paint, fill, scalar effects/graphs, standard masks and anchors, groups, native replay, UV/surface preview and tiles | Optional v13; portable data images; arbitrary output components and UDIM packing | 16 CPU/GPU scenarios and 16 actual desktop assertions; up to 16 scalar channels, output/global budgets apply |
| Independent specular/glossiness and clearcoat | Shader-selected linear F0 RGB/glossiness and optional coat/roughness bindings; shared diagnostics | Same semantics derive export templates and stale-preview validation | Actual Blender 5.1.2/Cycles texture and BSDF response references; exact BRDF/lighting parity excluded |
| Physical displacement | Declared units, signed meter range/midlevel, existing-vertex displacement and matching picked surface | Signed 32-bit meter EXR | Single-tile existing mesh density; UV editing while previewing displacement; no tessellation or tiled displacement |

See SHADER_WORKFLOWS.md. Custom clone/smudge/projection, custom-output anchors,
transmission, scattering and anisotropy are not claimed. T19 delivery is qualified for the Blender scope documented in DELIVERY.md.


### T19 delivery and optional backend

| Capability | Engine/UI/CLI | Actual evidence and limits |
|---|---|---|
| Blender mesh/material bundle | Versioned manifest, indexed mesh/material identities, float interpreted maps, standalone setup and native File menu | Actual Blender 5.1.2/Cycles multi-material pattern/mirrored-normal reconstruction, specular/gloss/coat, fractional alpha, HDR and physical vertices; single-tile scope |
| GLB interchange | Real glTF 2.0 scene, geometry primitives, embedded textures/materials; MR/coat/HDR extensions | Actual Blender glTF importer plus rendered source comparisons; meter units required; PNG8, matching Mikk basis; unsupported workflows reject |
| Extension/batch API v1 | Explicit versioned Python modules, native command registry/UI menu bridge, JSON CLI jobs | Native paint/portable reopen/delivery, preflight/failed steps and explicit module loading; no project autoloading or whole-job rollback |
| Optional offline Cycles | Isolated factory subprocess, same bundle importer, atomic PNG | Actual 64px render, failure preserves destination; missing runtime actionable; particles separate and unavailable |

See DELIVERY.md/EXTENSIONS.md. Unreal/Unity automatic setup, UDIM mesh/material
bundles and frozen executables are not qualified; texture presets remain available.


### T20 qualification boundaries

Local validation is split into guarded CPU, offscreen GPU, actual UI, carried
assets and performance lanes. The first 45-check run found a 4K default-budget
boundary and a late stroke-allocation ownership defect; compound initial admission
now prevents lazy channels being published before a rejected stroke. Focused
post-fix checks and brush UI pass; low flow remains 101/102 and release-visible.
The current legacy UI-logic run passes. No golden/assertion was weakened.

Managed carried-scene/three-page UDIM workflows pass. Core and custom-scalar
512/2K/4K profiles report completed-work distributions and explicit limits; default
5 GiB 4K scalar stroke rejection is not an interactive-painting qualification.
A 128-file relocated source candidate passes CLI/batch/GUI smoke without shipping
local tests. Frozen packages, physical tablet, other-platform runtimes and remote
CI execution remain unverified; CI stays syntax-only. See VALIDATION.md and
RELEASE_GATES.md. T20's local increment is verified; its external release gates
remain open.
