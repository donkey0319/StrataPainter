# T19: delivery and optional offline rendering

The qualified target integration is **Blender 5.1.2/Cycles**. Strata now delivers
actual geometry, material assignments and interpreted textures, not just named map
presets. Unreal/Unity texture templates remain available; automatic setup in those
applications is not claimed or marked verified. No dependency was installed.

## Desktop and source entry points

**File > Deliver mesh and materials** (also in the command palette) offers:

- **Blender mesh/material ZIP**: independent geometry and maps, a versioned material
  manifest, integrity inventory, and standalone Blender setup/validation scripts.
  Supports multiple single-tile material sets, metallic/roughness, independent
  specular/glossiness, clearcoat, fractional opacity, HDR emission, custom scalar
  maps and physical vertex displacement.
- **glTF 2.0 GLB**: actual indexed geometry, per-primitive material ownership,
  embedded PNG textures and glTF PBR materials. Supports metallic/roughness,
  fractional opacity, clearcoat and HDR emission via the corresponding Khronos
  extensions. Requires declared source units. Specular/glossiness, physical
  displacement and unbound arbitrary user channels reject with a Blender-bundle
  alternative rather than silently losing data.

Choose a destination and native or 128/256/512/1024/2048 output resolution. Native
paint/effects use the same detached evaluation/replay path as texture export.
The GUI shows a working frame before generating the file. The destination is
replaced only after successful staging/validation; failures preserve an existing
file. Export commits an in-flight edit/stroke, as ordinary export does, but does
not switch the active material, rewrite layer values or clear undo history.

Python operations used by both GUI and batch:

```python
from strata.delivery import export_blender, export_glb
export_blender(engine, "export/asset.zip", size=1024)
export_glb(engine, "export/asset.glb", size=1024)
```

Both formats currently require **single-tile UVs in [0,1]** and no enabled native
material tiles. T14's per-UDIM texture exporter remains the tiled-delivery path;
mesh/material UDIM reconstruction is not advertised by this package. Archives
have a 512 MiB uncompressed / 256-file budget, and GLB has a 512 MiB output budget.
These are output/decode limits, not a promise of bounded peak process memory at
arbitrary resolutions. The existing GPU allocation/evaluation limits still apply.

## Blender setup

Extract the ZIP to obtain `blender_delivery.py` and `bundleio.py`, then run:

```powershell
blender --background --factory-startup --python blender_delivery.py -- asset.zip --save asset.blend
```

The scripts also work directly from the source checkout:

```powershell
blender --background --factory-startup --python strata/blender_delivery.py -- export/asset.zip --save export/asset.blend
```

For an already running Blender Python host, explicitly load the setup script with
`runpy.run_path(path)` and call its `import_bundle(zip_path)`. Import creates a new
collection and materials, retains existing objects, packs imported images into
Blender data and returns `(object, manifest)`. Failed staged imports remove their
new objects/materials/images. The offline CLI uses a separate factory-startup
process and does not load a user's Blender startup/configuration or scripts.

The material graph is built from the manifest's semantic sources. It links color,
roughness, metallic, tangent normal and alpha; custom maps remain labeled image
nodes. Independent F0/glossiness uses conductor plus energy-reduced diffuse lobes;
its optional coating uses an independent dielectric reflection layer. The ordinary
metallic/roughness target uses Principled with native coat inputs. Emission adds
its linear HDR contribution, and alpha mixes the surface with transparency.
Height, AO and arbitrary user maps are retained as explicit auxiliary sources;
height is already included in the finished tangent normal and is not applied as a
second bump. AO is not multiplied into Principled's base color. Physical Cycles
lighting already handles occlusion; viewport AO/lighting equivalence is unclaimed.

## Manifest and interchange conventions

The ZIP contains:

- `manifest.json`: `version: 1`, `target: blender`, geometry description, material
  persistent IDs/names, shader model, semantic texture bindings, resolutions,
  color provenance, normal convention, workflow settings and file inventory.
- `geometry.npz`: positions, normals, UVs, triangle indices and per-triangle
  material indices. NumPy object/pickled arrays are prohibited. Decode dimensions,
  finite values, index ownership and zero normals are validated.
- `textures/set_###/channel_##.exr`: full-precision float color/data sources.
  Numeric filenames avoid material-name/path collisions.
- `blender_delivery.py` and `bundleio.py`: inspectable standalone setup code.

Each resource has a SHA-256 and byte length. Import validates the complete file
inventory and rejects tampering, duplicate/case-colliding paths, traversal,
Windows device names and decode budgets before adopting geometry. The native
optional renderer executes its installed importer, not code extracted from an
archive. The manifest is data, not an extension loader.

Project Y-up coordinates map to Blender Z-up with `(x, -z, y)`. If source units
are declared, geometry reverses source normalization and converts to meters,
including the saved source origin. Otherwise the Blender bundle preserves project
coordinates and declares `units: project`; that is not a physical scale claim.
GLB always requires meter conversion and retains the glTF right-handed Y-up frame.
Its UV V coordinate is inverted for glTF's upper-left texture origin. Finished
normal maps use **OpenGL / +Y** linear tangent normals. Blender and the GLB consumer
recompute MikkTSpace tangents: prepare/rebake the source with `tangent_basis="mikk"`
for target normal equivalence on complex/mirrored meshes. Arbitrary legacy tangent
bases are not qualified as equivalent.

The glTF implementation follows the [Khronos glTF 2.0 specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html).
GLB contains real accessors, aligned binary buffer views, indexed triangle
primitives, scene nodes and material assignments. Base color/alpha is RGBA;
ORM uses R=AO, G=roughness, B=metallic. RGB color images use sRGB; alpha, ORM,
normal and coat inputs are linear data. Clearcoat uses R=weight/G=roughness and
`KHR_materials_clearcoat`. HDR emission is normalized into an sRGB PNG with a
`KHR_materials_emissive_strength` factor. PNG maps are 8-bit; the Blender EXR bundle
retains float precision. Base-color reflectance outside [0,1] and negative GLB
emission reject rather than silently clipping unsupported HDR color.

Blender bundle color maps are explicit **linear Rec.709**. Managed source buffers
retain their working values; legacy color is converted using the preview's gamma
2.2 convention. The importer uses numeric Non-Color image reads into Blender's
linear Rec.709 scene so data and linear EXRs are not decoded twice. Display
exposure, environment and preview emissive-intensity controls are not baked into
material data. Target BRDFs and lighting differ from the Strata preview; exact
lighting/BRDF pixel equivalence is not claimed.

Physical displacement exports signed meters using T18's midlevel/range semantics.
The Blender setup applies bilinearly sampled meter offsets to existing vertices
along source normals. Vertices shared by materials are split when displaced so
different material height fields remain independent. It does not add subdivision,
tessellation or a second displacement/bump modifier. Mesh density and seam limits
from SHADER_WORKFLOWS.md continue to apply.

## Optional offline rendering

```powershell
python -m strata capabilities
python -m strata render export/asset.zip export/render.png --size 512 --samples 32
```

The `blender_cycles` backend discovers `STRATA_BLENDER`, PATH or the existing
Windows Blender installation. It starts Blender with `--background --factory-startup`,
uses isolated task configuration/scripts, imports the same delivery bundle, frames
it and renders with Cycles. A PNG is atomically published after successful rendering.
The JSON result names the actual destination and backend/version. Render limits
are 16–4096 pixels and 1–1024 samples; the API has a bounded subprocess timeout.
The backend does not overwrite or save a user's current Blender scene.

`strata.offline.render_bundle(bundle, output, size=512, samples=32,
backend="blender_cycles", timeout=300)` exposes the same operation. Missing or
unsupported backends raise `BackendUnavailable` before creating output; CLI errors
are JSON on stderr with exit code 2. Painting/exporting do not require an offline
backend. Particle simulation brushes remain a separate unimplemented optional
package, explicitly unavailable in capability results; no particle/Iray workflow
is advertised.

## Qualification and packaging

`tests/delivery_check.py --gpu .artifacts/delivery-t19-final` provides CPU contracts
and GPU/actual-runtime cases. Reference meshes contain two distinct material sets,
a UV color pattern, mirrored UVs and a tilted normal in matched MikkTSpace. Actual
Blender bundle import and the ordinary Blender glTF importer reconstruct material
inputs automatically; Cycles emission diagnostics compare their pixels with native
GPU output. Actual material renders and packed `.blend` reference assets are also
written. Fractional opacity, managed HDR emission/coat, F0/glossiness and signed
physical displacement have separate target-runtime cases. This exceeds filename
or node-presence checks, while excluding a claim of identical full BRDF lighting.

`tests/delivery_ui_check.py .artifacts/delivery-ui-t19-final` exercises the actual
File menu, formats, size/destination edits, exports, visible completion, an invalid
GLB preserving its destination and an extension menu action. Screenshots were
inspected. All tests and generated fixtures remain local and ignored.

The GUI PyInstaller recipe includes readable Blender setup/validation source assets.
`run_batch.py` and `packaging/strata_batch.spec` provide a separate console build
with the same CLI, source assets and optional installed OCIO/mesh readers. Source
entry points are verified. **Frozen builds are unverified:** PyInstaller is not
installed in the current environment, and no release build/dependency install was
performed. See IMPLEMENTATION_STATUS.md for final regression evidence and
EXTENSIONS.md for the versioned API/batch schema.
