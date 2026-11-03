# Document edits and persistent identities

T03 extends the existing version 3 archive with optional persistent IDs. Older projects remain readable. This document describes the integration contract; qualification results are recorded in IMPLEMENTATION_STATUS.md.

## Edit boundaries

Document controls use `Engine.begin_edit(targets, label)`, `set_properties(target, **values)`, and `commit_edit()` or `cancel_edit()`. `set_property(target, name, value)` is the single-field convenience method. Calling a setter without an active edit creates a discrete transaction. Targets must belong to the open document. Brush presets and viewport settings are session controls rather than document transactions.

A slider drag or text edit has one history entry. Compound actions such as applying a material to selected layers share one transaction. Escape restores the captured values; returning to the initial value produces no entry. Cancel and ineffective edits preserve the redo branch. Nested generator and projection objects retain their identity during restoration. Metadata snapshots exclude GPU storage, tree membership and identity fields; those remain engine-owned operations.

Undo and redo invalidate the compositors that depend on changed objects, including shared definitions in other texture sets. Property, tree, raster, quick-mask and resource history restore their document revisions so undo can return to the saved state. Revision numbers remain unique when a new edit replaces a redo branch.

## Identity contract

`pid` is a persisted UUID expressed as 32 lowercase hexadecimal characters. Layers, effects and texture sets keep this identity through save/reopen. Existing integer `uid` values remain process-local UI handles. Archive `_id` and `_instance` values continue to encode storage and shared definitions; they are separate from persistent identity.

Anchor references use the definition effect's `pid` in `params.source_pid`. Unique legacy names migrate to IDs; names remain editable display labels. Missing, ambiguous and forward references produce diagnostics. Compositor evaluation must not reuse a previous capture when a source becomes unavailable.

Copy a forest with `Engine.clone_layers(layers)` rather than cloning roots independently: internal anchor references must point to the copied definitions. External references keep their original target identity. Inserting a reusable resource likewise gives its copied definitions fresh identities.

## Instance storage

Material instances share their definition, so parameter changes affect every instance. GPU paint and mask storage is resolution-dependent. Sharing raster storage across differently sized texture sets is rejected before mutation; resize and mask creation must enforce the same restriction. Duplicate a layer when independent storage is needed. This guard is an interim storage policy, not independent raster-instance support.

## Qualification

Run CPU identity and transaction checks on every platform. Native GPU qualification additionally covers pixels after undo/cancel, shared-set invalidation, mask lifecycle, resource replacement and archive roundtrips. Actual UI gestures must verify drag grouping and Escape cancellation. Preserve the frozen T00 project and reference images when checking migration compatibility.
