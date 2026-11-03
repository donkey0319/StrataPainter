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
