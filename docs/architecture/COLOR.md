# Color and tangent-space contract

Legacy projects keep their existing storage, shader math, preview and exports.
Managed mode is an explicit new-project choice and requires OpenColorIO. No old
project is silently converted. Managed projects use a distinct archive version
so older readers cannot interpret linear paint as encoded RGB.

Managed working RGB is scene-linear Rec.709/sRGB primaries. The fixed OCIO built-in
studio-config-v2.2.0_aces-v1.3_ocio-v2.4 provides input and display transforms;
display is sRGB - Display / Un-tone-mapped. Its exact identity participates in
resource caches and project provenance. This initial managed mode does not claim
arbitrary user OCIO configs, ACEScg working primaries, AgX or HDR-monitor output.

| Input/output | Managed interpretation |
|---|---|
| Color/emissive UI pickers | sRGB values converted to working RGB before evaluation; model values remain picker values |
| LDR color/emissive bitmap | sRGB by default; explicit immutable-resource override may mark linear |
| HDR/EXR/PFM color bitmap | Linear by default; retained without an upper display clamp |
| Alpha/stencil/masks/roughness/metal/height/normal/opacity/mesh maps | Data; never receive color or display transforms |
| Color paint | Premultiplied linear RGB and coverage; undo/save preserve working values |
| Fill/content/blend | Linear working RGB, float storage; effects operate in that space; scalar/normal math unchanged |
| Emissive | HDR working values retained; display intensity/exposure applied only during preview |
| Material and color-only preview | OCIO display function; no display transform on data diagnostics |
| Color texture exports | Explicit sRGB encoding for ordinary image delivery; linear values for EXR/HDR/PFM |
| Packed data/normal exports | No display or color curve; existing normal convention conversion remains explicit |

Base-color PBR evaluation remains bounded to physical 0–1 reflectance. Emissive
HDR can exceed one. Managed color accumulators/content use float storage rather
than legacy 8-bit color attachments. Native assets must retain their source color
mode or reject incompatible raster import explicitly; no silent cross-mode paint
reinterpretation is allowed.

MikkTSpace qualification uses the installed external Blender adapter in background
factory mode, with original custom corner normals and UVs. Per-corner tangent/sign
results may require vertex splitting. B = sign * cross(N,T), OpenGL tangent normal
Y is positive, and DirectX export flips green exactly once. Legacy tangents remain
unchanged unless an explicit new-project tangent choice is made. The named target
is installed Blender 5.1.2. Reference checks must distinguish unlit color/data/
tangent agreement from full PBR lighting equivalence; the latter is not inferred.

Qualification on Windows/RTX 4050 uses OpenColorIO 2.6.0 (optional
`requirements-managed.txt`) and Blender 5.1.2. `STRATA_BLENDER` selects the
external executable. No other platform or Blender version was qualified locally.
Eight CPU/GPU scenarios pass: swatches, linear blending, HDR emission 0–4,
unchanged data, delivery encoding, interpretation undo, portable v6 reopen,
native asset profile rejection and missing optional runtime. Seven actual UI
assertions pass creation, Mikk selection, image controls, undo, reopen and export.
Native asset profiles are retained; conflicting image interpretations reject
before insertion. Resource thumbnails also receive the display transform.

The mirrored two-panel reference compares Strata color/world-normal diagnostics
against actual Cycles renders: Standard/sRGB, gamma 1, exposure 0, one sample,
orthographic 256×128. Interior patches exclude antialiasing boundaries. Maximum
errors: tangents 0.0, encoded world normals 0.002206, encoded color 0.004902.
Acceptance limits are 0.003 and 2/255. The normal attachment and target color
image are quantized. Full PBR lighting equivalence is excluded. Evidence:
`.artifacts/color-t11-final/reference-results.json`.

The milestone regression passes 27 transaction, 13 persistence and 21 export
checks. Frozen v2 and portable v3 retain all 16 maps. Feature suite: 101/102,
only the known low-flow failure. Managed projects require v6; ordinary legacy
v3/v4/v5 formats are unchanged.
