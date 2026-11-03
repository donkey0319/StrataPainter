# Texture export

The Export Textures dialog uses the same validated output manifest as the writer. Its preview lists every selected texture set and output filename, including the resolved format, depth and resolution. Export is disabled when a template or selection cannot produce valid distinct files.

Choose a stock template, select texture sets and output maps, and set format, depth, size and padding overrides. The default is Unreal Engine Packed; Unity URP/HDRP, Blender, Arnold, glTF-style maps and separate channels are also available. These templates create texture maps, not complete scenes or material graphs in those applications.

Expand Template editor to edit the JSON definition, then Apply template. Load JSON and Save JSON share the engine's template format. Map names support `$mesh`, `$textureSet` and `$project`; the Project name token field controls `$project`. Use `$textureSet` to distinguish materials. Names are leaf filenames rather than relative directory paths. Invalid names, reserved device names, unknown tokens and case-insensitive collisions are rejected before export. Names that become equal after sanitization, such as `A B` and `A/B`, must be renamed or exported separately.

Global format/depth settings override per-map settings; per-map overrides otherwise take precedence over the template. The preview shows the actual supported depth selected for a format. If a requested depth is unavailable, the exporter chooses its supported fallback. Larger outputs evaluate procedural content and supported native operations at the requested size without changing the editing session. Legacy rasters, clone/smudge checkpoints and unsupported dependencies are resampled explicitly; see PAINT_OPERATIONS.md. Managed color delivery follows architecture/COLOR.md; data maps bypass color/display transforms.

## Channel packing

Use `rgb` for a color source, `rgba` for a color source plus the opacity channel, `l` for grayscale, or explicit `r`, `g`, `b`, `a` components. An explicit `a` overrides the automatic opacity in an `rgba` map. Scalar sources can also be repeated into `rgb`. Sources include material channels, mesh maps, OpenGL/DirectX combined normals, smoothness/glossiness, derived diffuse/specular and constants `0`, `0.5`, `1`.

```json
{
  "name": "Custom packed maps",
  "format": "png",
  "depth": "8",
  "maps": [
    {"name": "$mesh_$textureSet_BaseColor", "rgb": "basecolor"},
    {"name": "$mesh_$textureSet_Normal", "rgb": "normal_directx"},
    {"name": "$mesh_$textureSet_ORM", "r": "ao", "g": "roughness", "b": "metallic"},
    {"name": "$mesh_$textureSet_Height", "l": "height", "depth": "16"}
  ]
}
```

Sparse explicit packing preserves component positions: `r` plus `a` writes RGBA with zero green/blue, and `g` plus `b` writes RGB with zero red. A lone `r` writes grayscale. A scalar component may reference `basecolor.g`; color components are `r/g/b`, while scalar sources only permit their `r` component.

## Batch safety and compatibility

All files are evaluated and encoded in a staging directory before any destination files are replaced. If evaluation fails, existing outputs remain unchanged. If publication fails, the writer attempts to restore earlier outputs. If rollback itself fails, the error identifies the retained staging directory containing recovery files. This is a recoverable batch operation rather than a filesystem-wide atomic transaction; do not concurrently export into the same destinations from several processes.

The legacy `export(engine, folder, preset, name)` API keeps original filenames for one selected texture set. When several sets are exported through a built-in legacy template, each map gets a set-name suffix, for example `T_Asset_BC_Metal.png` and `T_Asset_BC_Rubber.png`. Custom templates are never silently renamed to resolve collisions.

## Engine API

`build_export_manifest(engine, folder, ...)` validates and resolves export options without GPU calls or file writes. It is importable without ModernGL. `manifest.entries` exposes each selected set, mapping, resolved path, format, depth and resolution. `write_export_manifest(engine, manifest)` consumes that exact preview snapshot and rejects it if mesh identity or set name/key/resolution changed. `export_textures(...)` remains the convenience operation that performs both steps.

The optional material JSON contains only enabled outputs from the manifest, with their actual filenames and export resolution. It is a description for integration code, not an engine shader resource.

Explicitly enabled material tiles add a tile address to each manifest entry. Use
the $udim filename token (for example Color_$udim); a tiled template without it
receives a suffix such as Color_1001. Ordinary single-tile filenames are unchanged.
All tile outputs appear in the material JSON. Planning validates collisions and
the writer rejects stale tile layouts. Evaluation streams one tile at a time;
higher-resolution output replays native tile dabs and resamples imported bases.
The same staged publication and rollback rules apply to the whole tile batch.
Tiled desktop authoring UI remains pending; see architecture/TILES.md.

Run `python tests/export_check.py` for CPU packing, validation, file-output and fault-injection checks. Run `python tests/export_ui_check.py .artifacts/export-ui` with a real window/OpenGL context to verify the dialog, preview and GPU output together.


T19 adds genuine mesh/material delivery separately from these map templates:
portable Blender bundles, automatic target node setup, real GLB mesh/material
interchange and an optional Cycles renderer. See DELIVERY.md and EXTENSIONS.md.
The original optional material JSON above remains a texture manifest, and the
Unreal/Unity presets alone do not constitute tested target setup integrations.
