# Advanced bake controls (T15)

T15 extends the transactional T09 baker with named source pairing, authored cages,
supersampling and paintable projection corrections. Qualification is local Windows /
RTX 4050; automatic cage generation remains a separate enhancement.

## Artist workflow

In Bake Mesh Maps, choose all-source transfer or mesh/part-name matching, optionally
edit the low/high suffixes, choose 1x/2x/4x supersampling and import a projection cage.
Matching is case-sensitive and strips only the configured terminal suffix. Multiple
matching high parts contribute together; unmatched active low parts reject the bake.
The existing AO/thickness/ID switches and each baker's parameters remain available.
Position, world normal, curvature and coverage are required; high sources also produce
normal and height. Applying shared parameters preserves each material's correction
owners and external-map assignments.

Cages must preserve the low mesh's indexed vertex order and triangle topology. They
load in the low mesh's source transform, without independent normalization. Validation
rejects nonfinite, inward/zero-distance, inverted and degenerate cages before publication.
The cage supplies the frontal ray origin; the rear limit remains configurable.
A GPU prepass detects another low surface along the low-to-cage segment. Such crossings
reject transfer at those texels, even when all cage vertices point outward.

The mesh-map panel displays projection diagnostics: green hit, red miss, blue cage
crossing, and transparent outside UV coverage. Tiled materials offer a diagnostic tile
selector and evaluate the selected tile's correction data. Previews copy their source
before releasing tile/cache leases, so painting and saving can proceed in the same frame.

Bind a dedicated, unmasked paint layer without effects as a ray or distance correction.
Binding is undoable and disables its material channels. The Paint correction action
selects its owner and raw data channel; use the ordinary surface or UV brush and undo.
Ray correction uses the Normal RGB channel as an encoded world direction (RGB * 2 - 1).
Distance correction uses Height 0..1 for 0..2 times the frontal/rear range, with 0.5
neutral; zero is clamped to a small positive range. Transparent pixels are neutral and
partial coverage blends the correction. These are raw data fields without a color transform.
Rebake explicitly after painting. Normal and height conversion uses the original low
surface frame and ray-range encoding, including when the projection direction is skewed.

Transfer pairing affects projection only. AO and thickness include all selected high
parts, including self-occlusion and cross-part occlusion; pairing does not isolate them.
Without high sources, the whole low mesh is the occluder, including other texture sets.

## Storage and staging

`BakeSettings` adds `pairing`, `low_suffix`, `high_suffix`, `cage_path`, `cage_hash`,
`supersampling`, `ray_correction_pid`, `distance_correction_pid` and `correction_hashes`.
`Engine.set_bake_correction(kind, layer=None)` binds or clears an active material's field.
Cage paths are portable resources with content identities and validated resource relink.
Correction owners use persistent layer IDs and ordinary pixel/journal/tile storage.
Changed field content marks retained saved bake output stale; a deleted field remains
saveable/recoverable and reports a missing-owner error on rebake until restored or cleared.

Advanced settings activate project format v10. Default settings omit these optional keys;
ordinary independent-mask projects remain v4, and ordinary tiled projects remain v9.
Saved projection diagnostics retain native dimensions and categorical colors.
The root bake of a corrected tiled material represents its first tile; tile evaluation
uses the selected tile's actual fields. Portable reopen and resolution replay preserve
those fields. Supersampling respects the GPU texture-size limit, reduces continuous maps
with filtering, renormalizes normals/tangents and samples categorical maps without mixing IDs.
All-set bakes stage before publication; failed validation/allocation retains live maps,
settings and history. Temporary textures, framebuffers and geometry resources are released.

## Qualification

- `tests/advanced_bake_check.py --gpu .artifacts/bake-t15-final`: 13 scenarios
  (three CPU contracts and ten GPU scenarios). Includes nearby unrelated high parts,
  unmatched names, inverted cages, thin gaps, overlapping material UVs, analytical flat
  normal/height references, 2x/4x sampling, painted skew/range recovery, undo/redo,
  stale/missing correction and cage recovery, portable reopen, tiled resize and allocation rollback.
- `tests/advanced_bake_ui_check.py .artifacts/bake-ui-t15-final`: ten actual desktop
  assertions for source controls, cage selection, bake, field binding, UV painting,
  undo/redo and portable reopen. Source/field screenshots were visually reviewed.
- The CPU contracts are included in `.github/workflows/checks.yml`; hosted CI is unrun.
- Final integration results are recorded in IMPLEMENTATION_STATUS.md.

Validation and sampled low-to-cage ray crossings do not certify arbitrary cage
self-intersections or mesh manifoldness. No automatic cage generator, arbitrary-topology
cage remapping, external mesh-map tile sequences, production-scale 4x bake benchmark or
cross-platform GPU qualification is claimed. Existing low-flow accumulation failure is
unchanged. No Adobe pixel-identity claim is made for this baker.
