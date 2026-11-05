# Grenade tutorial reconstruction

This exercise follows Cryptic Visionary's
[A Beginners Guide to Substance Painter](https://www.youtube.com/watch?v=uxxliJba8m0)
using StrataPainter. The owner authorized constructing a replacement mesh because
the source FBX was unavailable. Geometry, UVs, bell artwork and procedural settings
are original approximations; this is not an exact copy of the artist's asset.

## Local deliverables

All generated assets, tests and screenshots remain ignored under
`.artifacts/tutorial-grenade/` and `tests/`:

- `grenade_reconstruction.fbx`: imported and tested FBX; 90,768 triangles, five
  material sets, connected cylindrical body UVs and a separate band chart.
- `grenade_source.blend`: editable original geometry.
- `grenade_tutorial.strata`: portable v16 project, 2048px body and four 512px
  hardware sets; includes the original bell alpha and painted mask pixels.
- `textures/`: seven body-only Arnold maps, including OpenGL Normal and actual
  32-bit FLOAT EXR Height. Other material sets are intentionally not exported.
- `grenade-front.png`, `grenade-three-quarter.png`, `desktop-final.png`:
  native engine and actual desktop references.
- `qualification.json`, `desktop-final.json`: local results.

Open the `.strata` file through File > Open. Its stack separates cast steel,
olive paint, Height-only cast distress with Levels, cavity dirt, painted dirt,
polygon-filled red band, editable bell relief and independent gold shading.
The gold mask references **Bell detail coverage** with **Final authored coverage**.
The hidden **09 - Gold bells - independent mask copy** layer is a static comparison;
enable it while hiding the live gold layer to inspect the distinction.

The replay uses native engine authoring operations and a separately inspected
desktop reopen. It is not a recording of every tutorial mouse gesture. The static
mask was copied into independently owned project pixels; this does not implement
the still-deferred mask clipboard UI. Path spacing retains its existing segment
contract. Native position-driven noise and AO dirt approximate the source look.

## Reproduction and qualification

`examples/grenade_mesh.py` generates the original FBX with the existing Blender
installation, without downloading assets or adding dependencies:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background --factory-startup --python examples/grenade_mesh.py -- .artifacts/tutorial-grenade
.\.venv\Scripts\python.exe tests/grenade_reconstruction_check.py .artifacts/tutorial-grenade --size 2048
```

The scene replay/check script remains local, following repository test policy.
Twenty native GPU/workflow assertions pass, plus an actual EXR channel-header
check confirming FLOAT storage. Checks cover brush variation, an actual mirrored
stroke and reversal, band triangle ownership, exact shared scalar coverage,
point-edit undo/redo, live versus static masks, 2K resize, exact portable reopen,
body-only outputs and covered base-color pixels matching within 8-bit precision.
The symmetry test stroke is undone before saving the final appearance.

Desktop first-open verification compares Color, Roughness, Metallic, Height and
Normal buffers against delivered maps. Color and Height agree exactly within
floating-point read precision; the other maps agree within 8-bit quantization.
The screenshot was visually inspected. Qualification is Windows/RTX 4050 only.

## Repairs exposed by the replay

Material thumbnail evaluation previously left shared mesh uniforms configured for
the preview sphere. Recomputing the grenade afterward changed Color by up to
0.086275. Compositors now bind their own mesh uniforms at evaluation boundaries;
the same interleaved evaluation preserves Color and Normal exactly.

The first desktop composite also inherited a UI scissor rectangle when clearing
accumulators. Unwritten Normal-channel regions remained uninitialized, causing a
visible horizontal shading discontinuity. Scissoring is cleared before accumulator
initialization and for full texture passes. First-open Normal now matches the
export within 0.001960, rather than the reproduced 0.855956 discrepancy.

Sphere thumbnails now omit project-mesh authored coverage from cloned descriptions
and show the object's editable material. They no longer try to validate a grenade
surface path against the preview sphere. Object coverage remains visible in the
project viewport/mask preview; the original layer is unchanged.

No project schema or shader formulas change in these repairs. The final focused
regression passes 14 material/projection and 14 authored-object CPU/GPU cases.
Local interleaving/scissor checks preserve the complete normal map exactly.
The known low-flow baseline failure is unchanged; no assertions or references
were weakened, and the broad feature suite was not rerun for this bounded repair.
