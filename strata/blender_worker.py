"""External Blender worker; run only with --background --factory-startup."""
import sys
from pathlib import Path
import numpy as np
import bpy


def main():
    source, destination = sys.argv[sys.argv.index("--") + 1:][:2]
    data = np.load(source, allow_pickle=False)
    indices = data["indices"].astype(int)
    mesh = bpy.data.meshes.new("Strata Mikk reference")
    mesh.from_pydata(data["positions"].tolist(), [], indices.tolist())
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    ids = np.array([loop.vertex_index for loop in mesh.loops], np.int64)
    uv_layer.data.foreach_set("uv", data["uvs"][ids].astype(np.float32).ravel())
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    mesh.normals_split_custom_set(data["normals"][ids].tolist())
    mesh.calc_tangents(uvmap="UVMap")
    tangents = np.array([(*loop.tangent, loop.bitangent_sign) for loop in mesh.loops], np.float32)
    normals = np.array([normal.vector[:] for normal in mesh.corner_normals], np.float32)
    np.savez(destination, tangents=tangents, normals=normals, vertex_ids=ids, version=np.array(bpy.app.version_string))


if __name__ == "__main__":
    main()
