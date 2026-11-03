# Persistent document identities

Layers, effects and texture sets have a `pid`: a lowercase, 32-character UUID hex
string. Runtime `uid` remains the UI selection key. Archive `_id` remains the GPU
array and instance-reference key. These identifiers have separate purposes.

Native v3 archives persist `pid` as additive metadata. Earlier archives without
IDs generate them on restoration and retain them on the next save. Archive
validation rejects malformed or duplicate identities on full definitions;
`instance` entries reuse the referenced definition rather than redefining it.
Raster instances spanning different texture resolutions are rejected before GPU
restoration. Definition-only fills and groups may still share parameters.

Content anchor effects define an anchor with their effect `pid`. Mask anchor
effects store that ID in `params.source_pid`. `bind_anchor_references` migrates
legacy names only when the name identifies exactly one definition. Once bound,
renaming either display label cannot retarget the reference. Missing, ambiguous,
forward and cyclic references produce diagnostics; unavailable captures evaluate
as black rather than reading a previous frame's texture.

`renew_persistent_ids` operates on the complete copied forest. Internal references
are remapped to copied definitions; references outside that forest retain their
source IDs. The engine independently renews runtime UI IDs when cloning. Library
and converted-material insertion also renew persistent IDs so repeated drops
remain independent.

Each compositor evaluation clears its available anchor captures. GPU allocation
storage may be reused, but only captures produced during the current evaluation
can be read. Deleted definitions release their allocation storage. Trees with
anchors use complete evaluation until partial snapshots also capture dependency
state. `Compositor.anchor_diagnostics` exposes dependency migration diagnostics.
