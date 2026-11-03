"""Versioned native paint provenance, separate from disposable GPU undo snapshots."""
import copy
import hashlib
import os
from pathlib import Path
from .userchannels import is_user
import uuid
import zlib
import numpy as np

VERSION = 1


def checkpoint_values(pixels):
    size = int(np.prod(pixels["shape"], dtype=np.int64)) * 2
    decoder = zlib.decompressobj()
    content = decoder.decompress(pixels["data"], size + 1)
    if len(content) != size or not decoder.eof or decoder.unused_data:
        raise ValueError("Invalid or oversized native paint checkpoint")
    values = np.frombuffer(content, np.float16).reshape(pixels["shape"])
    if not np.isfinite(values).all():
        raise ValueError("Non-finite paint checkpoint")
    return values


def validate_operation(op):
    if (not isinstance(op, dict) or op.get("version") != VERSION or not isinstance(op.get("brush"), dict)
            or op.get("coordinate_space") not in ("uv", "surface") or op.get("target") not in ("layer", "mask")
            or type(op.get("seed")) is not int or not isinstance(op.get("samples"), list)
            or not isinstance(op.get("views"), list) or not op["views"] or not isinstance(op.get("dabs"), list)
            or any(not isinstance(op.get(key), str) for key in ("set_pid", "mesh_revision", "color_identity"))):
        raise ValueError("Invalid native operation provenance")
    from .userchannels import unit_value
    if op["brush"].get("user_channel") is not None:
        if not is_user(op["brush"]["user_channel"]):raise ValueError("Invalid user paint channel")
        unit_value(op["brush"].get("user_value",1.))
    for view in op["views"]:
        for key, shape in (("vp", (4, 4)), ("size", (2,)), ("campos", (3,)), ("right", (3,))):
            values = np.asarray(view.get(key), dtype=float)
            if values.shape != shape or not np.isfinite(values).all():
                raise ValueError("Invalid native operation view")
        if any(type(n) is not int or not 1 <= n <= 32768 for n in view["size"]):
            raise ValueError("Invalid operation viewport dimensions")
        if view.get("uv_mapping") is not None:
            from .viewinput import UVMapping
            UVMapping(**view["uv_mapping"])
    for sample in op["samples"]:
        if sample.get("event") not in ("start", "feed", "break") or not np.isfinite(sample.get("seconds", -1)) or sample["seconds"] < 0:
            raise ValueError("Invalid native pressure/time sample")
        if sample["event"] != "break" and not np.isfinite(sample.get("pressure", np.nan)):
            raise ValueError("Invalid native pressure sample")
    shapes = {"hit": (3,), "frame": (3, 3), "rot": (2,), "hit_px": (2,), "hit_uv": (2,), "sym_inv": (4, 4)}
    for record in op["dabs"]:
        if type(record.get("view")) is not int or not 0 <= record["view"] < len(op["views"]):
            raise ValueError("Invalid native dab view")
        values = record.get("values", {})
        if set(values) != set(shapes) | {"radius", "radius_px", "radius_uv", "flow", "occl"}:
            raise ValueError("Invalid native dab fields")
        for key, shape in shapes.items():
            array = np.asarray(values[key], dtype=float)
            if array.shape != shape or not np.isfinite(array).all():
                raise ValueError("Invalid native dab geometry")
        if any(not np.isfinite(values[key]) or values[key] < 0 for key in ("radius", "radius_px", "radius_uv", "flow")):
            raise ValueError("Invalid native dab values")


def mesh_revision(mesh):
    digest = hashlib.sha256()
    for name in ("positions", "normals", "uvs", "indices", "tangents", "tri_material"):
        digest.update(np.ascontiguousarray(getattr(mesh, name)).tobytes())
    return digest.hexdigest()


def freeze_brush(brush):
    """Content-address images before the first dab, so later file edits cannot rewrite it."""
    from .layers import Brush
    from .projectio import resource_slots
    from .alphas import BUILTIN_ALPHAS
    data = brush.to_dict()
    root = Path(os.environ.get("STRATA_RESOURCE_CACHE", str(Path.home() / ".strata" / "cache"))) / "journal"
    for owner, key, role in resource_slots({"brush": data}):
        path = owner[key]
        if path.startswith(("builtin:", "bake:")) or (role == "alpha" and path in BUILTIN_ALPHAS):
            continue
        content = Path(path).read_bytes()
        suffix = Path(path).suffix.lower()
        if not suffix[1:].isalnum() or len(suffix) > 12:
            raise ValueError("Paint resource needs a supported image extension")
        destination = root / (hashlib.sha256(content).hexdigest() + suffix)
        root.mkdir(parents=True, exist_ok=True)
        if not destination.is_file() or destination.read_bytes() != content:
            destination.write_bytes(content)
        owner[key] = str(destination)
    result = Brush()
    result.load_dict(data)
    return result


class Journal:
    def __init__(self):
        self.nodes, self.heads, self.states = {}, {}, {}

    @staticmethod
    def key(owner, target):
        return owner.pid + ":" + target

    def remember(self, serial):
        self.states[serial] = dict(self.heads)

    def restore(self, serial):
        self.heads = dict(self.states.get(serial, {}))

    def invalidate(self, owner, target):
        self.heads.pop(self.key(owner, target), None)

    def checkpoint(self, engine, owner, target, textures, reason, operation=None):
        key = self.key(owner, target)
        pixels = {}
        for channel, texture in textures.items():
            values = engine.gpu.read(texture).astype("float16")
            pixels[channel] = {"shape": list(values.shape), "data": zlib.compress(values.tobytes())}
        uid = uuid.uuid4().hex
        self.nodes[uid] = {"parent": self.heads.get(key), "key": key, "kind": "checkpoint", "reason": reason,
                           "pixels": pixels, "operation": operation}
        self.heads[key] = uid
        return uid

    def begin(self, engine, stroke, owner):
        if stroke.target == "quick":
            return
        key = self.key(owner, stroke.target)
        textures = dict(stroke.textures) if stroke.target == "layer" else {"mask": stroke.textures}
        if key not in self.heads:
            self.checkpoint(engine, owner, stroke.target, textures, "Legacy/imported or externally edited raster base")
        stroke.journal_key = key
        stroke.mesh_revision = mesh_revision(engine.mesh)
        stroke.color_identity = engine.color.cache_id
        stroke.set_pid = engine.ts.pid

    def finish(self, engine, stroke, owner):
        key = getattr(stroke, "journal_key", None)
        if key is None:
            return
        operation = {"version": VERSION, "brush": stroke.brush.to_dict(), "seed": stroke.seed,
                     "coordinate_space": "uv" if stroke.view.uv_mapping is not None else "surface",
                     "mesh_revision": stroke.mesh_revision, "color_identity": stroke.color_identity,
                     "set_pid": stroke.set_pid, "target": stroke.target, "views": stroke.recorded_views,
                     "samples": stroke.recorded_samples, "dabs": stroke.recorded_dabs,
                     "source_revision": self.heads.get(key), "clone_offset": stroke.clone_offset.tolist()}
        reason = ("Clone/smudge result and source revision retained as raster checkpoint" if stroke.direct else
                  "Quick-mask dependency retained as raster checkpoint" if stroke.quick is not None else
                  "Baked-map projection dependency retained as raster checkpoint" if any(
                      str(path).startswith("bake:") for path in stroke.brush.proj_maps.values()) else None)
        if reason:
            textures = dict(stroke.textures) if stroke.target == "layer" else {"mask": stroke.textures}
            self.checkpoint(engine, owner, stroke.target, textures, reason, operation)
        else:
            uid = uuid.uuid4().hex
            self.nodes[uid] = {"parent": self.heads.get(key), "key": key, "kind": "stroke", "operation": operation}
            self.heads[key] = uid

    def chain(self, key):
        nodes, uid, seen = [], self.heads.get(key), set()
        while uid:
            if uid in seen or uid not in self.nodes:
                raise ValueError("Invalid journal ancestry")
            seen.add(uid)
            node = self.nodes[uid]
            if node["key"] != key:
                raise ValueError("Journal target changed within a chain")
            nodes.append(node)
            if node["kind"] == "checkpoint":
                break
            uid = node.get("parent")
        return list(reversed(nodes))

    def snapshot(self, arrays):
        reachable = set()
        for head in self.heads.values():
            while head and head not in reachable:
                reachable.add(head)
                head = self.nodes[head].get("parent")
        # Redo history is session-only. Persist only the active native branches.
        nodes = {uid: copy.deepcopy(self.nodes[uid]) for uid in self.nodes if uid in reachable}
        for uid, node in nodes.items():
            for channel, pixels in node.get("pixels", {}).items():
                name = "journal_" + uid + "_" + channel
                arrays[name] = np.frombuffer(pixels.pop("data"), np.uint8)
                pixels["array"] = name
        return {"version": VERSION, "nodes": nodes, "heads": dict(self.heads)}

    @classmethod
    def load(cls, meta, arrays):
        result = cls()
        if not meta:
            return result
        if meta.get("version") != VERSION or not isinstance(meta.get("nodes"), dict) or not isinstance(meta.get("heads"), dict):
            raise ValueError("Unsupported native paint journal")
        result.nodes, result.heads = copy.deepcopy(meta["nodes"]), dict(meta["heads"])
        for uid, node in result.nodes.items():
            if node.get("kind") not in ("checkpoint", "stroke") or not isinstance(node.get("key"), str):
                raise ValueError("Invalid native paint node")
            if node.get("operation") is not None:
                validate_operation(node["operation"])
            elif node["kind"] == "stroke":
                raise ValueError("Native stroke has no operation")
            for channel, pixels in node.get("pixels", {}).items():
                if channel not in ("C", "R", "M", "H", "N", "E", "O", "mask") and not is_user(channel):
                    raise ValueError("Invalid checkpoint channel")
                shape = pixels.get("shape")
                if (not isinstance(shape, list) or len(shape) != 3 or any(type(n) is not int or n < 1 for n in shape)
                        or max(shape[:2]) > 32768 or shape[2] > 4):
                    raise ValueError("Invalid paint checkpoint dimensions")
                pixels["data"] = arrays[pixels.pop("array")].tobytes()
                checkpoint_values(pixels)
        validated = set()
        for uid in result.nodes:
            seen, ancestor = set(), uid
            while ancestor:
                if ancestor in validated:
                    break
                if ancestor in seen or ancestor not in result.nodes:
                    raise ValueError("Invalid native journal ancestry")
                seen.add(ancestor)
                ancestor = result.nodes[ancestor].get("parent")
            validated.update(seen)
        for key in result.heads:
            result.chain(key)
        return result


def view_record(view):
    mapping = view.uv_mapping
    return {"vp": np.asarray(view.vp).tolist(), "size": list(view.size), "campos": np.asarray(view.campos).tolist(),
            "right": np.asarray(view.right).tolist(), "uv_mapping": None if mapping is None else
            {"size": list(mapping.size), "zoom": mapping.zoom, "center": list(mapping.center)}}
