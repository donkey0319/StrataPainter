"""Optional external Blender MikkTSpace adapter; no user startup/settings are loaded."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import numpy as np


def blender_path():
    configured = os.environ.get("STRATA_BLENDER")
    if configured:
        if not Path(configured).is_file():
            raise ValueError("STRATA_BLENDER does not identify an executable")
        return configured
    found = shutil.which("blender")
    if found:
        return found
    root = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Blender Foundation"
    candidates = sorted(root.glob("Blender */blender.exe"), reverse=True) if root.exists() else []
    return str(candidates[0]) if candidates else None


def mikk_mesh(mesh):
    executable = blender_path()
    if not executable:
        raise RuntimeError("MikkTSpace requires Blender; set STRATA_BLENDER or use legacy tangents")
    root = os.environ.get("STRATA_RESOURCE_CACHE")
    if root:
        Path(root).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="strata-mikk-", dir=root) as temporary:
        directory = Path(temporary)
        source, output = directory / "input.npz", directory / "output.npz"
        np.savez(source, positions=mesh.positions, normals=mesh.normals, uvs=mesh.uvs, indices=mesh.indices)
        environment = os.environ.copy()
        environment.update(BLENDER_USER_CONFIG=str(directory / "config"), BLENDER_USER_SCRIPTS=str(directory / "scripts"))
        result = subprocess.run([executable, "--background", "--factory-startup", "--python",
                                 str(Path(__file__).with_name("blender_worker.py")), "--", str(source), str(output)],
                                capture_output=True, text=True, env=environment, timeout=120,
                                creationflags=0x08000000 if os.name == "nt" else 0)
        if result.returncode or not output.is_file():
            raise RuntimeError("Blender tangent calculation failed: " + (result.stderr or result.stdout)[-1200:])
        with np.load(output, allow_pickle=False) as data:
            tangents = data["tangents"].copy()
            normals = data["normals"].copy()
            indices = data["vertex_ids"].copy()
            version = str(data["version"])
    if (not np.array_equal(indices, mesh.indices.ravel()) or tangents.shape != (len(indices), 4)
            or normals.shape != (len(indices), 3) or not np.isfinite(tangents).all()
            or not np.isfinite(normals).all()):
        raise ValueError("Invalid or reordered MikkTSpace result")
    from .mesh import Mesh
    result = Mesh(mesh.name, mesh.positions[indices], normals, mesh.uvs[indices],
                  np.arange(len(indices), dtype=np.uint32).reshape(-1, 3), tangents=tangents,
                  curvature=mesh.curvature[indices], extra=copy.deepcopy(mesh.extra),
                  parts=mesh.parts[indices], colors=mesh.colors[indices], tri_material=mesh.tri_material.copy(),
                  material_names=list(mesh.material_names), part_names=list(mesh.part_names)).finalize()
    result.extra["tangent_basis"] = {"name": "MikkTSpace", "backend": "Blender", "version": version}
    return result
