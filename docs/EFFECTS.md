# Effects, anchors and independent mask paint

Select a layer and expand **Content effects** or **Mask effects** in Properties.
Choose a type and click **Add**. Select an effect row to edit its name, settings,
blend and opacity. The row checkbox bypasses the effect; Up/Down reorder it,
Copy makes an independent copy, and Delete removes it. These actions support undo.
Rows evaluate top to bottom. Content effects transform layer values; mask effects
evaluate after the base painted mask and legacy generator, before geometry masking.

Editors cover content HSL, levels, invert, blur, brightness/contrast and anchors;
mask fill/bitmap/projection, generator, levels, invert, blur, ID color selection,
anchor reference, mesh maps, threshold and independent paint. Blend and opacity
apply to transforms as well as sources. Content blend affects only the selected
channels. An anchor definition has no blend or opacity control because it captures
output rather than transforming it.

## Height-to-mask workflow

1. Paint Height on a paint layer, or create a height fill.
2. Add a content **anchor** to that source layer and name it.
3. On a later layer, add a mask **anchor**, choose the source and Height channel.
4. Add filters and a mask **paint** row. Move paint between filters as needed.
5. Select **Paint this effect** and paint in the 3D viewport. The brush's white/black
   value and eraser operate on this effect's own pixels. Clear black/Fill white are
   undoable. **Paint base mask** returns targeting to the legacy layer mask.

Content anchors retain the established meaning: accumulated material output after
the complete source layer, including its mask and content effects. Their position
among content rows does not change capture timing. Mask references store persistent
effect IDs, so names can change without retargeting. Missing, ambiguous, forward or
cyclic dependencies display diagnostics; unavailable sources sample black and never
reuse an earlier frame's capture. RGB source channels use luminance for masks.

Each paint effect owns a separate UV-space scalar texture. Filters before and after
it remain separate, editable operations. Strokes have their own undo snapshots;
copying duplicates pixels and identities, while shared layer instances intentionally
share the definition and paint. Incompatible cross-resolution raster sharing is
rejected; independent copies are resampled to the destination resolution.

## ID and geometry selection

The **color_select** editor supports up to eight ID colors, tolerance and hardness.
Click **Pick ID in viewport**, then click the 3D model to sample its baked ID map.
Escape cancels picking. Picking the baked ID does not sample the shaded material.

**Geometry mask** shows mesh-part checkboxes and **Show all geometry**. Restrictions
support undo and save/reopen. The current lookup supports part IDs 0–1023; meshes
exceeding that limit show an explanation instead of ineffective checkboxes.

## Storage and compatibility

Native projects containing independent mask paint save as schema **version 4**.
The reader verifies required effect-pixel arrays and dimensions before replacing
the open project. Older builds that support only v3 reject these projects. Projects
without the new paint effects continue to save as v3; v1/v2/v3 remain readable.
Portable save, backups and recovery retain the same behavior. Native smart materials
and smart masks also retain independent paint pixels; use the current build for
these new assets. Paint-target selection is session state and can be selected again
after reopening.

Validation: `tests/effects_check.py --gpu OUT` covers ordering, independent strokes,
undo, copies, archives, libraries and storage ownership. `tests/effects_ui_check.py OUT`
exercises all editors, real controls and viewport picking. Qualification results
and remaining work are recorded in IMPLEMENTATION_STATUS.md.

## Linked wear and painted chip relief

Add a **mask_anchor** row in Mask effects after the painted mask you want to
publish. Enter its name in **Mask anchor**. The row captures the scalar mask at
that position. Filters after it can change the source layer's coverage while
upper layers keep reading the earlier capture. On each upper layer, add an
**anchor** mask effect and choose that definition in **Anchor source**. Source
channel selection applies to content anchors. A mask anchor always returns its
scalar capture. References use persistent IDs and support renaming, copies,
undo and portable reopen.

The capture precedes the layer's geometry restriction and authored-object
coverage. Disabled masks, rows and layers produce no capture. References require
a source on an earlier evaluated layer in the same texture set. Missing,
forward and cyclic sources retain the existing black fallback and diagnostics.
Existing content anchors continue to capture accumulated material output.

Add **bevel** after a mask reference to turn its binary boundary into a smooth
distance ramp. **Bevel radius** is 0–32 texture pixels, with zero preserving the
input. Put this mask on a Height-only fill to create chip relief, and reuse the
original capture for the primer and paint coverage. Blend, opacity and bypass
apply to the filter. The native implementation samples eight directions around
the thresholded mask and smooths the signed distance. Fine corners are an
approximation and the operation does not claim Adobe Bevel Smooth pixel parity.

For wear around stamped normal details, add a content **anchor** to the lower
normal-detail layer. Add a **generator** mask effect above it, enable
**Use normal anchor**, choose the content anchor and edit **Micro normal
strength**. The generator adds the local divergence of the encoded tangent
normal vectors to baked curvature before evaluating its ordinary controls.
Edge Wear, Dirt and Cavity consume this curvature. Other generator types retain
their existing inputs. A missing or disabled normal source contributes no added
curvature. A mask capture cannot serve as a vector normal source.

Mask anchors, bevel filters and active micro-normal generator inputs require
project **v15**. Older projects retain their existing version selection. These
filters operate in the active texture tile, with texture-pixel radius and local
normal differences. Cross-tile and UV-seam neighborhoods are not stitched.

Local qualification is recorded in IMPLEMENTATION_STATUS.md. The complete
material workflow and existing feature mappings are in
[the helmet tutorial reference](HELMET_TEXTURING_TUTORIAL.md).
