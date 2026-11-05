"""Create an original, nonfunctional tutorial grenade prop with Blender.

Run: blender --background --factory-startup --python examples/grenade_mesh.py -- OUTPUT_DIRECTORY
The mesh is a visual reconstruction, not the tutorial author's original asset.
"""
import json
import math
from pathlib import Path
import sys

import bpy


OUT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
materials = {}
for name, color in (("Grenade_Body_ID", (.23, .25, .11)),
                    ("Grenade_Trigger_Body_ID", (.65, .65, .61)),
                    ("Safety_clasp_id", (.72, .72, .67)),
                    ("Pull_Ring_ID", (.6, .6, .56)),
                    ("Spring_assembly_id", (.3, .3, .28))):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    materials[name] = mat


def surface(name, rings, segments, material, uv_box, angle_offset=-math.pi * 1.5):
    """Connected cylindrical UV chart; seam is at the rear of the prop."""
    vertices, faces = [], []
    for z, radius in rings:
        for j in range(segments + 1):
            u = j / segments
            a = 2 * math.pi * u + angle_offset
            r = radius(u) if callable(radius) else radius
            vertices.append((r * math.cos(a), r * math.sin(a), z))
    for i in range(len(rings) - 1):
        for j in range(segments):
            k = i * (segments + 1) + j
            faces.append((k, k + 1, k + segments + 2, k + segments + 1))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    mesh.materials.append(materials[material])
    uv = mesh.uv_layers.new(name="UVMap")
    x0, y0, x1, y1 = uv_box
    for poly in mesh.polygons:
        poly.use_smooth = True
        for loop_id in poly.loop_indices:
            v = mesh.loops[loop_id].vertex_index
            row, col = divmod(v, segments + 1)
            uv.data[loop_id].uv = (x0 + (x1 - x0) * col / segments,
                                   y0 + (y1 - y0) * row / (len(rings) - 1))
    return obj


def finish(obj, material):
    obj.data.materials.append(materials[material])
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = obj.modifiers.new("Soft manufactured edges", "BEVEL")
    bevel.width, bevel.segments = .025, 3
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=.04)
    bpy.ops.object.mode_set(mode="OBJECT")
    for poly in obj.data.polygons:
        poly.use_smooth = True
    normal = obj.modifiers.new("Weighted corner normals", "WEIGHTED_NORMAL")
    bpy.ops.object.modifier_apply(modifier=normal.name)


def cylinder(name, radius, depth, z, material, vertices=64):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth,
                                      location=(0, 0, z))
    obj = bpy.context.object
    obj.name = name
    finish(obj, material)
    return obj


profile = [(0, .12), (.25, .46), (.65, .78), (1.05, .94),
           (1.45, .98), (1.85, .88), (2.1, .73), (2.7, .46)]


def body_radius(z, u):
    for (a, ra), (b, rb) in zip(profile, profile[1:]):
        if a <= z <= b:
            r = ra + (rb - ra) * (z - a) / (b - a)
            break
    horizontal = max(math.exp(-((z - y) / .035) ** 4)
                     for y in (.45, .85, 1.25, 1.65, 2.05))
    phase = abs((u * 12 + .5) % 1 - .5)
    vertical = math.exp(-((.5 - phase) / .06) ** 4)
    return max(.03, r - .065 * horizontal - .055 * vertical)


surface("Segmented cast body", [(2.7 * i / 216,
        lambda u, z=2.7 * i / 216: body_radius(z, u)) for i in range(217)],
        192, "Grenade_Body_ID", (.04, .05, .96, .83))
surface("Red neck band", [(2.69, .46), (2.70, .48), (2.75, .48), (2.76, .45)],
        96, "Grenade_Body_ID", (.08, .89, .92, .96))
cylinder("Trigger housing", .39, .62, 3.08, "Grenade_Trigger_Body_ID")
cylinder("Trigger base lip", .405, .065, 2.80, "Spring_assembly_id")
cylinder("Trigger cap", .405, .07, 3.40, "Grenade_Trigger_Body_ID")

# A solid decorative spoon silhouette, with no internal mechanism.
outline = [(-.43, 3.50), (.43, 3.50), (.54, 3.43), (.66, 2.85),
           (1.00, 1.80), (.96, 1.44), (.86, 1.78), (.48, 2.82),
           (.34, 3.35), (-.43, 3.35)]
vertices = [(x, y, z) for y in (-.16, .16) for x, z in outline]
n = len(outline)
faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
mesh = bpy.data.meshes.new("Spoon")
mesh.from_pydata(vertices, [], faces)
obj = bpy.data.objects.new("Safety spoon", mesh)
bpy.context.collection.objects.link(obj)
finish(obj, "Safety_clasp_id")

bpy.ops.mesh.primitive_torus_add(major_radius=.235, minor_radius=.026,
                               major_segments=64, minor_segments=12,
                               location=(-.49, -.03, 3.25), rotation=(math.pi / 2, 0, 0))
obj = bpy.context.object
obj.name = "Pull ring"
finish(obj, "Pull_Ring_ID")

# Consolidate by material, preserving the body and neck band's separate UV charts.
for name in materials:
    objects = [o for o in bpy.context.scene.objects if o.type == "MESH"
               and o.data.materials and o.data.materials[0].name == name]
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        bpy.ops.object.join()
    bpy.context.object.name = name
    if name != "Grenade_Body_ID":
        # Parts that shared a material had separate initial unwraps. Repack the
        # combined selection so their bake maps cannot overlap each other.
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=.025)
        bpy.ops.object.mode_set(mode="OBJECT")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "grenade_source.blend"))
bpy.ops.export_scene.fbx(filepath=str(OUT / "grenade_reconstruction.fbx"),
    use_selection=True, object_types={"MESH"}, add_leaf_bones=False,
    axis_forward="-Z", axis_up="Y", bake_anim=False, mesh_smooth_type="FACE")
(OUT / "mesh_notes.json").write_text(json.dumps({
    "procedural_asset": True, "source": "original visual reconstruction",
    "reference": "https://www.youtube.com/watch?v=uxxliJba8m0",
    "body_uv": [.04, .05, .96, .83], "body_height": 2.7,
    "bell_heights": [.25, .65, 1.05, 1.45, 1.85],
    "materials": list(materials),
    "limits": "Decorative exterior only; geometry and UVs differ from the tutorial."}, indent=2))
print("CREATED", OUT / "grenade_reconstruction.fbx", flush=True)
