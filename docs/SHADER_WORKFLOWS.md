# T18: user channels and shader workflows

T18 adds project-local scalar channels, independent specular/glossiness material
semantics, a clearcoat layer and physical vertex displacement. The original seven
channels, old project versions and ordinary metallic/roughness workflow retain
their storage and defaults. No compiled extension or dependency was installed.

## Desktop workflow

Open **Layer > Channels and shaders** (also available in the command palette).
Enter a lowercase channel name and choose **Create scalar channel**. The channel
is available throughout the project, including all material sets and native tiles.
Enable it on a layer, then edit its fill value, opacity and blend. On a paint layer,
**Paint selected channel** chooses its independent raster target; the ordinary
brush controls still determine coverage, pressure, alpha, spacing and symmetry.
Paint and Erase are supported. **Paint document channels** returns to the ordinary
seven-channel brush. Mask targeting continues to paint the selected mask.

**Add channel effect** inserts an invert, levels, blur, brightness/contrast or
native graph effect targeting this channel. Edit parameters and ordering in the
existing content-effect stack. User effects show their actual channel name.
Ordinary content effects continue to affect document channels. Both kinds share
the layer's masks, mask effects, geometry selection, authored-object coverage,
visibility and opacity; groups have independent scalar blend/opacity settings.
Standard accumulated-output anchors retain their existing meaning when used in
custom-channel masks. Cross-channel custom-output anchor captures are not added.

**Preview selected channel** displays scalar values in both 2D and 3D. Choose an
arbitrary R/G/B/A component and **Prepare packed export** to populate the existing
Export textures dialog. Its JSON template editor accepts `user:name` in any
component, with the usual sparse packing, formats, padding and resolution rules.
Unspecified RGB components are zero; the prepared template starts alpha at one.

For independent specular/glossiness, create four scalar channels and bind them to
`specular_r`, `specular_g`, `specular_b` and `glossiness` before selecting the
**Specular / glossiness** shading model. F0 RGB is **linear reflectance**, not sRGB
color. Base Color becomes the diffuse color; authored Metallic and Roughness remain
in the document but do not drive this preview. The selected shader exports zero
metallic and `1 - glossiness` roughness when those sources are requested.
Bind an optional independent `coat` weight and `coat_roughness` for either model.
The viewport's Specular F0, Shader Roughness and Clearcoat diagnostics show these
same values. **Prepare shader export** derives a template from the active model
and bindings, adding coat maps and signed meter displacement when enabled.
Shader/channel interpretation changes invalidate an existing export manifest.

## Storage, evaluation and bounds

- Keys match `user:[a-z][a-z0-9_]{0,31}`. Up to 16 arbitrary channels per project;
  labels up to 80 characters; defaults, fill/brush values and opacity in [0, 1].
  Channels are linear scalar data. RGB quantities use three scalar channels.
- Layer settings are `user_channels[key] = {value, enabled, blend, opacity}`.
  Disabled channels do not contribute. A group enables each declared channel by
  default, while ordinary layers require explicit enablement. Per-channel blend
  supports ordinary scalar modes 0–28, with -1 selecting Normal; encoded-normal
  blends are rejected.
- Paint storage is lazy, independent two-component half float value/coverage.
  It does not repurpose or overwrite the authored Height raster. Sparse MRT brush
  variants select the established scalar brush math. Custom Paint and Erase support
  native single-tile UV/surface strokes, polygon fill, recorded dab replay, cancel,
  undo/redo and resolution changes. Clone/smudge/projection on user channels are
  explicitly rejected before allocation; select Paint to continue.
- A reusable scratch compositor evaluates scalar channels through the established
  content/mask/blend passes. The original compositor supplies masks so anchor
  dependencies retain their standard source channels and evaluation ordering.
  Each output is one half-float texture. Shader-bound F0/gloss/coat values clamp to [0, 1] consistently in preview and
  export; raw custom graph outputs retain their data values. User outputs have a 256 MiB aggregate
  per-evaluation budget in addition to the existing global GPU budget. Scratch
  memory is allocated only when user channels exist and is reused across channels.
  Shader bindings pack into two RGBA half-float attachments; the scene shader stays
  within 16 fragment samplers. This does not qualify 16 simultaneous 8K outputs.
- Native tiled paint uses the existing owned leases, journals, eviction/backing and
  per-tile replay. Scalar outputs and shader bindings survive the disposable tile
  viewport cache. Arbitrary-component export works per UDIM. T14's other tool,
  revision and workload limits still apply.
- `assign_fill_map`, `add_fill_layer(maps=...)`, `set_channel_settings` and explicit
  `assign_tile_sequence` accept declared user channels. Images are data inputs;
  portable projects package them through the existing resource mechanism.
- Native **v13** is selected only when user definitions or non-default shader
  settings exist. Definitions, workflow bindings, layer settings, custom raster
  arrays and frozen brush targets survive reopen. Schema preflight checks declared
  references, settings, paint dimensions, journal/tile brush targets and physical
  units before project adoption. Active native journal branches are saved; redo
  branches remain session-only. Ordinary independent mask projects stay **v4**
  without journals/other optional features; plain tiled projects stay v9.

## Physical displacement

Declare source units when creating/preparing the mesh. The signed output is

```
displacement_meters = (height - height_midlevel) * displacement_meters_range
```

The UI's **Range (meters)** stores that range in
`shader_workflow.displacement_meters`, bounded to +/-1 meter. Midlevel defaults to
0.5. The preview converts meters to project units using the declared source unit
and mesh normalization scale, then displaces **existing vertices** along their
normals. The picked surface uses the same displacement and original triangle IDs.
Displaced surface normals use fragment derivatives plus the authored tangent
normal. Paint in 2D while the 3D displaced preview is active; turn the range to
zero to resume 3D painting. Signed output is a 32-bit EXR in the derived template.

OpenGL 3.3 provides this vertex-texture path, not a tessellation stage. Mesh density
therefore controls silhouette/detail; split seam vertices can separate if their
heights disagree. Tessellation, automatic subdivision, arbitrary topology repair
and tiled displacement are not implemented or advertised. Enabling tiles while
displacement is active, or enabling displacement on a tiled project, is rejected.

## Shader interpretation and target evidence

The specular/glossiness preview uses the existing GGX direct-light and environment
approximation with independent F0 and inverted glossiness. Clearcoat is a second
GGX reflection layer with dielectric F0=.04, its own roughness and attenuation of
the base layer. This is a bounded preview approximation, not exact Blender
Principled/Unreal/Unity BRDF equivalence. Transmission, scattering and anisotropy
were not added. T19 target setup/delivery conventions and qualified Blender scope are documented in DELIVERY.md.

The local reference asset is generated from actual Strata EXR exports. Blender
5.1.2/Cycles renders the independent F0/glossiness material using conductor plus
diffuse lobes, and a separate Principled coating material. Emission diagnostics
verify linear source values without lighting differences. Changed glossiness and
coat weight must also change actual BSDF renders. The packed editable
`.artifacts/channels-t18-final/blender-reference/reference.blend` retains source
images and node graphs. Reference reports explicitly exclude lighting/BRDF pixel
parity. Signed meter output also reconstructs a displaced reference surface.

## Qualification

Local ignored tests:

```
.venv/Scripts/python.exe tests/user_channels_check.py --gpu .artifacts/channels-t18-final
.venv/Scripts/python.exe tests/user_channels_ui_check.py .artifacts/user-channels-ui-t18-final
```

16 CPU/GPU scenarios cover definition validation, masks and standard anchors,
group opacity, graph/data maps, managed color independence, strokes/cancel/undo,
portable reopen/replay/resize, sparse arbitrary packing, stale shader manifests,
independent F0/gloss/coat behavior, physical surface picking, old v4 saves, tiled
paint/replay/cache/export and real Blender references. 16 desktop assertions
exercise actual creation, enable/value editing, effects, previews, UV painting,
component selection, export preparation, reopen/resize, binding/model controls
and derived shader templates. Screenshots were inspected.

Final regression evidence is recorded in IMPLEMENTATION_STATUS.md. Tests and
artifacts remain local and ignored; the repository CI remains source-syntax-only.
