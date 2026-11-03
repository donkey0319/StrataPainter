# Substance 3D Painter user workflow complaints

Research and review brief for agents  
Research date: November 2, 2026  
Product: Adobe Substance 3D Painter  
Latest release checked: 12.2.0, released October 21, 2026 [S01]

## Purpose and main findings

This document organizes public user complaints into 38 reviewable findings covering controls, UI, layers, assets, geometry, baking, export, performance, and reliability. It gives reviewing agents evidence, qualifications, and concrete investigation tasks.

The strongest themes in this sample concern diagnosing complex layer stacks, preserving work through mesh revisions, managing texture-set boundaries, and trusting save/export operations. Smaller interaction costs include repeated menu navigation, confusing editing states, and asset browsing that takes artists away from the viewport. These themes are a synthesis of the linked reports, not measured rankings of the entire user population.

Several prominent historical complaints have since received features or fixes. Reviewers should use the version corrections below before turning any complaint into a requirement. In particular, an old request is evidence of a user need, not proof of a missing feature today.

## Scope and evidence rules

- This is a qualitative public-source review, not a survey of all users or an exhaustive collection of every complaint. The sample spans reports from 2021 through 2026, with some older cross-application context.
- Sources are firsthand posts on Adobe Community, Reddit, and Steam, supplemented by Adobe documentation and release notes. Search focused on explicit frustrations, feature requests, and interrupted production workflows.
- Posts, replies, and votes are self-selected. They establish that someone encountered a problem; they do not establish its prevalence. Several comments in one discussion are not several independent studies.
- All complaint summaries are paraphrases. Review tasks and design implications are this document's analysis, not promises from Adobe or statements attributed to users.
- No Painter installation was exercised for this research. A current documentation check is different from a successful reproduction on 12.2.0.
- Dates below use explicit post/release dates where available. Relative forum labels can be inconsistent; a source marked “date not extracted” should be opened before making chronological claims.
- This brief does not assess Strata's implementation or claim that Strata already solves these problems.

### Reading the status labels

| Label | Meaning |
| --- | --- |
| Reported | A user describes the problem; current reproduction remains necessary. |
| Repeated | More than one user/report supports the theme in this sample. This is not a population frequency estimate. |
| Acknowledged | An Adobe representative discusses the need or limitation. This does not guarantee delivery. |
| Workaround | A documented or staff-suggested alternative exists; assess its interaction cost. |
| Historical | The complaint is old and has not been validated against the current release. |
| Addressed | A relevant shipped feature or fix is documented. Exact edge-case coverage still needs testing. |

## Controls and painting interactions

### CTL01 Frequent operations require menu travel

**Evidence and status:** Reported and acknowledged. A May 28, 2025 request names layer creation and black-mask creation as repetitive menu operations; Adobe agreed shortcuts deserved further work. Painter does support editable shortcuts, so the issue is command coverage and discoverability rather than a complete absence of customization. [S02] [S03]

**Review task:** Time a repeated create-layer, add-mask, fill, and rename sequence. Record which commands can be bound, which have defaults, and whether bindings remain available with different panel focus. Consider searchable commands and visible shortcut hints.

### CTL02 Brush size changes feel coarse

**Evidence and status:** Historical. A user reports irregular wheel increments and difficulty reaching tiny brush sizes. [S04]

**Review task:** Compare wheel, numeric entry, pen, and modifier controls across small and large mesh scales. Test whether displayed units explain the result and precision adjustments remain predictable.

### CTL03 Numeric and color copying takes extra focus changes

**Evidence and status:** Historical. A user requests hover-based copying and pasting of values and colors. [S04]

**Review task:** Count clicks when matching values across several effects. Evaluate consistent copy/paste, reset, units, and multi-selection behavior; do not assume hover copying is the only suitable solution.

### CTL04 Navigation conventions conflict with other applications

**Evidence and status:** Repeated cross-application context. Artists discuss switching camera schemes among Blender, Maya, ZBrush, and Painter. One user reports successfully remapping Painter. Preferences differ; there is no single scheme favored by everyone. [S05] [S06]

**Review task:** Test configurable navigation presets, conflict detection, and pen-friendly orbit/pan/zoom. Preserve painting gestures when remapping navigation. Separate a transfer-of-learning problem from a broken control.

## UI readability and editing state

### UI01 Scaling can make the interface tiny or blurry

**Evidence and status:** Repeated, configuration dependent. A February 2023 report describes a large blurry UI in 8.3.0; a May 2024 Steam comment describes tiny controls on a 4K Windows 11 display and rejects changing scaling for all applications. These are different failure modes. [S07] [S08]

**Review task:** Check readable text, icons, hit targets, and popup sizing at several OS scales and mixed-monitor DPIs. Record OS, resolution, application build, and per-monitor scaling before attributing the cause.

### UI02 A detached saved-search panel does not survive restart

**Evidence and status:** Reported, July 30, 2025. A user distinguishes a lost undocked brush-search tab from other panels that restore correctly; saving the UI layout did not resolve that specific case. [S09]

**Review task:** Create a saved-search tab, detach it to another monitor, save layout, restart, and reload layout. Test disconnected monitors separately. Avoid broadening this report into “all layouts are broken.”

### UI03 Export names remain truncated despite available space

**Evidence and status:** Reported and acknowledged. The December 24, 2025 request says resizing the export window does not expose complete output names. Adobe acknowledged the annoyance in January 2026. [S10]

**Review task:** Use long asset, channel, texture-set, and UDIM names. Verify resizable columns, full-name inspection, copying, and collision detection before export.

### UI04 Properties require excessive scrolling

**Evidence and status:** Reported feature request. The community listing includes a request for a Properties search field to find parameters without scrolling. The listing was inspected; the full thread could not be retrieved. [S11]

**Review task:** Find a named parameter in an unfamiliar generator. Compare search, collapsible sections, recent parameters, and filtering to modified values. Treat this source as a lead with limited context.

### UI05 Users lose track of what is editable

**Evidence and status:** Reported. A user describes a persistent state with greyed controls and a blue geometry overlay after clicking a mask-related control; replies suggest selecting the layer thumbnail. This is evidence of state confusion, not proof that the project was damaged. [S12]

**Review task:** Switch between layer content, masks, geometry masks, effects, and tools. Check whether the active target and reason an action is unavailable are obvious, and whether the user can recover without resetting the workspace.

## Layers masks and procedural logic

### LAY01 Isolating a layer in a large stack is tedious

**Evidence and status:** Repeated and acknowledged. A March 2022 request and later replies describe manually toggling many layers or folders to inspect a contribution. A July 2026 Adobe reply mentions work on a plugin; that reply does not establish a shipped native solution. [S13]

**Review task:** Inspect one layer in a nested material, then restore the exact prior visibility state. Account for masks, anchors, blending, and dependencies: hiding every other layer may change the contribution being diagnosed.

### LAY02 Group creation does not match selection expectations

**Evidence and status:** Historical. A user expects a folder command to wrap selected layers or effects automatically. [S04]

**Review task:** Compare group creation with and without selection, preserving order, masks, and blending. Check that moving items does not silently alter the material.

### LAY03 Moving painted content is less direct than expected

**Evidence and status:** Historical with an existing alternative. Users request transforms for painted layers and folders. Adobe documents a Transform filter for layer or mask scale, rotation, and offset; the categorical claim that transformation is impossible is too broad. [S04] [S14]

**Review task:** Reposition a painted decal and a group across UV seams. Compare filter-based transforms with direct manipulation; distinguish UV-space transforms, projection controls, and 3D surface placement.

### LAY04 Complex procedural logic is hard to read in a linear stack

**Evidence and status:** Reported. A request for nested effects describes difficulty organizing more complex mask logic. Requests for node graphs also appear in the layer-isolation discussion. Neither establishes that replacing the entire layer model is the preferred solution for all users. [S11] [S13]

**Review task:** Trace where a visible wear effect originates. Assess nested organization, dependency inspection, naming, and reusable substructures before choosing a graph or stack redesign.

### LAY05 A filter appears incompatible when projection or masking is the real issue

**Evidence and status:** Workaround. In a May 2026 Drop Shadow request, Adobe explains that fill layers can use the effect, but full-UV coverage leaves no exterior area for the shadow. Staff suggest another projection or an anchor-based construction for mask-driven shadows. [S15]

**Review task:** Test the artist's intended masked silhouette, not only whether the filter can be added. Evaluate contextual guidance when an effect produces no visible result.

### LAY06 Dropping an alpha creates the wrong stack destination

**Evidence and status:** Reported, June 19, 2026. A user describes dropping an alpha onto the model, receiving a new layer/mask, then copying the effect back into the mask they were already editing. The author explicitly allows that another workflow may exist. [S16]

**Review task:** Reproduce the exact drag target and popup choice. Explore an explicit destination choice for the selected mask while preserving surface placement and undo behavior.

### LAY07 Reusing a path between a layer and mask causes rework

**Evidence and status:** Reported with a workaround. A May 2026 request concerns copying the same path between stack types. Adobe suggests referencing the path result through an anchor; this reuses evaluated output and does not necessarily provide editable path duplication. [S17]

**Review task:** Reuse a curved lace or seam path for material and masking. Compare shared path data, editable copies, and anchor references, including what happens after the original path changes.

## Asset organization and application

### AST01 Personal asset organization feels constrained

**Evidence and status:** Historical. Users request asset folders and editable tags. [S04]

**Review task:** Organize a large mixed library, then locate an asset by project, category, and personal label. Verify current folders, tags, filters, and saved searches before declaring any capability missing.

### AST02 Switching asset scopes adds repeated clicks

**Evidence and status:** Reported. A user requests direct tabs or icons for Project, Starter Assets, and Your Assets instead of repeated dropdown use. [S18]

**Review task:** Count scope switches while assembling a material from bundled and project resources. Assess persistent scope visibility and keyboard access alongside available screen space.

### AST03 Browsing can unexpectedly replace a material

**Evidence and status:** Reported. A community question describes clicking an asset while a material layer is selected and replacing its material while retaining the layer name. The full thread was unavailable; evidence is from the community listing. [S19]

**Review task:** Distinguish preview, select, replace, and create-new gestures. Verify undo and resulting layer labels. Test rapid browsing under load, where feedback may arrive after the next click.

### AST04 Applying an image requires an import and rediscovery step

**Evidence and status:** Reported in the 2026 replies to an older discussion. A user objects to importing an image, finding it, then applying it. [S04]

**Review task:** Follow a file from the OS into a specific fill channel or mask. Assess direct drop, automatic resource classification, scope selection, and duplicate handling.

## Geometry texture sets and revisions

### GEO01 Objects materials and texture sets are easily confused

**Evidence and status:** Reported onboarding difficulty. A user expects separate Blender bodies to become separate texture sets. A community expert explains material assignment and an alternative ID-mask workflow for multiple surface looks within one set. [S20]

**Review task:** Import several objects sharing a material and one object with several materials. Show the mapping before project creation and explain how it affects painting, output files, and isolation.

### GEO02 Shared material edits and cross-set painting are different capabilities

**Evidence and status:** Documented limitation relevant to texture-set workflows. Layer instancing synchronizes parameters across sets, but paint actions apply only on the source set and are discarded by other sets. This is a verified architectural constraint, not a separately counted user survey finding. [S21]

**Review task:** Attempt one continuous painted mark across two material sets. Compare that with sharing a procedural material. Keep texture sets distinct from UDIM tiles; support for painting across tiles does not answer this case.

### GEO03 Mesh revisions can invalidate painted work

**Evidence and status:** Repeated and acknowledged. Reports across 2021–2024 describe displaced strokes after moving, changing, or removing geometry, sometimes with unchanged UVs. Adobe explains the relationship between 3D strokes, cameras, bounding boxes, and reprojection. The preserve-strokes option is useful in some revisions but does not guarantee every revision will preserve paint. [S22] [S23] [S24]

**Review task:** Test unchanged geometry with new UVs, changed geometry with unchanged UVs, whole-object transforms, and removed subobjects separately. Compare 2D and 3D strokes, masks, cloned content, and procedural layers. Evaluate revision preview, recoverability, and explicit preservation choices.

### GEO04 UV set selection needs separate validation from import preservation

**Evidence and status:** Historical. Users request choosing the working UV set. [S04]

**Review task:** Distinguish importing multiple UV sets, selecting the painting UV set, preserving unused UV data, and exporting it. Do not treat these as equivalent capabilities or reuse an old complaint as a current unsupported-format claim.

## Baking symmetry and selection

### BAK01 Local cage adjustments required disproportionate setup

**Evidence and status:** Repeated according to Adobe, now addressed by a relevant feature. A July 2026 request asks for local cage-offset painting rather than global distances or custom cage editing; staff note repeated demand. Painter 12.2.0 subsequently added cage painting. Auto Cage also existed when the request was made. [S25] [S01]

**Review task:** Assess the shipped feature on narrow gaps and intersecting details. Check edit visibility, smoothing, reset, per-set storage, and rebake cost rather than proposing cage painting as wholly absent.

### BAK02 Repeated bake configuration interrupts iteration

**Evidence and status:** Historical. A user objects that a preferred ID-map input does not become the default. [S04]

**Review task:** Test saved baking presets and project templates before considering a new preference. Check which settings persist across assets and which should remain asset specific.

### BAK03 Multi-axis planar symmetry does not match available alternatives

**Evidence and status:** Repeated within a request thread, including a February 2026 follow-up. Users distinguish planar mirroring on several axes from radial symmetry and 2D Mirror effects. Adobe discusses alternatives and acknowledges the distinction. [S26]

**Review task:** Paint a prop requiring two perpendicular planes and unique detail later on each side. Compare live planar symmetry, radial copies, and UV mirroring without treating their results as interchangeable.

### BAK04 Centering symmetry on one component is cumbersome

**Evidence and status:** Reported in a feature-request listing. The request asks to center the plane on the active material's geometry instead of the entire project and describes manually adjusting offsets. Full-thread retrieval failed. [S27]

**Review task:** Use an off-center component in a multi-part asset. Check pivot selection, snapping, numeric offsets, and a clear indication of the symmetry reference frame.

## Export and downstream appearance

### EXP01 Combining separate texture sets into one output is awkward

**Evidence and status:** Repeated and acknowledged. A December 2023 question describes using third-party software to merge outputs; the theme also appears in broader feedback. A single-set ID-mask workflow can avoid some cases but requires planning before texturing. [S28] [S04] [S20]

**Review task:** Separate compositing nonoverlapping UV regions from repacking an atlas. Test overlaps, padding, output resolution, channel packing, and color spaces. Do not confuse layer flattening with merging texture sets.

### EXP02 Export naming requires custom automation

**Evidence and status:** Reported and acknowledged, May 2026. A user requests a texture-resolution token in output names and directory paths and describes maintaining Python logic to route files. [S29]

**Review task:** Export sets with different resolutions into a production directory scheme. Evaluate token coverage, path previews, invalid characters, and saved export configurations.

### EXP03 Per-map resolution control is requested in addition to per-set control

**Evidence and status:** Reported in community feedback. The request distinguishes lower-resolution auxiliary maps from full-resolution base maps. Current export documentation describes global and per-texture-set resolution, plus per-output format and bit-depth overrides; it does not by itself establish arbitrary per-output resolution support. [S30] [S31]

**Review task:** Export base color, roughness, and auxiliary channels at different sizes in one repeatable operation. Verify actual current controls before classifying this as a missing feature.

### EXP04 Materials look different in the destination application

**Evidence and status:** Repeated cross-tool integration difficulty. Reports describe normal-map shading differences in Unity/Blender and differences among Painter, Iray, and Blender. These symptoms do not establish a Painter export defect; destination interpretation and scene settings require inspection. [S32] [S33]

**Review task:** Use a controlled reference scene. Check normal convention, tangent basis, triangulation, channel packing, texture interpretation, shader inputs, lights, and display transforms. Record the cause rather than labeling every mismatch a bug.

### EXP05 Color picking and typed hex values appear inconsistent

**Evidence and status:** Reported with a configuration resolution. In July 2025, a user compares external eyedropper sampling with typed hex values under ACES settings. The user later reports no issues after retaining ACES-sRGB defaults; replies explain that RGB/hex values depend on color space. [S34]

**Review task:** Show source, working, and display spaces when sampling or entering colors. Test identical numeric values separately from identical perceived colors. Avoid presenting the original report as an unresolved universal picker defect.

## Performance saving and production reliability

### REL01 Save failures are too easy to miss

**Evidence and status:** Reported and acknowledged. A July 30, 2026 request reports hours of lost work after overlooking small save-error text and asks for an unmistakable failure notification. A separate October 2024 report describes lost progress after a save error. [S35] [S36]

**Review task:** Simulate denied writes, unavailable destinations, and failed autosaves. Verify that failure is visible, unsaved state remains explicit, and a successful save can be distinguished from merely issuing the command.

### REL02 Low disk space can jeopardize a project

**Evidence and status:** Repeated historical reports with a specific documented fix. A December 2023 report describes corruption on a full drive; Adobe discusses warnings and extreme low-space cases. Release 12.0.2 lists a fix for crashing or corrupting projects when saving with insufficient space. [S37] [S01]

**Review task:** Test current low-space failure behavior using disposable projects and a controlled quota or mock filesystem. Assess previous-file preservation, temporary-file cleanup, warnings, and recovery. Do not advertise the old corruption report as an unfixed current defect.

### REL03 Large projects can make saving or reopening stall

**Evidence and status:** Repeated. A December 2022 report concerns 19–20 GB files freezing on save; a June 2024 report describes a relatively large project failing to open while smaller files open with slow brushes. These reports have different builds and hardware and should remain separate reproductions. [S38] [S39]

**Review task:** Measure save, reopen, memory use, and progress feedback across controlled project sizes. Separate project size, cache location, device speed, and layer complexity. Do not infer a universal file-size limit from these posts.

### REL04 Painting responsiveness degrades with project complexity

**Evidence and status:** Repeated complaints, with a documented computation cost. Adobe explains that modifying a lower layer can require recomputing layers above it and recommends geometry masks or hiding upper layers. That explains one performance mechanism, not every reported slowdown. [S40] [S41] [S39]

**Review task:** Measure input-to-visible-stroke latency and parameter-update time by stack depth, enabled effects, resolution, and UDIM count. Compare top and bottom layers. Distinguish documented cost, a regression, and a driver/resource problem.

### REL05 Updating can block delivery and make rollback difficult

**Evidence and status:** Repeated, version specific, with a relevant fix. March 2026 users report stalled exports after updating and difficulty opening upgraded projects in older versions. Adobe's 12.0.1 notes list a fix for export crashes/freezes from specific projects. A later user reports success on 12.0.2. [S42] [S01]

**Review task:** Validate project conversion, export, plugin compatibility, and recovery on copies before a production upgrade. Treat backward compatibility, regression detection, and export reliability as separate requirements. Do not generalize this incident to every update.

## Historical claims that need correction before reuse

The concise version facts below come from Adobe's release history. “Addressed” means relevant functionality shipped, not that every associated workflow is optimal. [S01]

| Older complaint or claim | Correction for reviewers |
| --- | --- |
| Painter cannot use custom-font text resources | 10.0.0 added embeddable-font text resources. |
| Painter cannot flatten layers | 12.0.0 added layer flattening and flattened export. |
| Painter has no local cage painting | 12.2.0 added cage painting. |
| Painter cannot paint across UDIM tiles | Cross-tile painting shipped in 6.2.0. Distinct texture sets remain a separate question. |
| The specific full-disk corruption report has no fix | 12.0.2 lists a corresponding save fix. |
| The March 2026 export freeze is necessarily current | 12.0.1 lists a corresponding export fix. |

Also avoid saying that all transforms are absent: a Transform filter is documented. Similarly, color-space configuration resolved the cited eyedropper/hex user's immediate problem. [S14] [S34]

## Suggested review order

This is an impact-based triage proposal, not a ranking by user count. A single credible data-loss report can justify investigation before a popular convenience request.

| Priority | Findings | Rationale and useful output |
| --- | --- | --- |
| First | REL01–REL03, REL05, GEO03 | Work loss or blocked delivery. Produce reproducible failure cases and recovery requirements. |
| Next | LAY01, GEO01–GEO02, EXP01, REL04 | Repeated production friction or documented constraints. Produce task measurements and dependency analysis. |
| Then | CTL01, UI01–UI05, AST01–AST04, LAY02–LAY07 | Interaction efficiency and discoverability. Produce annotated workflows, click counts, and error observations. |
| Specialist review | CTL02–CTL04, GEO04, BAK01–BAK04, EXP02–EXP05 | Hardware, painting, bake, and pipeline-specific needs. Produce versioned capability checks and controlled comparisons. |

### Review work packages for other agents

These are suggested assignments; no agents have been dispatched by this document.

1. **Controls and UI review:** CTL and UI findings. Deliver a command-coverage inventory, editing-state map, DPI matrix, and measured artist tasks.
2. **Layers and assets review:** LAY and AST findings. Deliver an inspection/reuse workflow and a library organization study, preserving links to existing workarounds.
3. **Geometry and baking review:** GEO and BAK findings. Deliver separate revision, texture-set, UV, symmetry, and cage test cases.
4. **Export and reliability review:** EXP and REL findings. Deliver a destination-compatibility matrix, save-failure tests, performance measurements, and upgrade/rollback findings.

### Required record for each reviewed finding

```text
Finding ID:
Reviewer and review date:
Painter version and distribution:
OS, GPU, driver, RAM, display scaling:
Project characteristics and minimal reproduction asset:
User task and expected result:
Steps and observed result:
Existing control, workaround, or shipped fix:
Classification: current defect / design limitation / discoverability /
                configuration / historical / not reproduced
Measured impact: time, clicks, latency, failure rate, or lost work:
Evidence links and reproduction artifacts:
Proposed requirement and acceptance criteria:
Open questions and confidence:
```

For an agent comparing these needs against another application, add the target application's verified behavior and implementation cost. Do not turn every complaint into a feature automatically. Preserve useful distinctions such as editable source reuse versus baked-result reuse, object selection versus material selection, and crash prevention versus recovery after a failure.

## Source register

All sources were accessed for this brief on November 2, 2026. “Listing” identifies cases where the displayed post excerpt, rather than the complete thread, supplied the evidence. Adobe Community staff comments are useful corroboration but are not substitutes for shipped documentation or reproduction.

| ID | Source and date | Evidence type |
| --- | --- | --- |
| S01 | [Adobe Painter release history][S01], updated October 21, 2026 | Official shipped features and fixes |
| S02 | [Adding hotkey support for key functions][S02], May 28, 2025 | User request and Adobe response |
| S03 | [Adobe Shortcuts][S03], updated October 8, 2026 | Official controls documentation |
| S04 | [Biggest frustration with Substance Painter][S04], June 2022 discussion with 2026 replies | Multiple user comments; historical and recent mixed |
| S05 | [Why does every 3D program have different camera controls][S05], July 2024 | Cross-application user discussion |
| S06 | [Change navigation shortcuts as in Blender][S06], January 13, 2021 | Cross-application user report; Painter remapping mentioned |
| S07 | [Painter UI looks big and blurry][S07], February 9, 2023 | User report and Adobe response |
| S08 | [Painter 10.0 announcement comments][S08], May 18, 2024 comment | Steam user complaint about 4K UI |
| S09 | [Saved-search tab forgotten on restart][S09], July 30, 2025 | User report and clarifying replies |
| S10 | [Output map names not expanding][S10], December 24, 2025 | User request and Adobe acknowledgment |
| S11 | [Painter feature-request listing][S11], individual dates not extracted | Properties search and nested-effects requests; listing |
| S12 | [Cannot edit anything][S12], January 2025 | User editing-state confusion and replies |
| S13 | [Feature suggestion Isolate Layer][S13], March 31, 2022, replies through July 2026 | Multiple users and Adobe replies |
| S14 | [Adobe Transform filter][S14], updated September 30, 2026 | Official existing capability |
| S15 | [Drop Shadow on masked Fill layers][S15], May 21, 2026 | User request and Adobe workaround |
| S16 | [Drop alphas into the selected mask][S16], June 19, 2026 | Detailed user workflow request |
| S17 | [Copy a path between layer and mask stacks][S17], May 30, 2026 | User request and anchor workaround |
| S18 | [Asset Shelf UI enhancement][S18], date not extracted | User request |
| S19 | [Material replacement while browsing][S19], individual date not extracted | Community questions listing |
| S20 | [Bringing in a file with different texture sets][S20], January 7, 2022 | User question and expert workflow explanation |
| S21 | [Adobe Layer instancing][S21], updated October 8, 2026 | Official capability and painting limitation |
| S22 | [Record painted strokes in UV space][S22], July 14, 2021, Adobe reply September 2023 | User production complaint and explanation |
| S23 | [Updated mesh breaks brush strokes][S23], March 29, 2024 | User report and Adobe explanation |
| S24 | [Import edited mesh with same UVs][S24], thread includes March–October 2023 replies | Multiple users and Adobe explanation |
| S25 | [Local cage offset painting for baking][S25], July 31, 2026 | User request and Adobe confirmation of repeated demand |
| S26 | [Multi-axis mirroring][S26], includes February 14, 2026 follow-up | User requests and Adobe alternatives |
| S27 | [Symmetry-plane request listing][S27], individual date not extracted | Feature-request listing |
| S28 | [Export multiple textures as one set][S28], December 21, 2023 | User complaint and Adobe response |
| S29 | [More export tokens including texture size][S29], May 29, 2026 | User pipeline request and Adobe response |
| S30 | [Painter community feedback listing][S30], individual date not extracted | Per-map resolution request; listing |
| S31 | [Adobe Export settings][S31], updated May 1, 2026 | Official existing controls |
| S32 | [Normal map exporting issue][S32], thread includes August 15, 2024 reply | User downstream appearance report |
| S33 | [Painter community discussion listing][S33], individual date not extracted | Viewport, Iray, and Blender appearance question; listing |
| S34 | [Eyedropper versus typed hex colors][S34], July 22–30, 2025 | User report, explanation, and configuration resolution |
| S35 | [Popup when Painter fails to save][S35], July 30, 2026 | User lost-work report and Adobe response |
| S36 | [Lost five hours after save error][S36], October 19, 2024 | Separate user lost-work report |
| S37 | [Corruption when drive is full][S37], December 19–20, 2023 | User report and Adobe explanation |
| S38 | [Large files not saving][S38], December 20, 2022 | User report with project size and build |
| S39 | [Crash when opening a file][S39], June 22, 2024 | User report with hardware context |
| S40 | [Tips for making Painter run better][S40], July 2024 | User performance complaint and discussion |
| S41 | [Adobe Layer management performance guidance][S41], updated October 8, 2026 | Official computation behavior and mitigations |
| S42 | [Newest update broke Painter][S42], March–April 2026 | Multiple export-failure and rollback complaints |

[S01]: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/release-notes/all-changes
[S02]: https://community.adobe.com/feature-requests-60/subject-feedback-adding-hotkey-support-for-key-functions-in-substance-painter-1186026
[S03]: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/settings/shortcuts
[S04]: https://www.reddit.com/r/Substance3D/comments/vdgzg6/what_is_your_biggest_frustration_with_substance/
[S05]: https://www.reddit.com/r/3Dmodeling/comments/1dz5k5h/
[S06]: https://www.reddit.com/r/ZBrush/comments/kwgc4r/
[S07]: https://community.adobe.com/questions-59/substance-3d-painter-ui-look-big-and-blurry-628250
[S08]: https://steamcommunity.com/app/2718190/eventcomments/6297799115129581877/?ctp=2&l=japanese
[S09]: https://community.adobe.com/bug-reports-58/create-a-new-tab-from-a-saved-search-position-it-it-is-forgotten-when-painter-restarts-1186491
[S10]: https://community.adobe.com/feature-requests-60/output-map-names-not-expanding-in-window-1619722
[S11]: https://community.adobe.com/substance-3d-painter-56?cb=31303&content_type=idea
[S12]: https://www.reddit.com/r/Substance3D/comments/1hwt9w9/
[S13]: https://community.adobe.com/feature-requests-60/feature-suggestion-isolate-layer-1185975
[S14]: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/filters/standard-filters/transform
[S15]: https://community.adobe.com/feature-requests-60/have-drop-shadow-filter-work-on-masked-fill-layers-1624437
[S16]: https://community.adobe.com/feature-requests-60/dragging-alphas-onto-the-model-offers-the-option-selected-mask-so-i-can-control-where-new-fills-go-inside-the-mask-i-m-working-on-1628647
[S17]: https://community.adobe.com/feature-requests-60/ability-to-copy-a-path-between-the-layer-and-mask-stack-and-vice-versa-1625819
[S18]: https://community.adobe.com/questions-59/ui-enhancement-request-for-asset-shelf-629919
[S19]: https://community.adobe.com/questions-59/index26.html
[S20]: https://community.adobe.com/questions-59/bringing-in-a-file-with-different-texture-sets-627186
[S21]: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/layer-stack/layer-instancing
[S22]: https://community.adobe.com/questions-59/painter-option-to-record-3d-painted-strokes-in-uv-space-and-not-in-world-space-627835
[S23]: https://community.adobe.com/questions-59/updated-mesh-break-brush-strokes-629131
[S24]: https://community.adobe.com/questions-59/how-to-import-edited-mesh-with-same-uv-without-breaking-textures-627173
[S25]: https://community.adobe.com/feature-requests-60/feature-request-local-cage-offset-painting-for-baking-1634798
[S26]: https://community.adobe.com/feature-requests-60/multi-axis-mirroring-1186032
[S27]: https://community.adobe.com/feature-requests-60/index5.html
[S28]: https://community.adobe.com/questions-59/exporting-multiple-textures-as-one-texture-set-628944
[S29]: https://community.adobe.com/feature-requests-60/more-tags-especially-texturesize-tag-1625642
[S30]: https://community.adobe.com/substance-3d-painter-56/index2.html?cb=31303
[S31]: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/getting-started/export/export-window/export-settings
[S32]: https://community.adobe.com/questions-59/normal-map-exporting-issue-628009
[S33]: https://community.adobe.com/substance-3d-painter-56/index115.html
[S34]: https://community.adobe.com/questions-59/color-space-with-eye-dropper-vs-typing-hex-code-629921
[S35]: https://community.adobe.com/feature-requests-60/show-a-popup-when-substance-painter-fails-to-save-1634535
[S36]: https://community.adobe.com/questions-59/lost-5-hours-of-progress-in-adobe-substance-painter-due-to-save-error-629395
[S37]: https://community.adobe.com/bug-reports-58/stop-corrupting-my-files-when-drive-space-is-full-1186153
[S38]: https://community.adobe.com/bug-reports-58/substance-not-saving-large-files-and-not-responding-1186605
[S39]: https://community.adobe.com/bug-reports-58/substance-3d-painter-crashes-when-trying-to-open-a-file-1186257
[S40]: https://www.reddit.com/r/Substance3D/comments/1dzyzpl/any_tips_for_making_substance_painter_run_better/
[S41]: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/technical-support/performance-guidelines/layer-management
[S42]: https://www.reddit.com/r/Substance3D/comments/1rr9sic/newest_update_completely_broke_my_substance/
