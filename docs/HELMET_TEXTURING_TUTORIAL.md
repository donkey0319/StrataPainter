# Helmet texturing workflow reference for StrataPainter

J Hill textures a sci-fi helmet modeled by Breki Thor in *How to TEXTURE EVERYTHING in Substance Painter*. Use this reference to find the relevant part of the tutorial, identify the Substance 3D Painter (SP) operation, and locate the StrataPainter behavior to reproduce or extend. [Original tutorial](https://www.youtube.com/watch?v=GvjfkhCW3aM) · [Artist's project page](https://www.characterclass.com/helmet)

**Evidence.** Chapter names and start times come from the original upload's description retrieved with Moli 1.1.21. The operation inventory uses the published breakdown linked to that upload. YouTube returned an empty caption response and rejected the transcript request. The video timeline has not been reviewed shot by shot. Rows marked **Chapter** identify an artist-authored chapter and give an implementation mapping to verify during playback. Rows marked **Reported** describe corroborated operations, with chapter links serving as navigation rather than exact action timecodes. Tool names, parameter values and click sequences beyond the cited evidence require playback verification. [CGWORLD breakdown](https://cgworld.jp/flashnews/01-202604-SP-Texturing.html)

## Workflow and feature mapping

| Chapter start | Evidence | Artist operation or chapter topic | Substance 3D Painter functionality | StrataPainter entry point or verification target |
| --- | --- | --- | --- | --- |
| [00:00](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=0s) | Chapter | Introduce the helmet project. | Project and viewport context. | Use a representative multi-part mesh with separable shell, trim, wires and visor. Project creation and mesh maps are covered in [Bake and display](BAKE_DISPLAY_LIBRARY.md). |
| [02:07](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=127s) | Chapter | Establish material references. | Reference gathering is an art task. Use the material and individual channel views to compare surfaces while authoring. | Compare shaded and isolated channels in the 3D and 2D views. [UV painting](UV_PAINTING.md) |
| [07:03](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=423s) | Reported | Organize material regions into folders and give each region a base fill. Set folder blending to Pass Through and manage Base Color and Roughness independently. | Layer stack folders, fill layers, per-channel blending and channel enables. | Start with groups and fill materials. Use geometry or ID masks where the fixture supplies appropriate selections. Verify folder compositing against SP when children touch different channels and a lower layer contributes to the result. [Fill materials](FILL_MATERIALS.md) · [Effects and geometry selection](EFFECTS.md) |
| [16:24](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=984s) | Chapter | Develop the metal material. | Map to Base Color, Metallic and Roughness fills, with independent channel variation. A curvature or AO mask is a candidate for localized wear. | Use channel-scoped fills and mask effects. Verify roughness-only edits leave Metallic unchanged and respect region coverage. [Channels](CHANNELS.md) · [Effects](EFFECTS.md) |
| [31:10](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=1870s) | Chapter | Develop the plastic material. | Map to a dielectric fill, roughness variation and optional microtexture in Height or Normal. | Combine a base fill and bitmap or procedural detail. Verify detail scale and that its channels remain independent. [Fill materials](FILL_MATERIALS.md) · [Procedural imports](PROCEDURAL_IMPORTS.md) |
| [40:38](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=2438s) | Reported | Paint a source mask low in the stack and expose it with an anchor. Reuse it in upper masks to coordinate exposed primer and edge wear. Apply Bevel Smooth to shape the chip relief. | Paint effect on a mask, Anchor Point, upper mask references and Bevel Smooth effect. | Independent mask paint and ordered effects are documented. Verify a true mask capture, rather than assuming an accumulated content anchor captures an arbitrary mask row. Verify a bevel-specific filter separately from simple blur or levels. [Effects](EFFECTS.md) · [Procedural imports](PROCEDURAL_IMPORTS.md) |
| [1:13:47](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=4427s) | Chapter | Develop the metal coating. | Map to a coating layer with its own channel values and coverage. Confirm the actual layer stack and whether the artist uses a dedicated shader channel. | Test masked fill layering first. StrataPainter also has a clearcoat shader workflow if playback establishes that it is needed. [Shader workflows](SHADER_WORKFLOWS.md) |
| [1:22:12](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=4932s) | Chapter | Develop the leather material. | Map to a dielectric base, texture-driven roughness and grain through Height or Normal. Confirm the exact material assets and effects during playback. | Use projected bitmap or native procedural fills. Inspect grain scale, seams and the ability to edit color independently. [Fill materials](FILL_MATERIALS.md) · [Procedural imports](PROCEDURAL_IMPORTS.md) |
| [1:39:38](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=5978s) | Reported | Stamp screw recesses and panel details into a low Normal layer. Publish the authored detail through an anchor so later smart masks can respond with wear or dirt. | Normal-channel stamping, Anchor Point, smart mask or generator input for micro-normal detail. | Use a Normal-enabled brush or projection for stamping. Verify whether the target generator can consume a vector normal reference. The documented anchor-to-mask effect reduces RGB sources to luminance, which cannot substitute for a directional normal input. [Brushes](BRUSHES.md) · [Effects](EFFECTS.md) |
| [2:04:49](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=7489s) | Reported | Project image decals, tune the sticker edge thickness and wear the sticker so underlying material shows through. | Image/decal projection, local Height and editable coverage or damage masking. | Start with planar or UV fill projection, explicit decal clipping, warp, and ordered mask effects. Verify the edge height disappears with the corresponding damaged coverage and that the placement survives a camera move and reopen. [Authored objects](AUTHORED_OBJECTS.md) · [Effects](EFFECTS.md) |
| [2:23:20](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=8600s) | Chapter | Add overlays. | Map to upper fill or paint layers with mask, channel blend and opacity controls. Confirm the specific overlays during playback. | Check that an overlay can alter Roughness alone or combine multiple channels while retaining lower material differences. [Channels](CHANNELS.md) · [Effects](EFFECTS.md) |
| [2:49:49](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=10189s) | Chapter | Author emissive regions. | Map to the Emissive channel and localized paint or fill coverage. | Compare the Emissive channel, shaded preview and exported texture. Record preview effects such as bloom separately if observed during playback. [Channels](CHANNELS.md) · [Bake and display](BAKE_DISPLAY_LIBRARY.md) |
| [2:53:35](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=10415s) | Reported | Import an external font and place editable lettering along a curved cable surface. Adjust the lettering after placement. | Font resource import and non-destructive text projection. | Use portable text objects and UV or planar projection with warp. Surface ribbons and text are documented separately. Verify whether the cable placement can be reproduced with UVs or warp before treating it as a text-on-path requirement. [Authored objects](AUTHORED_OBJECTS.md) |
| [3:01:22](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=10882s) | Chapter | Author glass. | Map to shader selection, opacity, tint and roughness. Check playback for the actual shader and whether it uses transmission. | Test Opacity and preview behavior first. Qualify any transmission or refraction requirement separately from alpha blending. [Channels](CHANNELS.md) · [Shader workflows](SHADER_WORKFLOWS.md) |
| [3:08:13](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=11293s) | Reported | Inspect dark albedo with PBR Validate, set Albedo Dark Range Threshold to 50 sRGB for this project, and adjust dark material values. | PBR Validate filter and Base Color editing. Adobe specifies disabling the filter for export. | Treat this as a diagnostic workflow to verify. An isolated Base Color view helps inspect values, while a parity check needs a threshold overlay with explicit sRGB interpretation that never contaminates delivered maps. [Adobe PBR Validate](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/filters/advanced-filters/pbr-validate) · [Color pipeline](architecture/COLOR.md) |
| [3:08:13](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=11293s) | Reported | Export packed occlusion, roughness and metallic maps for Unreal Engine using a custom template. | File → Export Textures and Output Templates with individual component assignments. | Use Unreal Engine Packed or edit a custom template. Verify R = AO, G = Roughness and B = Metallic with distinct sample values, then compare the manifest preview to the actual files. [Adobe Export](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/export/export) · [StrataPainter export](EXPORT.md) |
| [3:18:25](https://www.youtube.com/watch?v=GvjfkhCW3aM&t=11905s) | Chapter | Review the finished helmet. | Final appearance review. | Compare representative materials and isolated maps in the authored project and the target renderer. [Delivery](DELIVERY.md) |

## Acceptance scenarios for implementation work

1. **Linked paint chips.** Paint one mark into a source mask. Check that primer and rim consumers both update immediately while each keeps its own shaping and material controls. Repeat after undo, rename and portable reopen. Check that moving a source above its consumer produces a diagnostic without stale pixels. Adobe restricts anchor references to sources below the consumer in the same Texture Set. [Adobe Anchor Point](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/anchor-point) · [Transactions](TRANSACTIONS.md)
2. **Wear that follows a stamped normal.** Stamp one recess over unchanged bake maps. Compare the generator with the stamp enabled and disabled. The local response should follow authored detail and the rest of the bake-driven result should stay stable. Verify the normal channel and mask independently so a shaded resemblance does not pass as evidence of a live dependency. [Adobe Normal Map Painting](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/advanced-channel-painting/normal-map-painting) · [Adobe Curvature generator](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/curvature)
3. **Editable sticker and wire lettering.** Change decal placement and letter content after saving, reopening and changing texture resolution. Check clipping, wear revealing the base surface, portable font loading and coverage on a curved mesh. Inspect from two camera angles. [Authored objects](AUTHORED_OBJECTS.md)
4. **Diagnostic and packed export.** Use known Base Color samples just below and above the selected threshold and independent AO, Roughness and Metallic values. Compare isolated channel pixels and the packed file. Verify the diagnostic never changes the exported Base Color, and that the destination interprets the packed components as data. [Export](EXPORT.md) · [Color pipeline](architecture/COLOR.md)

Before changing an operation, review its existing implementation contract in the linked feature document and consult the [implementation status](IMPLEMENTATION_STATUS.md) and [implementation plan](STRATA_PAINTER_IMPLEMENTATION_PLAN.md). Use this inventory to define workflow acceptance, and use those documents to determine what has already been qualified.

## Replicating the workflow in StrataPainter

The following procedure uses StrataPainter's current controls. The source inventory
above retains its evidence labels. This procedure provides native equivalents for
the corroborated operations, with shader and filter limits stated below.

1. Create or open the helmet mesh. Bake its mesh maps through Texture Set
   Settings. Use folders for shell, hardware, plastic, coating, leather, wires
   and visor. Add a fill inside each folder and restrict coverage with geometry,
   ID or painted masks. Ordinary unmodified folders pass their children through
   the existing accumulated stack. Set channel-specific blend and opacity in
   the layer properties. [Bake controls](BAKE_DISPLAY_LIBRARY.md) · [Fill materials](FILL_MATERIALS.md)
2. Set each base material's Base Color, Roughness and Metallic values. Assign
   bitmap channel maps or native procedural content for grain and variations.
   Choose UV or triplanar mapping and adjust scale, rotation and offset. Keep
   roughness and height detail on independently enabled layers for later edits.
   Use native generators and ordered mask effects for localized wear.
   [Fill materials](FILL_MATERIALS.md) · [Procedural content](PROCEDURAL_IMPORTS.md)
3. For linked paint chips, select the source layer and add **paint** in
   **Mask effects**. Click **Paint this effect** and paint the chip coverage.
   Add **mask_anchor** after the paint row and give **Mask anchor** a name.
   Add an **anchor** mask effect to an upper primer fill and select that name
   in **Anchor source**. Repeat for other consumers. Add **invert**, **levels**
   or **bevel** after the reference to shape each consumer independently.
   A Height-only fill with the bevel mask supplies the relief. Effect rows
   evaluate in the Properties list's numbered order. [Effects](EFFECTS.md)
4. Stamp the hardware and panel details on a Normal-enabled paint layer using
   a brush map or projection. Add a content **anchor** to that lower layer.
   On the upper wear layer add a **generator** mask effect, choose Edge Wear,
   Dirt or Cavity, enable **Use normal anchor**, and choose the normal-detail
   anchor. Tune **Micro normal strength** with the normal layer enabled and
   disabled to check the response. [Brushes](BRUSHES.md) · [Effects](EFFECTS.md)
5. Assign the decal image to a fill, select UV or planar projection, enable
   decal clipping and adjust transform or Warp. Add mask paint and filters
   for damage. Use the coverage on a Height fill for the sticker thickness.
   Move the camera to check that the stored placement stays attached.
   [Decal placement](AUTHORED_OBJECTS.md)
6. Add overlays with channel enables, mask blending and layer opacity.
   Enable Emissive on the light elements and inspect the Emissive display.
   For wire labels, open **Layer > Paths, ribbons and text**, choose a font,
   enter the label and edit its UV placement or planar warp over the cable.
   This provides editable surface lettering. Text objects use UV or planar
   placement, so cable UV layout determines how the letters follow the surface.
   [Channels](CHANNELS.md) · [Text](AUTHORED_OBJECTS.md)
7. Use an Opacity-enabled fill with Base Color and Roughness for a transparent
   visor and export its opacity. The existing preview supports alpha blending
   and alpha testing. Optical refraction and a dedicated glass transmission
   shader remain outside the qualified preview. Validate that appearance in
   the destination renderer. [Shader workflows](SHADER_WORKFLOWS.md) · [Delivery](DELIVERY.md)
8. Choose **Albedo validation** in the viewport Display list. In Display
   Settings, set **Albedo threshold** to 50. Magenta marks Base Color pixels
   whose largest encoded sRGB component is below 50/255. Adjust the material
   and compare both the 3D and UV views. Managed linear Rec.709 colors are
   converted to encoded sRGB before this check. Threshold is session inspection
   state. This checks dark albedo, with no metal-reflectance-range diagnostic.
   It applies only during display and leaves exported material pixels intact.
9. Open **Export Textures**, choose **Unreal Engine Packed** or edit the
   template to assign AO to R, Roughness to G and Metallic to B. Review the
   selected texture sets, names, size and format before exporting. Save a
   portable project to retain editable paint, font and image resources.
   [Export](EXPORT.md) · [Persistence](PERSISTENCE.md)

The native bevel and micro-normal curvature operations approximate the corresponding
SP effects. Their texture-pixel neighborhoods do not stitch across UV seams or
tile boundaries. The new linked wear features require v15 projects. Exact
commercial material assets, hidden values and the artist's complete cursor
sequence remain unverified.
