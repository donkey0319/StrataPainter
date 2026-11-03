# Editable paths, ribbons, text and placement (T17)

T17 stores authored objects on ordinary fill-material layers. Their coverage is
evaluated at the current texture-set resolution; material values, seven bitmap slots,
effects, blending, masks and projection remain editable. The objects are not flattened
into paint pixels. The original one-shot `paint_path` helper remains available.

## Desktop workflow

Open Layer > Paths, ribbons and text (also searchable in the command palette).
Choose New path, New ribbon or New region, click surface points in the UV or 3D view,
and Create object. Points belong to the active material. UV clicks reject ambiguous
overlapping surfaces; 3D selection supplies the specific triangle. Orange UV markers
and connecting segments show the current control points. Move point picks its next
surface location. Path/ribbon width and per-point width/pressure profiles are editable;
ordinary property undo restores them. New objects use the brush's current base color.

Paths evaluate a deterministic sequence of sampled dabs along a UV polyline, with
interpolated radius profiles and an optional image/built-in tip. Ribbons use the same
surface anchors and a continuous longitudinal UV coordinate (UV arc length / repeat)
plus a normalized across-width coordinate. Their bitmap materials remain ordinary
layer maps. End/join coverage is rounded; complex junction UV stitching is not claimed.
Regions fill a closed simple UV polygon. Holes and polygon boolean operations are not
implemented. The native editable path is a polyline; the original one-shot helper
retains its smooth-curve/native-brush behavior.

Choose a TrueType/OpenType font, enter New label text and create a text label.
Edit Label text, origin, normalized em size, tracking, line leading and alignment after
reopening. Fonts are portable resources, not an OS font-name substitution. Font glyphs
are regenerated at the new resolution; the output matches direct evaluation at that
resolution. Missing/invalid fonts report an error, retain the editable label and allow
relinking instead of silently substituting another face. Resource relink has undo/redo.
Preview resource errors keep the desktop responsive; export propagates the error.
Complex-script typography and arbitrary collection-face selection are unqualified;
local qualification uses the available Arial TrueType font.

The shared Fill projection controls now include Warp and decal clipping. Choose one
of four destination corners, edit numeric coordinates or drag in the viewport. Each
drag is a single transaction; Esc cancels and undo restores the original mapping.
The transform is stored in the projection, independently of the current camera.
UV and planar modes support text/decal placement; their UI offers only those modes.
Material maps and parameters remain live after placement.

## Surface and tile contracts

Surface control points store a triangle index and barycentric coordinates, not a
screen-space position. Widths/em size/origin use UV units. A path stores a fingerprint
of indexed topology, UVs and triangle-material assignments. Geometry deformations with
that identity preserved retain the anchors. Changed UVs/topology/material assignments
reject mesh revision before publication and report the unsupported case. Labels are UV/
planar placements; they do not promise automatic reprojection after a UV-layout change.

Paths are restricted to connected indexed UV charts. Seams/disconnected charts require
separate paths; this is not a general geodesic path solver. Point selection and archive
validation enforce material ownership. Surface paths cannot be shared into a material
that does not own their anchors; generic text/material data can still be shared.

Native tile evaluation uses global UV coordinates for object coverage. Ribbons spanning
a tile boundary and labels spanning adjacent tiles are qualified. Portable tile reopen
and authored resolution changes preserve editable data; explicit decal clipping crops
outside its projected unit square. General cross-tile filter neighborhoods retain T14's
limits. Ribbon UVs and stored projection transforms are camera-independent.

## API and storage

- `add_authored_path(points, kind='path', width=.04, name=None)` accepts UV pairs or
  explicit surface anchors. Kind is path, ribbon or region.
- `set_path_point(index, uv=None, layer=None, width=..., pressure=...)` edits an anchor
  or profile. `set_authored(layer=None, **changes)` edits detached object parameters.
- `add_text(text, font, name=None)` validates a font before inserting a label layer.
- `set_projection(layer, warp=corners, decal=True, ...)` uses the existing projection
  transaction boundary. `warp=None` restores the ordinary affine mapping.

`Layer.authored` is optional version-1 object data. Paths include surface identity,
anchors, width, spacing, repeat, closure and optional tip resource. Text includes font,
Unicode text, origin, size, tracking, leading and alignment. Font/tip references use
normal portable resource records. Projection warp is a validated projective homography
from four destination UV corners to the source unit square; the quad must be convex,
counterclockwise, finite and well-conditioned, with corner coordinates within -32..32.
Decal clipping is explicit. Default absent warp/clipping fields preserve legacy output.

Objects allow at most 64 control points and text allows 2048 characters. Coverage has
a 128 MiB per-evaluation limit and font atlases a separate 16 MiB limit; budget failures
are explicit. Compositor/tile ownership releases temporary textures and framebuffers.
Text hinting and antialiasing are evaluated at the target resolution. No Adobe pixel-
identity or arbitrary surface-reparameterization claim is made.

Authored objects, warp or decal settings activate project v12 only when used. Ordinary
independent-mask projects without journals remain v4; ordinary tiles v9, advanced bakes
v10 and procedural/import data v11 remain unchanged when no T17 data is present.

## Qualification

- `tests/authored_check.py --gpu .artifacts/authored-t17-final`: 14 scenarios (four
  CPU contracts and ten GPU scenarios). Includes anchor/profile/schema validation,
  region/overlap rejection, exact projective corner mapping, path/label edits after
  portable reopen and resize, direct-resolution text reference equality, camera-stable
  ribbon UVs, tile boundaries, explicit clipping, font loss/relink/undo, mask bypass,
  supported/rejected mesh revisions and the existing one-shot helper.
- `tests/authored_ui_check.py .artifacts/authored-ui-t17-final`: 12 actual desktop
  assertions for point capture/movement/undo, font selection, editable portable text,
  shared warp gesture/undo, decal controls and resolution regeneration. Screenshots
  visually reviewed; widget coordinates account for native pixel rounding.
- The final regression and focused repair results are in IMPLEMENTATION_STATUS.md.
  Native references and screenshots remain under `.artifacts/authored*-t17-*`.

Qualification is local Windows/RTX 4050 and small reference layouts. Arbitrary topology/
UV reprojection, automatic seam traversal, spline/geodesic editing, region holes, complex
script shaping, production-scale object stacks and other GPU platforms remain unqualified.
