"""Detached texture-set evaluation: procedural content and native dabs at output resolution."""
import copy
from contextlib import contextmanager
import numpy as np

from .channels import BY_KEY
from .compositor import Compositor
from .journal import mesh_revision, checkpoint_values
from .layers import Brush, Layer
from .painter import Stroke, View, Dab, TOOL_PROJECTION
from .paintstore import PaintTextures
from .viewinput import UVMapping


def _view(engine, record):
    mapping = UVMapping(**record["uv_mapping"]) if record["uv_mapping"] else None
    if mapping is None:
        engine.renderer.render_pick(engine.gm, np.asarray(record["vp"]), *record["size"])
    return View(np.asarray(record["vp"]), tuple(record["size"]), np.asarray(record["campos"]),
                np.asarray(record["right"]), engine.renderer.pick_pos if mapping is None else engine.gpu.white,
                engine.renderer.pick_uv if mapping is None else None, lambda p: 1., uv_mapping=mapping)


def replay(engine, chain, textures, res, target, allocations, subset):
    """Replay recorded dabs, including original camera occlusion; never approximate clone inputs."""
    g = engine.gpu
    for channel, pixels in chain[0]["pixels"].items():
        values = checkpoint_values(pixels)
        source = g.texture((values.shape[1], values.shape[0]), values.shape[2], values, dtype="f2")
        allocations.append(source)
        output = g.resample(source, (res, res)) if source.size != (res, res) else source
        if output is not source:
            allocations.append(output)
        textures[channel] = output
    for node in chain[1:]:
        op = node["operation"]
        brush = Brush()
        brush.load_dict(op["brush"])
        view = _view(engine, op["views"][0])
        source_set = next((ts for ts in engine.sets if ts.pid == op["set_pid"]), None)
        if source_set is None:
            raise ValueError("A native operation's texture set is unavailable")
        stroke = Stroke(engine.painter, engine.gm, source_set.key, brush, view, lambda p, t: 1.,
                        target, textures if target == "layer" else textures["mask"],
                        mask_value=brush.mask_value, seed=op["seed"])
        previous_view = None
        try:
            for record in op["dabs"]:
                if record["view"] != previous_view:
                    stroke.view = _view(engine, op["views"][record["view"]])
                    previous_view = record["view"]
                values = copy.deepcopy(record["values"])
                for name in ("hit", "hit_px", "hit_uv", "sym_inv"):
                    values[name] = np.asarray(values[name])
                values["frame"] = tuple(np.asarray(value) for value in values["frame"])
                dab = Dab(**values)
                if target == "layer":
                    engine.painter.dab_paint(engine.gm, stroke.subset, stroke.buffers, stroke.brush, stroke.view, dab, None,
                                             projection=stroke.tool == TOOL_PROJECTION)
                else:
                    engine.painter.dab_mask(engine.gm, stroke.subset, stroke.buffers[0], stroke.brush, stroke.view, dab, None)
                stroke.changed = True
            stroke.apply()
        finally:
            stroke.release()
            for texture in textures.values():
                if all(texture is not existing for existing in allocations):
                    allocations.append(texture)


def evaluate_raster(engine, ts, source, kind, original, res, allocations, report=None, revision=None):
    report = [] if report is None else report
    key = engine.journal.key(source, kind)
    chain = engine.journal.chain(key)
    reason = None
    revision = revision or mesh_revision(engine.mesh)
    if chain:
        for node in chain[1:]:
            op = node["operation"]
            if op["mesh_revision"] != revision or op["color_identity"] != engine.color.cache_id:
                reason = "Mesh or color dependency changed; current raster resampled"
                break
    if chain and not reason:
        textures = PaintTextures(engine.gpu, res) if kind == "layer" else {}
        replay(engine, chain, textures, res, kind, allocations, ts.key)
        count = len(chain) - 1
        report.append({"target": key, "replayed": count, "base": chain[0].get("reason"),
                       "evaluation": "native replay" if count else "raster resampling"})
        return textures if kind == "layer" else textures.get("mask")
    def resample(texture):
        result = engine.gpu.resample(texture, (res, res))
        allocations.append(result)
        return result
    report.append({"target": key, "replayed": 0, "evaluation": "raster resampling",
                   "reason": reason or "No native operation history"})
    return ({channel: resample(texture) for channel, texture in original.items()} if kind == "layer" else resample(original))


@contextmanager
def evaluate_set(engine, ts, resolution):
    """Yield a temporary set and report; original rasters, settings and history stay intact."""
    from .engine import TextureSet
    res = int(resolution)
    if not 1 <= res <= 32768:
        raise ValueError("Invalid evaluation resolution")
    from .userchannels import validate_resolution
    validate_resolution(engine.user_channels, res)
    staged = TextureSet(ts.name, ts.materials, ts.tri_ids, res, ts.key)
    staged.pid, staged.bake_settings = ts.pid, copy.deepcopy(ts.bake_settings)
    allocations, memo, report = [], {}, []
    revision = mesh_revision(engine.mesh)
    original_view = (engine._vp.copy(), engine.view_size)

    def resample(texture):
        if texture is None:
            return None
        result = engine.gpu.resample(texture, (res, res))
        return result

    def target(source, kind, original):
        return evaluate_raster(engine, ts, source, kind, original, res, allocations, report, revision)

    def clone(source):
        if id(source) in memo:
            return memo[id(source)]
        result = Layer.from_dict(source.to_dict())
        memo[id(source)] = result
        result.children = [clone(child) for child in source.children]
        if source.tex is not None:
            result.tex = PaintTextures(engine.gpu, res, target(source, "layer", source.tex))
        if source.mask_tex is not None:
            result.mask_tex = target(source, "mask", source.mask_tex)
        for before, after in zip(source.mask_effects, result.mask_effects):
            if before.tex is not None:
                after.tex = target(before, "mask", before.tex)
        if result.raster_res is not None:
            result.raster_res = res
        return result

    try:
        staged.layers = [clone(layer) for layer in ts.layers]
        # Re-bake analytic surface maps at the requested size. External imported
        # maps have an explicit raster source and are honestly resampled.
        external = staged.bake_settings.external_maps
        staged.bake_settings.external_maps = {}
        staged.bakes = engine._bake(staged)
        staged.bake_settings.external_maps = external
        from .meshmap import SLOTS
        for key in external:
            attribute = SLOTS[key][1]
            old = getattr(staged.bakes, attribute)
            if old is not None:
                old.release()
            setattr(staged.bakes, attribute, resample(getattr(ts.bakes, attribute)))
        staged.comp = Compositor(engine.gpu, res, staged.bakes, engine.mesh, engine.resources)
        staged.comp.composite(staged.layers, engine.normal_strength)
        yield staged, report
    finally:
        staged.release()
        for texture in {id(texture): texture for texture in allocations}.values():
            engine.painter.forget_textures([texture])
            texture.release()
        engine.gpu.release_scratch()
        if engine.mesh is not None and engine.renderer.pick_pos is not None:
            engine.renderer.render_pick(engine.gm, original_view[0], *original_view[1])
