"""High-level import of Substance 3D Painter files into Strata (no GPU needed here).

  load_smart_material(path) -> ImportResult         .spsm  (layer preset)
  load_smart_mask(path)     -> SmartMask            .spmsk (mask preset)
  inspect_project(path)     -> ProjectInfo          .spp   texture sets, resolution, version
  load_project(path, set)   -> ProjectImport        .spp   mesh + the layer stack of every texture set

Engine.import_* (strata/engine.py) turns these into GPU layers, including stroke replay.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

from ..mesh import Mesh
from . import assbin, hbo
from .convert import Converter, ImportResult, MaskBuild, convert_mask_preset, convert_preset, Notes
from .spfile import SPFile, SPFileError

SMART_MATERIAL_EXTS = (".spsm",)
SMART_MASK_EXTS = (".spmsk",)
PROJECT_EXTS = (".spp",)
ALL_EXTS = SMART_MATERIAL_EXTS + SMART_MASK_EXTS + PROJECT_EXTS


def _best_preset(spf: SPFile):
    """Painter writes the same preset at several data versions for older releases; use the newest
    one that decodes."""
    best, err = None, None
    for name in spf.presets():
        try:
            root = spf.hbo(name)
            dv = spf.encoding(name)[1]
            if best is None or dv > best[1]:
                best = (root, dv, name)
        except Exception as e:      # a damaged variant shouldn't stop us
            err = e
    if best is None:
        raise SPFileError(f"{spf.name}: no readable layer preset ({err})")
    return best[0]


# ----------------------------------------------------------------------------- smart materials
def load_smart_material(path: str) -> ImportResult:
    """.spsm -> ImportResult holding one folder (the smart material's root folder, as in Painter)."""
    with SPFile(path) as spf:
        root = _best_preset(spf)
        res = convert_preset(root, spf, name=spf.name)
        res.name = spf.name
        res.kind = "smart_material"
        res.version = spf.painter_version()
        return res


@dataclass
class SmartMask:
    name: str
    mask: MaskBuild | None
    notes: list


def load_smart_mask(path: str) -> SmartMask:
    with SPFile(path) as spf:
        root = _best_preset(spf)
        mb, notes = convert_mask_preset(root, spf, spf.name)
        if mb is not None and mb.trivial:
            mb = None
        return SmartMask(spf.name, mb, notes)


def read_thumbnail(path: str):
    try:
        with SPFile(path) as spf:
            return spf.thumbnail()
    except Exception:
        return None


# ----------------------------------------------------------------------------- projects
@dataclass
class TextureSetInfo:
    index: int
    name: str
    resolution: int
    layer_count: int
    stroke_count: int


@dataclass
class ProjectInfo:
    path: str
    name: str
    version: str
    texture_sets: list


@dataclass
class SetImport:
    name: str
    resolution: int
    result: ImportResult


@dataclass
class ProjectImport:
    name: str
    version: str
    texture_set: str                  # the set that becomes active
    mesh: Mesh                        # tri_material = index into `sets`
    resolution: int                   # of the active set
    result: ImportResult              # of the active set (notes cover the whole project)
    texture_sets: list = field(default_factory=list)      # set names
    sets: list = field(default_factory=list)              # SetImport, same order as mesh materials
    active: int = 0


def _count(stack, types):
    n = [0]

    def f(o, _):
        if o.type in types:
            n[0] += 1
    hbo.walk(stack, f)
    return n[0]


def _materials(doc):
    return [m for m in (doc.get("materials") or []) if isinstance(m, hbo.HObj)]


def _resolution(mat) -> int:
    r = hbo.val(mat.get("resolutionLog2"))
    if isinstance(r, list) and r:
        r = r[0]
    try:
        return int(2 ** int(r))
    except (TypeError, ValueError):
        return 2048


def _set_name(mat, i):
    return hbo.text(mat.get("sceneMaterialName")) or f"Texture set {i + 1}"


def inspect_project(path: str) -> ProjectInfo:
    with SPFile(path) as spf:
        if spf.kind != "project":
            raise SPFileError(f"{spf.name} is not a Painter project")
        doc = spf.hbo("paint/document.bin")
        sets = []
        for i, m in enumerate(_materials(doc)):
            stacks = [s for s in (m.get("stacks") or []) if isinstance(s, hbo.HObj)]
            nl = sum(_count(s.get("stack"), ("DataLayerColor",)) for s in stacks)
            ns = sum(_count(s.get("stack"), ("DataStroke",)) for s in stacks)
            sets.append(TextureSetInfo(i, _set_name(m, i), _resolution(m), nl, ns))
        return ProjectInfo(path, spf.name, spf.painter_version(), sets)


def _project_mesh(spf: SPFile, mats: list, name: str) -> Mesh:
    """All of the project's geometry, one material (= Strata texture set) per Painter texture set."""
    meshes, scene_names = assbin.read_scene(spf.raw("paint/scene.assbin"))
    meshes = [m for m in meshes if m["positions"] is not None and m["uvs"] is not None and len(m["indices"])]
    if not meshes:
        raise SPFileError("The project's mesh has no UV-mapped geometry")
    set_names = [_set_name(m, i) for i, m in enumerate(mats)]

    def set_of(scene_mat):
        nm = scene_names[scene_mat] if 0 <= scene_mat < len(scene_names) else None
        if nm in set_names:
            return set_names.index(nm)
        if len(scene_names) == len(set_names) and 0 <= scene_mat < len(set_names):
            return scene_mat
        return 0

    from ..mesh import compute_vertex_normals
    P, N, T, I, TM, PT, base = [], [], [], [], [], [], 0
    part_names = []
    for k, m in enumerate(meshes):
        part_names.append(m.get("name") or f"Mesh {k + 1}")
        pos = m["positions"]
        idx = m["indices"].astype(np.uint32)
        nrm = m["normals"] if m["normals"] is not None and len(m["normals"]) == len(pos) \
            else compute_vertex_normals(pos, idx)
        P.append(pos); N.append(nrm); T.append(m["uvs"]); I.append(idx + base)
        si = set_of(int(m["material"]))
        TM.append(np.full(len(idx), si, np.int32))
        PT.append(np.tile(np.array([[k, si]], np.float32), (len(pos), 1)))
        base += len(pos)
    # Painter keeps its mesh normalised and its stroke cameras in that space: no resizing here
    mesh = Mesh(name, np.concatenate(P), np.concatenate(N), np.concatenate(T), np.concatenate(I),
                parts=np.concatenate(PT), tri_material=np.concatenate(TM), material_names=set_names,
                part_names=part_names)
    return mesh.finalize()


def load_project(path: str, texture_set: int | str | None = None) -> ProjectImport:
    """.spp -> mesh + the layer stack of every texture set. `texture_set` picks the active one."""
    with SPFile(path) as spf:
        if spf.kind != "project":
            raise SPFileError(f"{spf.name} is not a Painter project")
        doc = spf.hbo("paint/document.bin")
        mats = _materials(doc)
        if not mats:
            raise SPFileError("The project has no texture sets")
        names = [_set_name(m, i) for i, m in enumerate(mats)]
        active = 0
        if isinstance(texture_set, int):
            active = max(0, min(texture_set, len(mats) - 1))
        elif isinstance(texture_set, str) and texture_set in names:
            active = names.index(texture_set)
        mesh = _project_mesh(spf, mats, spf.name)
        notes = Notes()
        conv = Converter(spf, notes, mesh_names=list(mesh.part_names or []))
        sets = []
        for i, mat in enumerate(mats):
            stacks = [s for s in (mat.get("stacks") or []) if isinstance(s, hbo.HObj)]
            if len(stacks) > 1:
                notes.add("Only the first material stack of each texture set was imported", names[i])
            layers = conv.stack(stacks[0].get("stack"), names[i]) if stacks else []
            if hbo.val(mat.get("useUVTiles"), False):
                notes.add("UDIM tiles were merged into one texture set", names[i])
            sets.append(SetImport(names[i], _resolution(mat),
                                  ImportResult(name=names[i], layers=layers, notes=[], kind="project",
                                               version=spf.painter_version())))
        lines = notes.lines()
        for s in sets:
            s.result.notes = lines
        cur = sets[active]
        return ProjectImport(spf.name, spf.painter_version(), cur.name, mesh, cur.resolution, cur.result,
                             names, sets, active)


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in PROJECT_EXTS:
        return "project"
    if ext in SMART_MASK_EXTS:
        return "smart_mask"
    if ext in SMART_MATERIAL_EXTS:
        return "smart_material"
    return ""
