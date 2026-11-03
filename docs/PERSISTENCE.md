# Native project persistence and recovery

Strata saves schema version 3 projects (version 4 when independent mask paint is present) as ZIP archives containing `project.json`,
`data.npz` and optional content-addressed resource members. Version 1 and version 2
projects remain readable. Unsupported future versions are rejected before the
current project is replaced.

Optional schema v14 adds project-owned export configuration: the resolved template,
destination, selected set identities, map overrides, format/depth, output size and
padding. Save settings or a successful export records it as undoable document
metadata. It restores without writing any output. Projects without this optional
configuration retain their prior minimum version; the current reader supports
v1–v14. Older readers explicitly reject v14. See EXPORT.md.

Version 4 adds validated per-effect mask-paint arrays. Projects without these
effects continue to save as v3. See [effect storage and compatibility](EFFECTS.md).

## Engine operations

```python
engine.save(path)                         # atomic save, external references allowed
engine.save(path, portable=True, backups=3)
engine.autosave(recovery_path, backups=3) # portable snapshot, does not mark saved
engine.load(path)                         # transactional CPU and GPU restoration
engine.relink_resources({resource_id: replacement_path})
engine.mark_modified()                   # recovery/import must still prompt to save
```

`save()` preserves its existing default behavior of not collecting all external
dependencies. `portable=True` embeds referenced bitmap maps, image alphas,
stencils, projection images, the environment and file-based high-poly sources.
Previously embedded resources remain embedded when an ordinary save follows a
portable load; temporary extraction paths are never saved as permanent sources.
Built-in brush alphas and `bake:` mesh-map references are not external files.

Resources have a SHA256 content ID, original source path, optional project-relative
fallback, byte length, roles and an optional embedded archive member. Different
Windows drives use an absolute fallback instead of an invalid relative path.
Archive resources are validated by hash and length and written only to generated
safe filenames in an owned temporary directory; archive paths are never extracted
blindly. Extracted files live for the project session. New projects retain brush
and environment dependencies that intentionally carry over, including their
embedded files, while dropping unrelated project resource records.

`engine.project_resources` lists resource dictionaries with `id`, `source`,
`resolved`, `roles`, `embedded` and `status`. Status is `available`, `embedded`,
`changed` or `missing`. `engine.project_diagnostics` contains dictionaries with
`code`, `severity`, `message` and resource identifiers/source paths where relevant.

Relinking accepts resource IDs or known source/resolved paths. Unknown references
are errors. Replacements are checked before live paths change: bitmap resources
must decode and high-poly meshes must parse. The environment is prepared before
its previous texture is replaced. Relinking marks the project modified and keeps
existing baked maps; rebaking is a separate explicit operation. It is not yet a
T03 undo transaction.

## Baked maps and provenance

The archive stores baked-map pixels with shape, GPU storage type and SHA256 checks.
The low-poly mesh normalization transform is preserved. Texture sets restore their
own bake settings and maps independently, even when display names are duplicated.

At bake time the engine records a settings snapshot and high-poly source content
hashes. The cache fingerprint includes mesh arrays, actual baked settings,
source hashes, resolution, material assignments and normalization transform.
Changing the current settings or source file without rebaking does not relabel
the saved cache as a newly generated result. On load, the retained cache can be
reported stale while the current settings remain editable.

Missing or changed external high-poly sources do not silently replace a valid
saved bake with a low-poly bake. An in-memory high-poly source can also retain its
cached output after reopening, but its geometry is not serialized as a source.
These cases produce diagnostics. Explicit rebake refuses configured sources
that cannot be reconstructed; relink them or explicitly clear them first.

## Failure behavior

Saving writes a sibling temporary archive, validates it, flushes it, and replaces
the destination only after success. With `backups=N`, previous archives rotate
through `.bak1` to `.bakN`. The existing destination remains present if the new
archive cannot be written or published. Autosaves use this same writer and always
collect portable resources without changing the user's saved/modified marker.

Loading validates metadata, versions, mesh and paint dimensions, numeric arrays,
instance references, resource members and cached-map payloads before GPU work.
Restoration then owns separate mesh, layer, compositor, resource and paint
objects on the existing context. Failures release staged resources and preserve
the open project. Success keeps the Engine and Brush object identities so UI
commands retain valid references.

The UI recovery controller owns timing, sidecar session/source information,
recovery selection and user-facing dialogs. Restoring an autosave must call
`mark_modified()` and restore the intended user project path rather than making
the recovery snapshot the normal save destination.

## Verification

```powershell
python tests/persistence_check.py
python tests/persistence_check.py --gpu .artifacts/persistence
```

The CPU checks cover archive validation, portability, backups and interrupted
publication. The GPU checks cover distinct per-set settings and pixels, transform
preservation, brush identity/built-ins, portable autosave, relink/new-project
lifetime, failed-load rollback, unavailable high-poly sources and stale
source/settings provenance. Run these using a verified native environment with
the required project dependencies; GPU checks need an OpenGL 3.3 context.

Remaining scope outside this persistence package includes fully undoable relink
transactions, the broader persistent layer-ID contract from T03, native paint
operation journals and geometry/UV reprojection. Portable save cannot embed an
already missing file, and cached high-poly maps do not reconstruct missing source
geometry.
