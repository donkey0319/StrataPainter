"""Bounded, inert project export configuration; loading never writes output files."""
import copy
import json
import re
from . import exporter


def validate(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid project export settings")
    if not value:
        return {}
    keys = {"template", "folder", "name", "format", "depth", "size", "padding", "dilation", "sets", "overrides"}
    if set(value) != keys or len(json.dumps(value, allow_nan=False)) > 1024 * 1024:
        raise ValueError("Invalid or oversized project export settings")
    template = value["template"]
    if not isinstance(template, dict) or not isinstance(template.get("maps"), list) or not 1 <= len(template["maps"]) <= 1024:
        raise ValueError("Invalid saved export template")
    for mapping in template["maps"]:
        exporter._mapping_check(mapping)
    for key in ("folder", "name"):
        if not isinstance(value[key], str) or len(value[key]) > 32768 or '\x00' in value[key]:
            raise ValueError("Invalid saved export destination or name")
    if (value["format"] not in [""] + list(exporter.FORMATS)
            or value["depth"] not in [""] + [depth for depths in exporter.FORMATS.values() for depth in depths]
            or value["size"] not in exporter.SIZES or value["padding"] not in exporter.PADDING
            or type(value["dilation"]) is not int or not 0 <= value["dilation"] <= 1024):
        raise ValueError("Invalid saved output format, size or padding")
    if (not isinstance(value["sets"], list) or len(value["sets"]) > 4096
            or any(not isinstance(pid, str) or not re.fullmatch(r"[0-9a-f]{32}", pid) for pid in value["sets"])):
        raise ValueError("Invalid saved export texture-set selection")
    overrides = value["overrides"]
    if not isinstance(overrides, dict) or len(overrides) > 1024:
        raise ValueError("Invalid saved export overrides")
    for name, options in overrides.items():
        if (not isinstance(name, str) or not isinstance(options, dict)
                or set(options) - {"enabled", "format", "depth", "size", "padding", "dilation"}):
            raise ValueError("Invalid saved output-map override")
        if ("enabled" in options and type(options["enabled"]) is not bool
                or "format" in options and options["format"] not in [""] + list(exporter.FORMATS)
                or "depth" in options and options["depth"] not in [""] + [depth for depths in exporter.FORMATS.values() for depth in depths]
                or "size" in options and options["size"] not in exporter.SIZES
                or "padding" in options and options["padding"] not in exporter.PADDING
                or "dilation" in options and (type(options["dilation"]) is not int or not 0 <= options["dilation"] <= 1024)):
            raise ValueError("Invalid saved output-map override value")
    return copy.deepcopy(value)
