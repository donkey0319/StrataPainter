# T14 acceptance record

T14 is verified locally against `STRATA_PAINTER_IMPLEMENTATION_PLAN.md`, for
authored/imported multi-tile UV layouts. This record identifies the verified
contract and its limits; it does not claim complete Painter feature parity.

| Plan requirement | Implemented behavior | Evidence |
| --- | --- | --- |
| One material owns multiple addresses; legacy migration | One layer/effect tree per material, material-owned lazy tile stores, legacy pixels/base on 1001 | Foundation contracts; portable v9 roundtrips; canonical higher-resolution base checks |
| Addressing, boundaries and crossing faces | Half-open coordinates, validated UDIM convention, positive-area partitioning, original face/barycentric provenance | Eight CPU and four isolated GPU scenarios; deterministic random geometry/area checks |
| Independent bake/evaluation, caching, streaming and cross-tile paint/masks | Budgeted authored/transient/output stores; native UV/surface paint, erase, projection, base/effect masks; whole-mesh occlusion; revision-keyed cache | Live pixels before release; one undo/cancel; exact replay; eviction/OOM preservation; managed color/data checks |
| Tile browser, isolation, UV grid, diagnostics and image assignment | Browser and main 2D grid; 3D shading/global picking; explicit per-channel/per-tile image paths and missing-resource reports | 63 actual desktop assertions, including choose/stage/commit, portable reopen, resize and delivery |
| Delivery, anchor and instance audit | Validated `$udim`/implicit naming, atomic multi-material manifests, tile-local anchor evaluation and independent duplication; unsupported sharing rejects before mutation | Collision/stale/fault tests; copied-anchor bindings and combined history; guarded instance/clipboard tests |

The combined Engine acceptance fixture uses two materials: the first spans
1001/1002/1011 and the second spans 1001/1002. It paints across 1001/1002, reports
and resolves a missing image, saves/reopens portably, commits a bounded mesh
revision with a recovery checkpoint, resizes 128 to 512, forces authored eviction,
and writes ten textures plus two material JSON files. Delivered boundary pixels
match evaluated values. Evidence: `.artifacts/material-tiles-t14-final/t14-acceptance.json`.

The desktop fixture exercises actual revision selector/stage/commit buttons,
retains material/tile/layer identities, reopens portably, refreshes the grid after
64-to-256 resize, and writes all three correctly named color tiles with matching
boundary pixels. Results: `.artifacts/tiles-ui-t14-final/results.json`.

Height-derived normals sample neighboring height/coverage strips. Eight narrow
world-position strips establish a bounded surface-continuity gate, avoiding bleed
between nearby disconnected islands. Neighbors evaluate sequentially; retained
edge storage is O(resolution). Horizontal/vertical edges match an independent
central-difference/normal-combination reference; missing neighbors clamp. Portable
reopen is exact. Existing authored and high-poly normal combination is retained.

53 Engine GPU scenarios and 63 tile desktop assertions pass, alongside the final
regression matrix in `IMPLEMENTATION_STATUS.md`. Native color replay at 1K-to-2K
matches direct 2K authoring exactly with live-buffer eviction. Independent-mask
projects without journals remain v4; explicit tiled projects remain v9. Frozen v2
settings/all 16 reference maps and portable v3 roundtrip pass. The known low-flow
failure remains at 0.999; no new regression is accepted.

## Audited limits and extensions

- Native tiled clone, smudge and quick masks reject explicitly; they are outside
  the verified paint/erase/projection/base-mask/effect-mask contract.
- Cross-material instances and tiled clipboard forest copying reject explicitly.
  Same-material independent layer/group duplication is supported. The instance
  audit is complete; shared tiled raster ownership is not implemented.
- Reimport supports bounded correspondence with unchanged UVs, topology and
  material assignments. Misses/normal disagreement preserve the source project.
  Changed UV/topology and arbitrary surface preservation remain unsupported.
- Explicit fill-image sequences cover the current seven channels. External
  mesh-map sequences and tile-aware native raster shelf assets remain guarded.
- Height-normal gutters are supported on covered, locally continuous surface
  edges. Hard/disconnected/ambiguous borders clamp conservatively. General
  cross-tile blur/warp/filter neighborhoods remain tile-local and unqualified.
- Qualification is local Windows/RTX 4050. Physical tablets, other GPU platforms,
  all-channel 4K/large production assets remain unqualified. T21 subsequently adds
  bounded automatic multi-tile angle-seam chart allocation; see
  [UV preparation](../UV_PREPARATION_SCALE.md). T14's unchanged-layout revision
  restriction still applies.

Earlier progress entries accumulated these broader extensions under “before T14
verification.” They are retained here as explicit follow-ups. The baseline T14
plan requires the implemented material/tile workflow and an instance audit; it
does not require all raster tools, arbitrary topology changes or automatic packing.
