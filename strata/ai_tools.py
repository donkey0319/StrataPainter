"""Provider-neutral tools for the *live* engine. Call only on its owning GL thread."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .extensions import builtins, _layer


GUIDE = """You operate Strata Painter, a native layered PBR texture painter.
Use only the strata MCP tools for project operations. Never use shell commands,
file editing, or Python to change the application. Start each user request by
inspecting the live project. Read the guide/catalog before using unfamiliar tools.
Use persistent IDs, not guessed layer names or stale selection. User edits can
occur between calls: inspect again when targets change. Color is RGB [0,1]; rough
and metal are [0,1]. Prefer editable fill layers, native materials and masks.
Only claim an action succeeded after its tool result. Capture the viewport to
check visual edits. Tool images may be sent to the user's selected AI provider.
Saving/exporting requires the user to enable file output in the panel. Do not
overwrite source assets. Undo is native per operation, NOT atomic per request;
Stop prevents queued operations but does not undo completed edits. Ask the user
when the desired target or a destructive replacement is ambiguous.
"""

DOCS = {name: name + ".md" for name in (
    "ENGINE_API", "FILL_MATERIALS", "EFFECTS", "BRUSHES", "UV_PAINTING",
    "CHANNELS", "EXPORT", "TRANSACTIONS", "AI_ASSISTANT")}


def schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {},
            "required": list(required), "additionalProperties": False}


STRING = {"type": "string"}
NUMBER = {"type": "number"}
BOOL = {"type": "boolean"}
PID = {"type": "string", "description": "Persistent layer ID from strata_inspect; omitted uses selection."}
UNIT = {"type": "number", "minimum": 0, "maximum": 1}
RGB = {"type": "array", "items": UNIT, "minItems": 3, "maxItems": 3}
FLAGS = {"type": "array", "items": BOOL, "minItems": 7, "maxItems": 7}
VALUES = schema({"name": STRING, "visible": BOOL, "opacity": UNIT,
                 "color": RGB, "rough": UNIT, "metal": UNIT, "height": NUMBER,
                 "normal": RGB, "emissive": RGB, "opac": UNIT, "enabled": FLAGS,
                 "blend": {"type": "integer", "minimum": 0, "maximum": 31},
                 "variation": UNIT, "bump": UNIT,
                 "var_scale": {"type": "number", "minimum": .001, "maximum": 10000}, "seed": NUMBER})
BRUSH = schema({**{key: VALUES["properties"][key] for key in
                  ("color", "rough", "metal", "height", "normal", "emissive", "opac", "enabled")},
                "size_px": {"type": "number", "minimum": 1, "maximum": 2048},
                "size_uv": {"type": "number", "minimum": .0001, "maximum": 2},
                "size_space": {"type": "integer", "minimum": 0, "maximum": 2},
                "flow": UNIT, "hardness": UNIT, "stroke_opacity": UNIT,
                "spacing": {"type": "number", "minimum": .01, "maximum": 2},
                "mode": {"type": "integer", "enum": [0, 1]},
                "target": {"type": "integer", "enum": [0, 1]}, "mask_value": UNIT})
SUPPORTED_EFFECTS = ["fill", "generator", "levels", "invert", "blur", "threshold", "hsl", "brightness_contrast"]


def effect_schema(kind):
    from .layers import EFFECT_DEFAULTS, MaskGen
    if kind not in SUPPORTED_EFFECTS:
        raise ValueError("Effect is not exposed by the agent interface")
    defaults = vars(MaskGen()) if kind == "generator" else EFFECT_DEFAULTS[kind]
    props = {}
    for key, value in defaults.items():
        if value is None:
            continue
        if isinstance(value, bool):
            props[key] = BOOL
        elif isinstance(value, (int, float)):
            props[key] = {"type": "integer" if type(value) is int else "number", "minimum": -10000, "maximum": 10000}
        elif isinstance(value, list):
            props[key] = {"type": "array", "items": NUMBER, "minItems": len(value), "maxItems": len(value)}
    for key in ("level", "softness", "value", "in_lo", "in_hi", "out_lo", "out_hi"):
        if key in props:
            props[key] = UNIT
    if "kind" in props:
        props["kind"] = {"type": "integer", "minimum": 0, "maximum": 13}
    if "channel" in props:
        props["channel"] = {"type": "integer", "minimum": -1 if kind == "blur" else 0, "maximum": 6}
    if "gamma" in props:
        props["gamma"] = {"type": "number", "minimum": .01, "maximum": 100}
    if "radius" in props:
        props["radius"] = {"type": "number", "minimum": 0, "maximum": 64}
    return schema(props)


def specifications():
    """Real JSON schemas, shared by embedded adapters and external MCP clients."""
    definitions = [
        ("inspect", "Read live texture sets, layers, persistent IDs and material values.", schema()),
        ("guide", "Read Strata operating instructions, documentation or the preset/effect catalog.",
         schema({"topic": STRING})),
        ("viewport", "Render the current camera's 3D view as a fresh PNG for visual feedback.", schema()),
        ("layer_add", "Add/select an undoable paint, fill or group layer.", schema({
            "kind": {"type": "string", "enum": ["paint", "fill", "group"]}, "name": STRING})),
        ("layer_configure", "Edit native layer properties. Consult ENGINE_API and inspect first.",
         schema({"pid": PID, "values": VALUES}, ["values"])),
        ("layer_select", "Select a layer and its owning texture set by persistent ID.", schema({"pid": PID}, ["pid"])),
        ("material_select", "Select a texture set using its persistent ID.", schema({"pid": STRING}, ["pid"])),
        ("smart_material", "Add a built-in smart material as an editable group. Names from guide/catalog.",
         schema({"name": STRING}, ["name"])),
        ("mask_add", "Add a native mask to a layer; value is initial coverage [0,1].",
         schema({"pid": PID, "value": {"type": "number", "minimum": 0, "maximum": 1}})),
        ("effect_add", "Add a native effect. Read EFFECTS and guide/catalog for kinds and parameters.",
         schema({"pid": PID, "kind": {"type": "string", "enum": SUPPORTED_EFFECTS},
                 "mask": BOOL, "params": {"type": "object"}}, ["kind"])),
        ("brush_uv_path", "Paint an undoable deterministic path of UV [u,v] samples; read UV_PAINTING first.",
         schema({"points": {"type": "array", "minItems": 1, "maxItems": 100000,
                            "items": {"type": "array", "items": NUMBER, "minItems": 2, "maxItems": 2}},
                 "brush": BRUSH, "seed": {"type": "integer"}}, ["points"])),
        ("undo", "Undo one native operation, not a whole AI request.", schema()),
        ("redo", "Redo one native operation.", schema()),
        ("project_save", "Save a portable project to an explicit path; requires file output enabled.",
         schema({"path": STRING}, ["path"])),
        ("textures_export", "Export texture maps; requires file output enabled.",
         schema({"folder": STRING, "template": STRING, "size": {"type": "integer", "minimum": 16, "maximum": 8192}}, ["folder"])),
    ]
    return [{"name": "strata_" + name, "description": desc, "inputSchema": spec,
             "annotations": {"readOnlyHint": name in ("inspect", "guide", "viewport"),
                             "destructiveHint": name in ("undo", "redo", "project_save", "textures_export"),
                             "openWorldHint": name in ("project_save", "textures_export")}}
            for name, desc, spec in definitions]


def validate(value, spec, path="arguments"):
    """Small strict validator for the JSON Schema subset above; no new dependency."""
    kind = spec.get("type")
    valid = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
             "string": lambda: isinstance(value, str), "boolean": lambda: isinstance(value, bool),
             "number": lambda: type(value) in (int, float) and math.isfinite(value),
             "integer": lambda: type(value) is int}
    if kind and not valid[kind]():
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError(f"{path}: invalid choice")
    if kind == "object":
        props = spec.get("properties", {})
        for key in spec.get("required", []):
            if key not in value:
                raise ValueError(f"{path}: missing {key}")
        for key, item in value.items():
            if key in props:
                validate(item, props[key], path + "." + key)
            elif spec.get("additionalProperties") is False:
                raise ValueError(f"{path}: unknown {key}")
    if kind == "array":
        if not spec.get("minItems", 0) <= len(value) <= spec.get("maxItems", 100000):
            raise ValueError(f"{path}: invalid length")
        for item in value:
            validate(item, spec.get("items", {}), path + "[]")
    if kind in ("number", "integer"):
        if value < spec.get("minimum", -math.inf) or value > spec.get("maximum", math.inf):
            raise ValueError(f"{path}: out of range")


class StrataTools:
    def __init__(self, engine, capture=None, on_save=None):
        self.engine, self.capture = engine, capture
        self.on_save = on_save
        self.registry = builtins()
        self.allow_output = False

    def call(self, name, arguments):
        specs = {tool["name"]: tool["inputSchema"] for tool in specifications()}
        if name not in specs:
            raise ValueError("Unknown Strata tool")
        validate(arguments, specs[name])
        # Reject NaN/Infinity even in open property/brush parameter dictionaries.
        json.dumps(arguments, allow_nan=False)
        e, a = self.engine, dict(arguments)
        if name == "strata_guide":
            return self.guide(a.get("topic", "overview"))
        if name == "strata_inspect":
            return self.inspect()
        if not e.sets:
            raise ValueError("Open a project in Strata first")
        if name == "strata_viewport":
            if self.capture is None:
                raise ValueError("Viewport capture unavailable in this host")
            return {"content": [{"type": "image", "mimeType": "image/png", "data": self.capture()}]}
        if name in ("strata_project_save", "strata_textures_export") and not self.allow_output:
            raise PermissionError("Enable 'Allow saving and export' in the AI Assistant panel first")
        if e.edit_active:
            raise RuntimeError("Finish the active property edit before the agent edits the project")
        if name == "strata_smart_material":
            from .presets import SMART_MATERIALS
            if a["name"] not in SMART_MATERIALS:
                raise ValueError("Unknown smart material; read guide/catalog")
            e.add_smart_material(a["name"], as_group=True)
            return self.inspect()
        if name == "strata_material_select":
            index = next((i for i, ts in enumerate(e.sets) if ts.pid == a["pid"]), None)
            if index is None:
                raise ValueError("Unknown texture set ID")
            e.set_active(index)
            return self.inspect()
        if name == "strata_mask_add":
            layer = _layer(e, a.get("pid"))
            if layer.has_mask:
                raise ValueError("Layer already has a mask; existing masks are not replaced")
            e.add_mask(a.get("value", 1.0), layer=layer)
            return {"pid": layer.pid}
        if name == "strata_effect_add":
            validate(a.get("params", {}), effect_schema(a["kind"]), "params")
            effect = e.add_effect(a["kind"], layer=_layer(e, a.get("pid")),
                                  mask=a.get("mask"), **a.get("params", {}))
            return {"pid": effect.pid, "kind": effect.kind}
        if name in ("strata_undo", "strata_redo"):
            getattr(e, name.removeprefix("strata_"))()
            return self.inspect()
        if name == "strata_layer_configure":
            allowed = {"name", "visible", "opacity", "color", "rough", "metal", "height", "normal",
                       "emissive", "opac", "enabled", "blend", "variation", "bump", "var_scale", "seed"}
            if not a["values"] or set(a["values"]) - allowed:
                raise ValueError("Unsupported layer properties; use native material values only")
        command = name.removeprefix("strata_").replace("_", ".", 1)
        if name == "strata_brush_uv_path":
            command = "brush.uv_path"
        if name == "strata_project_save":
            a["portable"] = True
        if name == "strata_brush_uv_path":
            previous = e.brush.to_dict()
            try:
                return self.registry.execute(e, command, a)
            except Exception:
                e.brush.load_dict(previous)
                raise
        result = self.registry.execute(e, command, a)
        if name == "strata_project_save" and self.on_save:
            self.on_save(result)
        return result

    def inspect(self):
        e = self.engine
        def layer_info(layer):
            info = {k: getattr(layer, k) for k in ("pid", "name", "kind", "visible", "opacity",
                                                   "color", "rough", "metal", "height")}
            info.update(mask=layer.has_mask,
                        effects=[{"pid": f.pid, "kind": f.kind} for f in layer.effects],
                        mask_effects=[{"pid": f.pid, "kind": f.kind} for f in layer.mask_effects],
                        children=[layer_info(c) for c in layer.children])
            return info
        return {"active_set": e.ts.pid if e.sets else None,
                "selected_layer": e.layer.pid if e.sets and e.layer else None,
                "file_output_enabled": self.allow_output,
                "sets": [{"pid": ts.pid, "name": ts.name, "resolution": ts.res,
                          "layers": [layer_info(l) for l in ts.layers]} for ts in e.sets]}

    @staticmethod
    def guide(topic):
        if topic == "overview":
            return {"instructions": GUIDE, "topics": ["catalog", *DOCS]}
        if topic == "catalog":
            from .presets import SMART_MATERIALS, MATERIALS
            from .layers import GENERATORS, MASK_EFFECTS, CONTENT_EFFECTS, EFFECT_DEFAULTS
            return {"smart_materials": list(SMART_MATERIALS), "materials": list(MATERIALS),
                    "generators": dict(enumerate(GENERATORS)), "mask_effects": list(MASK_EFFECTS),
                    "content_effects": list(CONTENT_EFFECTS), "effect_defaults": EFFECT_DEFAULTS,
                    "agent_effect_schemas": {kind: effect_schema(kind) for kind in SUPPORTED_EFFECTS}}
        if topic not in DOCS:
            raise ValueError("Unknown documentation topic")
        return {"topic": topic, "text": (Path(__file__).resolve().parents[1] / "docs" / DOCS[topic]).read_text(encoding="utf-8")}
