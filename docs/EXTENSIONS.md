# Extension and batch API v1

`strata.extensions.API_VERSION == 1` is the public command extension contract.
It is an explicit Python host API shared by source CLI jobs and optional GUI
commands. Extensions are not loaded from native projects, delivery manifests,
shelf metadata, filenames or the working directory automatically.

## Native operations

```python
from strata.extensions import builtins
registry = builtins()
registry.execute(engine, "layer.add", {"kind": "fill", "name": "Finish"})
registry.execute(engine, "layer.configure", {"values": {"rough": 0.3}})
registry.execute(engine, "delivery.blender", {"path": "export/asset.zip"})
```

`registry.describe()` returns descriptions/signatures; `validate(command, params)`
binds arguments without executing. `execute` requires an object of parameters and
returns a JSON-serializable value. Existing engine operations still own edits,
undo, pixel storage, resolution replay, persistence and export. A callback runs
on the owning engine/GL thread and must observe existing tile leases and resource
ownership; the API does not make GPU objects thread-safe.

| Command | Parameters / result |
|---|---|
| `project.new` | `mesh="Canister"` (built-in name or mesh file), `resolution=256`, `source_unit=None`, `tangent_basis="legacy"`, `ao_samples=16`; material-set identities returned |
| `project.load` / `project.save` | `path`; save additionally `portable=False`; native staged load/atomic save |
| `material.select` | `index`; returns selected persistent set ID |
| `material.resize` | `resolution`, optional `index`; native resize/replay |
| `layer.add` | `kind="paint"`, `name=None`; returns persistent layer ID and selects it |
| `layer.configure` | `values` property object, optional `pid` (current layer otherwise); native undo transaction |
| `layer.select` | `pid`; selects the layer and owning material |
| `channel.declare` | `name`, `default=0`, `label=None`; returns `user:name` |
| `channel.fill` | `key`, `value`, `enabled=True`, `pid=None`; native scalar layer edit |
| `shader.configure` | `settings` object; uses T18 native validation |
| `brush.uv_path` | `points` (1–100000 UV samples), `brush=None` (native Brush fields), `viewport=[512,512]`, `seed=17`; records a native undoable/replayable stroke |
| `textures.export` | `folder`, `template="$workflow"` (active shader template, built-in template, JSON path or dictionary), `size=None`; ordinary native export manifest/writer |
| `delivery.blender` / `delivery.glb` | `path`, `size=None`; same delivery operations as the desktop panel |

Builtin command namespaces are reserved. This version has no job-variable language,
implicit layer-name resolution, arbitrary eval, automatic extension discovery or
promise of cross-version compatibility for private engine fields.

## Explicit Python extension

Create/import an ordinary trusted Python module:

```python
STRATA_EXTENSION_API = 1

def register(registry):
    def tint(engine, color=(0.7, 0.2, 0.1)):
        return engine.set_properties(engine.layer, color=list(color))
    registry.register("example.tint", tint, "Set the selected layer color")
```

Identifiers use `namespace.command`; duplicates and builtin namespaces reject.
The handler's first parameter must be `engine`. Module API version must match
before `register` is called. A Python host uses
`load_extension(registry, "examples.strata_delivery_extension")`; CLI loading is
explicit via `--extension`. Extension modules execute Python under the host's
normal permissions and are intended for code the user deliberately chooses.
Project/delivery data cannot request extension loading.

`install_ui_command(registry, app, command, params, label, menu="Extensions")`
adds an explicit menu/command-palette action, without executing it. The App renders
registered extension menus and dispatches through the same registry/engine. Use a
separate menu name; builtin File/Edit/Layer/Viewport/Window/Help categories are
reserved. Installing a command is a Python-host operation, not a project setting.
The example module in `examples/strata_delivery_extension.py` is not autoloaded.

## Batch schema and CLI

```powershell
python -m strata commands
python -m strata batch examples/delivery_job.json
python -m strata --extension examples.strata_delivery_extension commands
python run_batch.py capabilities
```

The command listing/capability probe creates no OpenGL context. A batch job uses a
standalone OpenGL 3.3 context with the ordinary Engine; `run.py` remains the GUI
launcher. Source CLI output is one JSON object on stdout, and operational logs and
errors go to stderr. Exit code 0 means success; operational failure returns 2.
Argparse also uses exit code 2 for invalid CLI syntax.

```json
{
  "version": 1,
  "steps": [
    {"command": "project.load", "params": {"path": "asset.strata"}},
    {"command": "material.select", "params": {"index": 0}},
    {"command": "delivery.blender", "params": {"path": "export/asset.zip", "size": 1024}}
  ]
}
```

Native file/folder and template-JSON paths are relative to the **job file's directory**.
Builtin mesh names retain their meaning. Extension parameters remain the
extension's own contract. Results contain each command and its JSON result;
persistent IDs may be used by Python callers or already-known project references.
There is no substitution of prior step results in job JSON. The selected native
layer/material provides ordinary sequential context.

Input is limited to 1 MiB and 1–64 steps. Schema, command existence and argument
binding are checked for every step before the first step executes. Unsupported
fields, non-object params, non-finite JSON constants and unknown commands reject.
A failing runtime step stops subsequent steps and reports its number/command.
Jobs are **not whole-job transactions**: earlier completed exports/saves remain.
Individual native loads, saves, resizes and delivery publication retain their own
transaction/atomicity contracts. No implicit save or push occurs.

`strata.cli.run_job(engine, job, registry=None, base=None)` exposes the same
preflight/sequencing to a Python host, without taking ownership of its engine.
CLI-created engines/cache directories are released at completion. Explicitly
configured resource caches and Blender paths are respected. Optional offline
rendering has a separate `render` command and fixture; see DELIVERY.md.

The source entry points, explicit module loading/version rejection, GUI callback
bridge, native paint/portable reopen/resolution delivery and runtime-error behavior
are qualified by local ignored T19 checks. PyInstaller recipes are prepared but
frozen executables remain unverified; no packaging dependency was installed.
