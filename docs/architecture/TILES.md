# T14 tile contract and current integration boundary

T14 is verified locally for authored/imported multi-tile layouts; see
[T14 acceptance](T14_ACCEPTANCE.md) for plan traceability, evidence and audited limits.
Material-owned storage, batch UV painting, detached evaluation,
native persistence, resize and UDIM delivery have Engine APIs. A Material tiles
browser now provides a UV grid, isolation, diagnostics, image assignment and
paint-on-release paths. The main 3D viewport now streams cached tile materials;
the main 2D view now draws a navigable global UV tile grid from that same cache.
Main 3D and 2D support live tiled paint, erase, masks and projection. Height-derived
normals use streamed neighboring height/coverage and world-position strips.
Advanced tiled tools remain guarded.
Polygon fill and the 3D material picker also address tiled data explicitly.

## Addressing and geometry foundation

strata.tiles.TileAddress is a stable integer (u,v), ordered by UDIM number:
1001 + u + 10v. Supported UDIM coordinates have u in 0–9, nonnegative v, and a
four-digit result at most 9999. Negative coordinates and a would-be eleventh
column are rejected instead of aliasing the next row. This follows the ten-wide
convention in the [Blender manual](https://docs.blender.org/manual/en/2.93/modeling/meshes/uv/workflows/udims.html).

Point ownership is half-open. An exact integer edge selects the tile above/right;
address_at can take available addresses and fall back to the lower neighbor at
an outer boundary. It does not invent negative tiles at UV zero. Callers still
need coverage tests to decide which island was hit.

partition(mesh, materials=None, max_tiles=256) computes positive-area coverage by
clipping UV triangles against unit squares. A boundary-touching face does not
create a zero-area neighboring tile. Faces crossing tiles retain every covered
piece, source face ID and barycentric source-corner weights. Degenerate UV faces
are reported explicitly. The configurable tile limit rejects excessive coverage;
it never truncates faces or creates GPU storage.

Each page retains its original material identities. raster_mesh(source) shifts UV
coordinates by the tile address while keeping original triangle attributes and
world geometry. Rasterizing the original corners lets GL perform edge clipping
without changing smooth-normal interpolation at new CPU-generated vertices.
Clipped barycentrics are retained for correspondence/diagnostics. The source mesh
is not modified. Revision hashes include all surface/bake-relevant vertex arrays;
future evaluation keys must additionally contain set pid, tile and document revision.

## Texture residency foundation

strata.tilestore.TileStore owns pages keyed by (material set pid, TileAddress).
Its explicit resident byte limit works alongside the existing GPU texture budget.
Acquire a lease on the owning GL thread; allocate named owner/channel textures
through that lease. Active pages are pinned. Unleased pages are evicted in LRU
order after every texture is read and compressed successfully.

Eviction preserves exact unorm8, half-float and full-float bytes in CPU backing.
Restoration stages every texture before publishing it; failed uploads free partial
allocations and retain backing data for retry. Active leases cannot be evicted or
closed. Lease objects reject use after expiration. Callers must not retain raw
texture references beyond the lease. The optional forget callback releases painter
framebuffers referencing textures before eviction. CPU backing is document data
and is not covered by the GPU resident byte limit.

snapshot() returns a versioned backing manifest and NPZ arrays without evicting
resident pages or changing their texture objects. from_snapshot() validates
material/tile identities, duplicate records, shapes, precision and payload hashes
without creating GL objects. Restores remain lazy and budgeted through leases.
Native v9 projects include this envelope and an immutable imported-raster base
for replay. Ordinary legacy saves retain their existing version rules; independent
mask paint without a native journal remains v4.

## Material-owned Engine APIs

enable_tiles(ts_index=None, resident_bytes=None) explicitly enables a material's
covered addresses. Engine.sets stays material-based with one editable layer/effect
tree. Legacy pixels migrate only to (0,0); other tiles start unpainted. Detach shared
cross-material instances first. Enabling stages storage before publication.
Canonical higher-resolution legacy raster bases retain their original precision
and resolution in CPU backing; authored pages use the material's current resolution.

paint_tiles_uv(points, mapping) accepts a complete global UV path with optional
pressure per point. One Stroke produces spacing/jitter, then recorded dabs dispatch
to intersected tiles through leases. Boundary painting is one undo action. Paint,
erase, projection, base masks and independent paint-mask effects use canonical
owner pids with tile-scoped pixels. Samples, pressure, views, seed, frozen brush
resources and emitted dabs persist. Clone/smudge, quick mask and symmetry reject.

begin_uv_stroke, stroke_uv_to, end_stroke and cancel_stroke also support tiles.
One global native dab stream preserves spacing, jitter, timestamps, pressure and
each projection view. Bounded transient pages hold per-tile coverage, original
pixels and accumulation buffers, preserving stroke opacity across eviction.
Authored pages are leased only during dispatch. Live raster revisions invalidate
previews; viewport LOD replay includes uncommitted dabs. Release commits one undo;
Escape restores pixels and mask flags. Save and selection/property edits finish
the stroke before proceeding. Failed feeds cancel without committing history.

begin_stroke and stroke_to use the same tile stroke lifetime for native surface
input. World-space dabs dispatch into shifted-UV tile meshes. Conservative world
bounds cull tiles beyond the shader's three-radius limit, including mirror/radial
copies. A brush crosses world-adjacent surfaces even when their UVs occupy distant
tiles. UV input keeps its separate UV-footprint ownership and symmetry guard.

Surface operations retain original camera matrices, viewport dimensions, pressure,
timestamps, seed, frozen resources and emitted dabs. Replay rebuilds each view's
occlusion from the whole source mesh, including other materials; it restores the
current pick pass afterward. Renderer pick-buffer resize stages all replacements
and preserves old targets after partial allocation failure. Offscreen tile work
disables inherited viewport scissors and restores caller clipping afterward.
The same-resolution replay is exact; 64-to-128 replay matches direct 128 authoring
for the surface fixture. This is not larger workload or physical-tablet acceptance.

Bounded changed-geometry reimport projects tiled surface dabs and samples through
T13 correspondence, then regenerates tile rasters from their bases/updated native
operations before commit. UV-only tiled paint retains its unchanged-UV behavior.
Both require unchanged UVs, topology and material assignments. Misses/normal
disagreement reject; cancellation and allocation failure preserve live data.
The comparison preview streams actual tiled materials on both sides. Commit
retains a portable pre-reimport checkpoint. Arbitrary changed UV/topology and
ambiguous surface correspondence remain outside this bounded path.

Referenced image interpretation must be set before native tiled painting; changing
it afterward rejects to preserve replay colors. Native shelf raster imports and
tiled asset saves reject before uploads/publication until tile-aware asset storage
is integrated. Procedural shelf content remains available. Portable projects retain
tile data and resources.

polygon_fill handles selected source triangles across tile boundaries for paint,
erase, base masks and independent paint-mask effects. A complete replacement is
staged before publication and committed as one tile-pixels undo action. Quick masks
remain guarded. A polygon edit stores the entire affected owner's target (layer
paint or mask) as a raster base at current authored resolution, replacing only that
target's native operations. Other owners/targets retain native replay. The desktop
discloses this resolution behavior; later resize resamples the edited target.
Portable reopen retains exact authored bytes. Missing resources/allocation failure
leave pixels, flags and history intact. Recreating a disabled base mask starts from
the same default as the single-tile fill workflow.
Selecting only degenerate/uncovered UV faces is a no-op and retains native replay.
Staging, reset, undo and cancellation retain the current tile residency limit.

pick_material uses the hit material and global UV to select the correct tile,
samples authored-resolution accumulators within a detached evaluation, and applies
the established managed color encoding before updating the brush. It does not
sample viewport LOD or stale legacy textures. Resource errors reach the desktop
status without partially changing the brush.

evaluate_tile(address, ts_index=None, resolution=None) yields detached bakes and
composites in a context manager; textures expire on exit. Evaluation clones shared
definitions with canonical pids and binds tile pixels, without swapping live
Layer.tex pointers. Anchors capture within the tile's compositor. Surface bakes
use the selected material/tile; AO/thickness occluders retain full source geometry.
Detached evaluation rebuilds bakes/composites. Two separate revision-keyed caches
retain display thumbnails and native-precision render outputs, respectively.

set_resolution and detached higher-resolution export replay native dabs at the
requested size. Imported raster bases are resampled explicitly. Resize stages
dependent allocations before publication and clears old-resolution history only
on success. History budgets count compressed pixels and operation metadata.
Failed draws/allocations preserve pixels, layer flags, serial and undo history.

Portable v9 saves retain addresses, pixels, raster bases, operations and frozen
brush resources. CPU validation checks coverage, source/material provenance,
dimensions, compressed payloads and hashes before GL restoration. Restores are
lazy. Saved authored normals retain exact float32 values so repeated normalization
cannot silently change operation source fingerprints on successive reopens.

T13 revision staging supports geometry changes with exactly unchanged UVs,
topology and material assignments. All tiles evaluate before commit. Cancel and
failures preserve the original; commit retains a portable checkpoint and prior
mesh revisions on native UV/surface operations. Surface pixels regenerate from
bounded correspondence; changed UV/topology reprojection rejects.

Export manifests carry tile identity. $udim expands to the four-digit number;
tiled templates without the token append _1001, etc. Legacy non-tiled filenames
and selected-material order remain unchanged. Maps group by material/tile for
streaming. Collisions and stale layouts reject before writes; the entire batch
stages before atomic publication. Material JSON includes all tile-map filenames.

Clear paint and base/effect mask fills reset tile pixels and their imported bases
as one undoable edit. They remove superseded operations for that owner/target;
other owners and masks remain intact. Constant mask defaults persist and replay at
new resolutions. Undo restores prior pixels, bases, operations and layer flags.
Polygon fill and same-material layer/group duplication are supported. Clipboard
forest copying and cross-material instances remain guarded. Metadata edits share
one tree. External mesh-map sequences reject during tile evaluation.

duplicate_layer copies a subtree's tile rasters, canonical bases, mask defaults,
independent mask effects, image sequences and native operations with fresh owner
identities. Compressed bytes retain precision and canonical resolution; immutable
resource files can be shared while painted pixels/settings remain independent.
Internal anchor references remap to copied sources; external references retain
their original identity. Legacy name references bind on detached definitions and
publish with the copy, preventing ambiguity when anchor names are duplicated.

One combined tile_stack history entry restores definitions, selection, compressed
backing/native operations and original anchor bindings together. Its CPU payload
counts toward the history budget; dropping redo releases detached legacy textures
without releasing live source effects. Preparation/allocation failures preserve
the tree, pixels and serial. Replacement rejects outstanding material/cache leases
before closing any store, so a pinned thumbnail remains usable after rejection.

assign_tile_sequence(layer, channel, paths, ts_index=None) assigns an explicit
dictionary of integer UDIM numbers to image paths on a fill layer. Channel enable
state stays in the shared layer definition. None removes an override. Assignment
is one undoable edit and preloads existing images before publication. Missing and
unassigned addresses are returned by sequence_diagnostics(); assigning an address
outside this material rejects. Evaluation of an enabled sequence channel requires
the selected tile's image and a successful decode/upload; it cannot silently fall
back to a constant. Sequences use tile-local image UVs and the layer's projection.
They survive native resize and portable packaging, including source deletion.
Project resource relinking updates sequence paths with one reversible resource
edit. External bake-map sequences remain a separate pending workflow.

## Evidence and remaining work

tests/tiles_check.py: eight CPU contracts plus four offscreen GPU scenarios pass.
CPU checks include 80 deterministic random crossing triangles and area conservation.
The GPU proof uses the existing baker surface pass and native UV painter on both
sides of 1001/1002, with continuous coverage and matching color. AO/thickness are
disabled in this proof: final baking must retain occluders from all tiles.
Cache tests cover eviction, pinned-budget failure, material isolation, all three
texture precisions, partial upload failure/retry and complete tracked-texture cleanup.
Backing save/load retains 1001/1002/1011 and separate-material pixels exactly;
corrupt checksums and duplicate tile identities reject before GPU allocation.
Evidence: .artifacts/tiles-t14-foundation/raster-results.json and t14-tiles-foundation.log.

tests/material_tiles_check.py adds fifty-three native GPU checks: boundary painting,
undo, independent masks, repeated portable reopen, exact resized-vs-direct pixels,
detached evaluation, staged mesh revision/checkpoint recovery, corrupt-load/OOM
preservation, material isolation, tile-local anchors, atomic export, portable image
sequences, missing tiles, relink undo/redo, all-channel erase, projection view
continuity, clear/mask fill history and tracked project texture cleanup.
CPU export planning runs in export_check.py.
Cache checks include exact eviction/restore, metadata invalidation, save without
authored pins, complete tracked texture cleanup, managed color/data previews and
rejection of invalid operation viewport dimensions before mutation.

## Tile browser and preview cache

Open Material tiles from Texture Set Settings or the Viewport command/palette.
Enabling a material is explicit; save a copy to retain its single-tile version.
The browser has a tile selector, isolation, fit, wheel zoom and middle-drag pan.
The grid uses global UV coordinates; image samples use tile-local coordinates.
Fill layers expose per-channel/per-tile image paths, missing-tile diagnostics and
removal of the channel sequence override.

Dragging the canvas shows a path and paints it on release as one undo action.
Brush settings/resources freeze at path start; pressure is sampled per UI frame.
Escape or closing/collapsing cancels pending input. Changing material/layer/mask
target cancels rather than painting a different owner. This is a batch path tool,
not a continuous live stroke buffer; clone/smudge/quick-mask remain unsupported.
The main 3D view and 2D grid provide continuous live input.

MaterialTiles.preview(address, channel=0, resolution=512) leases a display-ready
RGBA8 thumbnail. The browser uses at most 256px per tile. A separate TileStore has
a 64 MiB resident budget, compressed backing and active-page pins; it shares the
global tracked texture budget. Its generation key includes material/source/layout,
document serial/settings, selected mask owner, color identity, channel/resolution
and bitmap/high-source timestamps/sizes. Cache misses evaluate only the requested
tile, including lower-resolution native replay. Bakes/composites are released;
the cache retains no authored texture pointers or leases. Thumbnails are disposable
and omitted from native snapshots/history. Color previews apply the display
transform; data channels do not. Main-view shading/exposure is not baked into them.

ImGui queues texture handles for later submission. The browser prepares thumbnails
after shortcut/view edits and keeps displayed cache pages pinned through draw
submission, then releases leases in a finally block. It never frees a queued
thumbnail as a side effect of the same frame's undo/redo.

tests/tiles_ui_check.py has sixty-three actual UI assertions for enable, idle reuse,
zoom/pan/fit, cross-boundary canvas input, frozen brush values, Escape, undo/redo,
isolation, typed image assignment/removal, diagnostics and portable save. Screenshot
visually reviewed, including tiles-3d.png, tiles-2d.png, tiles-live-uv.png and tiles-live-3d.png.
Checks include live cross-boundary pixels before release, one history entry,
Escape restoration and missing-brush-resource recovery. Actual 3D gestures reach
both tiles before release, commit once and cancel without history. Physical
tablet sampling and other GPU platforms remain unqualified.
Desktop checks also exercise actual mesh picking/material sampling and polygon
fill across all three tile addresses with one undo entry and pixel restoration.

## Main 2D grid

The main 2D view uses the material-output cache at the same viewport resolution
as 3D (at most 512px). It auto-frames a new material/mesh tile layout, retains
navigation across ordinary edits/resize, and exposes Frame UV tiles and tile-aware
Reset 2D view through the Viewport menu/command palette. Wheel zoom and middle
drag operate in global UV space, including sparse layouts spanning distant rows.
Tile labels and frames identify covered addresses. Empty cells remain background.

Each visible tile is clipped to its unit square and viewport scissor before
drawing. Offscreen tiles are skipped; cache leases last through the immediate GL
draw. Wireframe uses the original global UV mesh once, so crossing faces connect
correctly. Color, scalar, baked-map and world-normal diagnostics use the same
source fields as the existing single-tile UV view, with managed color applied
only to color/emissive. Missing-tile diagnostics are explicit and clear on repair.
UV lookup returns global coordinates for covered tiled geometry. Paint, erase,
base masks, independent paint-mask effects and projection update while held.
Clone, smudge, quick mask and symmetry remain guarded.

GPU checks cover distinct tile pixels, unused-cell background, nonzero framebuffer
origins, global UV lookup, managed color/data output and missing-resource reports.
Actual UI checks verify the three tile images, wheel/pan/frame controls and reuse
of the 3D cache during navigation. tiles-2d.png was visually reviewed. Legacy UV
UI/paint behavior remains regression-tested separately.

## Main 3D viewport and material-output cache

MaterialTiles.cached_evaluation(address, resolution=None, refresh=True) leases
native-precision final composites and bake maps from a separate TileEvaluationCache.
The default resident budget is 256 MiB alongside the global tracked texture budget.
Outputs retain texture precision and sampler settings, including categorical map
filtering. Authored leases, editable Layer objects and temporary compositor targets
are not retained. Eviction compresses exact bytes; cache data is disposable and
excluded from archives/history. Failed partial allocations discard their disposable
page without changing paint. Missing-resource errors cache per revision to avoid
repeated evaluation on idle frames, and invalidate on resource/settings changes.

Engine.render_materials(rect, indices=None, tile_resolution=512, refresh=True)
streams one leased tile at a time into the bound framebuffer, preserving depth
between materials/tiles. The viewport caps tile maps at 512px independently of
authored/export resolution. Direct cache callers can request native resolution,
subject to explicit cache/global budgets; an oversized page rejects rather than
silently lowering resolution. This is not 4K workload qualification.

The tiled scene shader subtracts tile addresses from global interpolated UVs and
discards fragments outside the half-open unit square. Crossing faces retain their
geometry/interpolation and cannot overwrite another tile with clamped samples.
The non-tiled shader remains unchanged. Picking returns global UVs and original
triangle IDs. Managed color uses the regular scene's working/display contract;
data diagnostics remain untransformed. Missing tiles return explicit diagnostics
and leave their region unshaded. Memory failures reach existing budget-recovery
controls. Paused refresh reuses the prior cached generation; resuming updates edits.

GPU checks cover distinct 1001/1002/1011 colors on crossing faces, cache reuse and
exact restore after eviction, paused/property generations, global picking, managed
color/data scene output, save with populated caches, missing-resource retry
suppression and cleanup after partial cache OOM. Height-derived normals use valid
neighbor strips on locally continuous surface edges. Outer, disconnected and
ambiguous edges clamp. General cross-tile filter neighborhoods remain unqualified.

A real 1024-to-2048 native boundary stroke matches direct 2048 authoring exactly
(maximum absolute error 0), with four store evictions under a 40 MiB tile budget.
The tracked texture peak is 923 MiB for this fixture; this excludes buffers/driver
allocations and is not a total VRAM measurement. Evidence:
.artifacts/material-tiles-t14-final/native-replay-1k-2k.json. This does not qualify
the desktop workflow or all-channel 4K workloads.

A separate live surface fixture also matches 1024-to-2048 replay against direct
2048 authoring exactly (maximum error 0). Its transient accumulation store evicts
five times under a 96 MiB resident limit. The isolated tracked texture peak is
958 MiB, excluding buffers/driver allocations. Evidence:
.artifacts/material-tiles-t14-final/surface-replay-1k-2k.json. This qualifies the
color-channel surface fixture, not all-channel 4K or large production assets.

Extensions outside the verified T14 acceptance contract:

1. Complete tiled clone/smudge/quick mask. Main 3D/2D live input is qualified
   separately from the browser's batch path tool.
2. Qualify larger cached tiled workloads and general cross-tile filter neighborhoods.
   Height-normal gutters are qualified. Cache misses still rebuild complete tile evaluation;
   independent reuse of static bake inputs remains a future optimization.
3. Integrate tiled clipboard forest copying and cross-material instances.
4. Extend T13 to changed UV/topology correspondence and retained orphan tiles.
5. Extend image assignment to external bake-map sequences, retaining global
   picking/provenance and local image sampling.
6. Extend qualification beyond the combined desktop/multi-material acceptance
   fixtures to large production assets, physical tablets and other GPU platforms.

The combined acceptance fixture now covers one material on 1001/1002/1011, a
second material, a boundary stroke, portable reopen, bounded mesh revision,
resolution change, atomic export, missing resources and memory eviction. Actual
desktop controls cover the tiled revision/resize/delivery workflow separately.
