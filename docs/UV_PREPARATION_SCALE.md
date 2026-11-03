# Automatic UV preparation and physical scale

New Project can inspect UV availability and optionally **Prepare missing UVs
(Blender)**. The default preserves valid triangle UVs exactly. **Regenerate valid
UVs too** is an explicit choice. Smart projection and angle-based unwrap use
angle/dihedral seams, pixel padding at the document resolution and an island
rotation choice. The installed Blender 5.1.2 backend runs in background factory
mode with isolated settings; STRATA_BLENDER selects its executable.

All geometry is retained when loading mixed UV input for preparation. Ordinary
loads now report missing UV parts/faces rather than silently dropping them.
Degenerate geometry and nonmanifold edges produce repair instructions.
By default, per-material generated charts fit tile (0,0). Preserved charts occupy
conservative UV bounds; generated charts use a free rectangle beside them. If no
suitable region exists, increase the tile budget, choose regeneration or separate
the material. The rectangle search
is conservative, so it can reject layouts with irregular usable gaps. Generated
UVs split vertices at corners while retaining face order, normals, parts and
material identity.

**UV tile budget per material** selects 1–64 pages, starting at UDIM 1001,
with ten columns before wrapping to the next row. One remains the default.
For multi-tile preparation, geometric charts follow source parts and dihedral
seams at the selected angle. Intact charts are assigned deterministically by
surface area and available rectangle area; Blender unwraps and packs each page.
Materials have separate layouts and raster ownership even when their UDIM
numbers match. Prepared materials extending beyond 1001 automatically enable
T14 tiled painting during project creation.

The budget is a maximum, not a promise to fill every page. A smooth connected
chart stays intact and may occupy only one page; this allocator does not cut it
into arbitrary tiles or guarantee uniform texel density/optimal packing.
Preserved faces must each fit one page within the selected budget. Cross-page
preserved faces or insufficient space produce actionable errors before the
backend runs; choose a larger budget or explicit regeneration. The conservative
free-rectangle search can reject irregular usable gaps. Existing overlaps in
preserved UVs are retained rather than repaired.

Pixel padding is converted to a UV fraction at the chosen resolution; changing
resolution later does not automatically repack the mesh. Generated UVs are mesh
data and survive save/reopen and OBJ delivery. UDIM maps use the normal tiled
exporter; T19 mesh/material bundles and GLB retain their single-tile limit.

Reimport's **Prepare missing revision UVs** uses the same backend and enters the
T13 staging/comparison/commit transaction. Existing source normalization is reused.
Surface operations reproject; changed native UV correspondence and raster bases
follow the explicit T13 retention/report policy. Preparation is not an alternate
path that silently replaces the open project. **Revision UV tile budget** selects
the same allocator before choosing a revised mesh. An already tiled project
retains T14's requirement for unchanged UVs, topology and material assignment:
regenerating an identical layout can stage/commit, while changed packing is
rejected with the open project and its pixels preserved. General tiled raster
reprojection is outside this package.

Declare source units in New Project: meters, centimeters, millimeters, inches or
feet. Unspecified means no physical-size inference. Metadata retains this
declaration separately from normalized rendering coordinates and the source
normalization transform. For planar/tri-planar fill maps, **Physical repeat**
specifies the period in meters; zero selects ordinary dimensionless scale.
Projection scale multiplies that frequency. This control uses normal property
transactions and is undoable. UV, spherical and cylindrical modes retain their
existing coordinate semantics and do not claim a physical repeat.

Positive physical repeat requires archive **v8**, preventing older readers from
silently ignoring its material semantics. Unit metadata and generated UV geometry
alone can use existing raster/journal formats. Legacy projects and defaults retain
their original behavior.

File menu commands export OBJ in normalized coordinates, original source
coordinates, or meters. Source export reverses the saved normalization transform;
meter export additionally applies the declared unit. UVs/normals/material groups
remain intact. Meter delivery rejects unspecified units before writing.

API: strata.uvprep.prepare_mesh(mesh, settings, source_unit=None) returns a new
mesh; uv_status(mesh) reports valid triangles. new_project accepts uv_settings
and source_unit. export_mesh(engine, path, coordinates='normalized') also accepts
'source' and 'meters'. UV settings are method ('smart'/'angle'), preserve_valid,
resolution, padding_px, angle_degrees, rotate and tile_count (default 1, maximum 64).
The uv_preparation metadata records the actual occupied tiles and selected settings.
No new archive version is required: multi-tile raster projects use existing v9
(or a later version required by their other features). Both packaging recipes
include the readable external unwrap worker; frozen execution remains a T20 gate.

Initial single-tile qualification: seven CPU/runtime scenarios cover real mixed-material OBJ input,
exact preservation, both installed Blender methods, degenerate/nonmanifold errors,
paint/save/reopen, delivered UV/source coordinates, equal physical-repeat pixels
on differently sized assets, and prepared-UV transactional reimport. Eight actual
UI assertions cover inspection, creation, units, physical-repeat undo/reopen and
mesh/map delivery. Screenshot inspected. Local evidence: .artifacts/uvprep-t21-final/
and .artifacts/uvprep-ui-t21-final/. Other platforms/Blender versions and Assimp's
full import-format corpus remain unqualified.

Backend API reference: [Blender UV operators](https://docs.blender.org/api/current/bpy.ops.uv.html).

Multi-tile extension (November 2, 2026): seven additional CPU/Blender/GPU
scenarios verify deterministic and angle-seam allocation, both Blender methods,
11-page row wrapping, nonoverlapping generated chart interiors, resolution-aware
padding, exact fixed UVs on either page, separate materials, failed-budget source
preservation, automatic tiled project creation, per-page painting, undo/redo,
portable pixel equality, OBJ UVs, UDIM map names and transactional revision
acceptance/rejection. The desktop suite now has twelve assertions, including the
actual new-project and revision budget controls. Guarded CPU checks import no GL
or UI backend. Tests and evidence stay local and ignored.

Final combined regression evidence: `.artifacts/t21-final/report.json`.
Focused evidence: `.artifacts/uvprep-tiles-t21-qualified/`,
`.artifacts/t21-tiles-qualified.log`, `.artifacts/uvprep-ui-t21-extension-focused/`.
