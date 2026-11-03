# Transactional mesh revisions

Use **File > Reimport Mesh...**. Choose a revised file, review material mapping and
the projection distance, then **Stage mesh revision**. The current document stays
open while new geometry, bakes and supported native paint are prepared. A side by
side unlit comparison and a report show bounds, mapped/unmapped sets, UV changes,
projection counts and retained raster dependencies. Cancel releases the proposal.

Material names match automatically. Explicit mapping is available for renames.
Each new material belongs to at most one old set. Removed/unmapped sets retain
their identities, layers and pixels as unassigned sets; a later revision can
assign them to a material. New materials get empty sets. Content is never deleted
because its former material disappeared.

File loading reuses the original source normalization transform. Changed bounds
are not independently fitted back into the old box. Mesh arguments to the API
are already in project coordinates. Source physical units are not inferred.
Mikk projects retain the external Blender tangent path; legacy tangents retain
their existing implementation.

Native surface dabs and samples project to the closest point on mapped triangles,
within an explicit distance in normalized project units (default 10% of old mesh
radius). Frames follow the new surface normal, UV coordinates and footprint scale
are refreshed, and original camera occlusion is evaluated on the new mesh.
Normal reversals exceeding the supported hemisphere and missing correspondences
fail staging with a missed-sample report. No partial project is published.

Native UV operations replay when ordered per-set triangle UV coordinates agree
within 1e-7. Otherwise their current raster is retained with a warning. Legacy,
imported and clone/smudge checkpoint rasters keep their original UV coordinates.
They are not advertised as arbitrary topology reprojection. Imported mesh maps
also retain their raster interpretation; analytic maps and available high-poly
sources are rebaked. Missing/changed dependencies appear in the report.

Commit checks that document edits have not changed since staging, writes a
portable pre-reimport project under the resource cache's revisions directory,
then adopts the staged GPU state. It clears incompatible GPU undo history, marks
the new document unsaved and persists the report/checkpoint path in mesh metadata.
**File > Restore Pre-reimport Project** restores that checkpoint as unsaved work.
The checkpoint file must remain available for recovery; portable revision saves
include the new document, not an indefinitely growing collection of prior projects.
Publication and preview teardown run after the UI draw frame, so queued image
references are not destroyed while ImGui renders.

Engine API: strata.reimport.preview(engine, mesh_or_path, mapping=None,
max_distance=None) returns (mesh, report). prepare(...) stages a proposal with
.stage, .report, .commit() and .cancel(). Mapping keys are set pids and values
are material-index lists; an empty list deliberately retains an unassigned set.
Keep all GPU operations on the owning context thread. Cancel unused proposals.

## Qualification

Ten CPU/GPU scenarios pass: nearest triangle/edge/miss behavior, source transform,
UV-only revision, changed bounds, modest geometry, native UV preservation/fallback,
renamed and removed materials, reassignment, stale commit rejection, failed bake/
projection preservation, cancellation texture cleanup and portable recovery.
Eight actual UI assertions pass selector, stage/comparison, cancel, commit,
save/reopen and checkpoint restore. The staged screenshot was visually reviewed.
Local evidence: .artifacts/reimport-t13-final/ and .artifacts/reimport-ui-t13/.

This is bounded correspondence, not a promise for arbitrary topology edits,
folded/ambiguous surfaces, unit changes or multi-tile assets. Candidate search is
CPU vectorized per sample over the mapped triangles; large journals and meshes
may take substantial staging time.

T14 adds a bounded tile revision path with unchanged UVs, topology and material
assignments. UV-only tiled paint retains its coordinates. Native surface paint
uses bounded correspondence for samples/dabs and regenerates tile pixels from
the updated operations before commit. The comparison preview shows actual tile
materials. Misses, normal disagreement, cancellation and allocation failure retain
the original project; commit writes a portable recovery checkpoint. Changed UVs
or topology remain unsupported for tiles. See architecture/TILES.md.
