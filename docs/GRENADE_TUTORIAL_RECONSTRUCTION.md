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

## Save/edit replay follow-up

Repeated the full native authoring workflow in `.artifacts/grenade-save-replay/`
and passed all 20 assertions, including 2K portable save/reopen and body export.
The original user project was preserved. Its existing archive also passed
preflight and retained the delivered layer definitions.

`tests/grenade_save_check.py` exercised the actual desktop save controller after
material, path-point/spacing and independent mask-paint edits. All 15 assertions
pass for Save As, ordinary Save, backup creation, portable resave, Unicode/spaced
Save As, moved-file reopen and archive preflight. Color, material and normal
outputs remain exactly equal across those round trips. Results and the reviewed
desktop screenshot stay under `.artifacts/grenade-save-check/`.

A separate reproducible save-related crash was found in status logging: a Windows
cp950 console cannot print a confirmation containing an emoji filename. The
archive write could succeed and then the uncaught `UnicodeEncodeError` from
`App.msg` could terminate the desktop loop. Console logging now escapes only
unencodable console characters and tolerates closed/broken output; UI status and
the in-app log retain the complete Unicode path. This does not change archive
serialization. The local `tests/grenade_unicode_save_ui_check.py` covers an actual
2K desktop Save As/reopen with a non-codepage filename.

Final focused regressions pass 13 persistence CPU/GPU cases, seven project
protection/controller cases and two console-output cases. No archive corruption
was reproduced in this follow-up. Large-project saves remain synchronous: the
measured ordinary/portable/Save As operations took 37.3–38.7 seconds for roughly
95 MB files on this host. Save responsiveness is a remaining limitation; the
console repair does not claim to eliminate that pause.

## Save responsiveness repair

The subsequent freeze report identified the synchronous archive work above as
the remaining issue. Desktop Save/Save As/portable saves and recovery now capture
owned CPU data on the graphics thread, then compress/write/verify on one worker.
The editor shows the real archive stage and elapsed time while rendering; editing
and project replacement wait. Save-and-close/quit/continue execute only after
verified publication. Failed writes retain dirty state and the previous archive.
The synchronous engine API and archive format are preserved.

`tests/responsive_save_check.py` passed 16 actual-desktop assertions on the 2K
grenade. Capture took 3.57 seconds; manual save rendered 666 frames over 66.72
seconds and recovery rendered 667 over 66.44 seconds. Reopened Color, material and
Normal pixels matched exactly. Injected write failure preserved the previous
file's SHA256, retained dirty edits and suppressed the success continuation.
Acknowledging the real failure dialog allowed a subsequent valid recovery save.
Evidence, progress screenshot and the validated project are local under
`.artifacts/responsive-save/` with the complete run log at
`.artifacts/responsive-save-run.log`.

Final regressions pass 13 persistence CPU/GPU cases, seven project-controller
cases, one snapshot ownership/newer-edit case, two logging cases and the actual
desktop unsaved/replacement/quit flow with zero failures. No tests or evidence
are committed. Snapshot capture still pauses briefly, and rendering competes with
compression, so total save time can increase; the archive phase remains responsive.
The known low-flow baseline is unchanged and was not rerun for this save repair.
