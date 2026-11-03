# Fill materials and projections

T05 exposes bitmap maps, projection settings and channel contributions in the
desktop properties panel. The controls reuse the T03 edit transaction and T04
channel descriptor contracts.

## Assemble a material

Select a fill layer and expand **Bitmap maps**. Every channel has a preview,
**Load / Relink**, **Clear**, and an imported-image chooser. Loading validates the
image before changing the document. Dropping image files into the app registers
them in the imported-image list; choose the desired file in each channel slot.
The chooser also includes image references already used by the project. A missing
image remains visible by name and can be replaced without editing project files.

A map overrides its channel's constant value. Assigning a map enables that
channel in the same undoable document edit, including normal, emissive and opacity
channels that begin disabled. The slot's **Enabled** checkbox shows and controls
this state. Clearing a map restores the stored constant and retains the enable
flag. Color and emissive maps use
the existing color resource interpretation; scalar and normal maps use data
interpretation. No managed color conversion is added by these controls.

## Projection

**Fill projection** exposes UV, tri-planar, planar, spherical and cylindrical
mapping, two-dimensional scale and offset, and rotation. Axis controls apply to
planar and cylindrical mapping; tri-planar sharpness applies only to tri-planar
mapping. Inapplicable controls are disabled.

Translate, Rotate and Scale activate direct manipulation of the selected fill's
projection in the viewport. Left-drag edits the projection; release commits one
undo entry. Escape restores the gesture's starting values. **Done** returns to
normal viewport input. Numeric controls and direct manipulation write the same
projection object through engine property transactions. **Reset mapping** restores
the default projection as one undoable action.

## Channel contributions

Expand **Channel blending** under the layer properties. Each channel has an
independent blend override and contribution opacity. **Inherit layer/default**
uses the layer's normal channel behavior. Color-specific modes are offered on
color channels and normal-map modes on the normal channel. A channel's contribution
opacity remains separate from the material opacity value and overall layer
opacity.

## Texture-set resolution

The texture-set settings panel has a resolution chooser and **Apply resolution**.
The change affects the selected set, resamples its paint and rebuilds its mesh
maps. A successful resize clears global undo history because prior GPU snapshots
have incompatible dimensions. The panel states this before applying the change.
Failure retains the existing set and history. Incompatible shared raster storage
is rejected; duplicate the layer into independent storage before resizing it.

Projection settings, maps and channel configuration are saved with the project.
Use portable save to collect referenced bitmaps and normal export templates to
deliver the resulting PBR textures. Qualification results belong in
IMPLEMENTATION_STATUS.md; this document describes the authoring workflow.
