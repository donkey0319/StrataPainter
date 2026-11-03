"""External Blender per-tile UV worker; preserve geometry and face order."""
import json
import math
import sys
import numpy as np
import bpy
import bmesh


def main():
    source, destination = sys.argv[sys.argv.index("--") + 1:][:2]
    data = np.load(source, allow_pickle=False)
    settings = json.loads(str(data["settings"]))
    groups = json.loads(str(data["groups"]))
    bpy.ops.object.select_all(action="DESELECT")
    uvs = data["uvs"][data["indices"]].copy()
    for group in groups:
        ids = np.asarray(group["triangles"], int)
        original = data["indices"][ids]
        # Weld by position within source parts, so imported corner splits do not
        # turn every triangle into an artificial disconnected chart.
        vertices, lookup, faces = [], {}, []
        for triangle in original:
            face = []
            for vertex in triangle:
                position = data["positions"][vertex]
                key = (int(data["parts"][vertex, 0]), *map(float, position))
                if key not in lookup:
                    lookup[key] = len(vertices)
                    vertices.append(position.tolist())
                face.append(lookup[key])
            faces.append(face)
        mesh = bpy.data.meshes.new("Strata UV preparation")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        obj = bpy.data.objects.new("Strata UV preparation", mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        mesh.uv_layers.new(name="UVMap")
        bm = bmesh.new()
        bm.from_mesh(mesh)
        if any(len(edge.link_faces) > 2 for edge in bm.edges):
            raise ValueError("Nonmanifold geometry: an edge has more than two faces; repair before unwrapping")
        for edge in bm.edges:
            edge.seam = edge.is_boundary or (edge.is_manifold and edge.calc_face_angle() > math.radians(settings["angle_degrees"]))
        bm.to_mesh(mesh)
        bm.free()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        region = group["region"]
        padding = settings["padding_px"] / settings["resolution"]
        scale = min(region[2] - region[0], region[3] - region[1]) - 2 * padding
        margin = padding / scale
        if settings["method"] == "smart":
            bpy.ops.uv.smart_project(angle_limit=math.radians(settings["angle_degrees"]), margin_method="FRACTION",
                                     island_margin=margin, scale_to_bounds=False)
        else:
            bpy.ops.uv.unwrap(method="ANGLE_BASED", margin_method="FRACTION", margin=margin)
        bpy.ops.uv.pack_islands(rotate=settings["rotate"], margin_method="FRACTION", margin=margin)
        bpy.ops.object.mode_set(mode="OBJECT")
        values = np.array([loop.uv[:] for loop in mesh.uv_layers.active.data], np.float32).reshape(-1, 3, 2)
        uvs[ids] = values * scale + np.array([region[0] + padding, region[1] + padding], np.float32)
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    np.savez(destination, uvs=uvs, version=np.array(bpy.app.version_string))


if __name__ == "__main__":
    main()
