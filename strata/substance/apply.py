"""Put converted Substance Painter content into a live Strata engine (GPU side).

  add_imported(engine, result, index=None, parent=None)   smart material -> layers (one undo step)
  apply_mask(engine, mask_build, layer=None, replace=False) smart mask -> a layer's mask (one undo)
  import_project(engine, project_import, ...)               .spp -> new project, every texture set

The Engine exposes these as add_imported / apply_mask_state / import_painter_project.
"""
from __future__ import annotations

import copy

from ..layers import Effect, Layer, _uid
from .convert import ImportedLayer, ImportResult, MaskBuild, fresh_copy
from .replay import MAX_DABS_PER_LAYER, MAX_DABS_TOTAL, Replayer


class ReplayStats:
    def __init__(self):
        self.dabs = 0
        self.skipped = 0
        self.truncated = False

    def add(self, rp: Replayer):
        self.dabs += rp.dabs
        self.skipped += rp.skipped
        self.truncated = self.truncated or rp.truncated


def _build(engine, ts, il: ImportedLayer, pending: list) -> Layer:
    """GPU allocation for one converted layer tree; paint jobs are queued in `pending`."""
    lay = il.layer
    lay.children = [_build(engine, ts, c, pending) for c in il.children]
    if lay.kind == "paint" and lay.tex is None:
        engine._alloc_paint(lay, ts.res)
    if lay.has_mask:
        if lay.mask_tex is None:
            engine._alloc_mask(lay, 1.0 if il.mask_fill is None else float(il.mask_fill), ts.res)
    if il.jobs and lay.kind == "paint":
        pending.append((lay, il.jobs, False))
    if il.mask_jobs and lay.has_mask:
        pending.append((lay, il.mask_jobs, True))
    return lay


def _begin_replay(engine, pending, report=None, progress=None, max_dabs=MAX_DABS_TOTAL, per_layer=MAX_DABS_PER_LAYER):
    from . import session
    if report:
        engine.import_reports.append(copy.deepcopy(report))
    engine.import_state=session.create(engine,pending)
    session.resume(engine,max_dabs,per_layer,progress)


def _budgets(total,per_layer):
    if type(total) is not int or total<1 or type(per_layer) is not int or per_layer<1:
        raise ValueError("Replay budgets must be positive integers")


def _guard(engine):
    if engine.import_state and engine.import_state["status"]!="complete":
        raise ValueError("Finish or explicitly discard the pending import continuation before importing more content")
    if engine.ts is not None and engine.ts.tiles is not None:
        raise ValueError("Painter replay into tiled materials is not validated; import into a separate untiled project")


def add_imported(engine, result: ImportResult, index=None, parent: Layer | None = None, record=True,
                 progress=None, max_dabs=MAX_DABS_TOTAL, per_layer=MAX_DABS_PER_LAYER) -> list:
    """Insert a converted smart material into the active texture set. Returns the new top layers."""
    if engine.ts is None:
        return []
    _budgets(max_dabs,per_layer)
    _guard(engine)
    ts = engine.ts
    if record:
        engine._push_undo(engine._snapshot_stack())
    pending, out = [], []
    items = fresh_copy(result.layers)
    target = parent.children if parent is not None else ts.layers
    if index is None:
        # like Painter: land above the selected layer
        sel = ts.selected if parent is None else -1
        index = sel + 1 if 0 <= sel < len(target) else len(target)
    for k, il in enumerate(items):
        lay = _build(engine, ts, il, pending)
        target.insert(index + k, lay)
        out.append(lay)
    _begin_replay(engine, [(ts,lay,jobs,mask) for lay,jobs,mask in pending], result.report, progress, max_dabs, per_layer)
    if out:
        if parent is None:
            ts.selected, ts.focus = target.index(out[-1]), None
        else:
            engine.select(out[-1])
    ts.dirty = True
    engine.dirty = True
    return out


def apply_mask(engine, mb: MaskBuild | None, layer: Layer | None = None, replace=False, record=True, report=None, progress=None, max_dabs=MAX_DABS_TOTAL, per_layer=MAX_DABS_PER_LAYER) -> bool:
    """Apply a converted smart mask to `layer` (default: the selected layer). Like Painter, a black
    mask is created when the layer has none, and the smart mask's effects are added on top
    (replace=True clears the existing mask effects first)."""
    lay = layer if layer is not None else engine.layer
    if lay is None or mb is None:
        return False
    _budgets(max_dabs,per_layer)
    _guard(engine)
    if record:
        engine._push_undo(engine._snapshot_stack())
        if lay.mask_tex is not None:
            engine._push_undo(("tex", lay, {"mask": engine.gpu.clone(lay.mask_tex)}))
    ts = engine.ts
    if replace:
        lay.mask_effects = []
    if mb.painted or mb.base < 0.999 or not lay.has_mask:
        if lay.mask_tex is None:
            engine._alloc_mask(lay, float(mb.base), ts.res)
        elif replace or not lay.has_mask:
            engine.gpu.fill(lay.mask_tex, (mb.base, mb.base, mb.base, 1))
        lay.has_mask = True
    for e in mb.effects:
        e2 = copy.deepcopy(e)
        e2.uid = _uid()
        lay.mask_effects.append(e2)
    if mb.painted and mb.jobs:
        _begin_replay(engine,[(ts,lay,mb.jobs,True)],report,progress,max_dabs,per_layer)
    elif report:
        report=copy.deepcopy(report);report["replay"]={"status":"not_required","truncated":False}
        engine.import_reports.append(report)
    ts.dirty = True
    engine.dirty = True
    return True


def import_project(engine, proj, ao_samples=96, progress=None, max_dabs=MAX_DABS_TOTAL, per_layer=MAX_DABS_PER_LAYER) -> int:
    """Replace the engine's project with an imported .spp: the mesh, one Strata texture set per
    Painter texture set (same resolutions), every layer stack, and replayed paint strokes.
    Returns the number of brush dabs replayed."""
    _budgets(max_dabs,per_layer)
    import numpy as np
    if np.any(proj.mesh.uvs < 0) or np.any(proj.mesh.uvs > 1):
        raise ValueError("Painter tiled/out-of-range UV replay is not validated; source project was retained")
    sets = proj.sets or []
    resolutions = {s.name: int(s.resolution) for s in sets} if sets else None
    res = int(proj.resolution)

    def bake_prog(f):
        if progress is not None:
            progress(0.6 * f)
    engine.new_project(proj.mesh, res=res, ao_samples=ao_samples, progress=bake_prog,
                       with_default_layer=False, split_materials=len(sets) > 1, resolutions=resolutions)
    replay_pending=[]
    by_name = {s.name: s for s in sets}
    n = max(len(engine.sets), 1)
    for k, ts in enumerate(engine.sets):
        si = by_name.get(ts.name) or (sets[k] if k < len(sets) else None)
        if si is None:
            continue
        if len(engine.sets) == 1 and ts.name == "Default":
            ts.name = si.name
        pending = []
        ts.layers = [_build(engine, ts, il, pending) for il in fresh_copy(si.result.layers)]
        ts.selected = len(ts.layers) - 1
        ts.dirty = True

        replay_pending.extend((ts,lay,jobs,mask) for lay,jobs,mask in pending)
    _begin_replay(engine,replay_pending,proj.result.report,
                  (lambda value: progress(.6+.4*value)) if progress else None,max_dabs,per_layer)
    names = [ts.name for ts in engine.sets]
    want = proj.texture_set if proj.texture_set in names else None
    engine.active = names.index(want) if want else 0
    engine.undo_stack.clear()
    engine.redo_stack.clear()
    engine.dirty = True
    return engine.last_replay.dabs


_ = (Effect,)
