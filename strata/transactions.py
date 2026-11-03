"""CPU-only editable-property snapshots with nested object identity preservation."""
from __future__ import annotations

import copy
from dataclasses import dataclass, fields, is_dataclass

_EXCLUDED = {"uid", "pid", "archive_id", "tex", "mask_tex", "children", "effects", "mask_effects", "expanded", "raster_res"}
_PLAIN_FIELDS = {"Engine": ("normal_strength", "user_channels", "shader_workflow"), "TextureSet": ("name", "description")}


@dataclass(eq=False)
class ObjectState:
    target: object
    values: dict


def editable_fields(target):
    if is_dataclass(target):
        excluded = _EXCLUDED | ({"kind"} if type(target).__name__ in ("Layer", "Effect") else set())
        return tuple(f.name for f in fields(target) if f.name not in excluded and not f.name.startswith("_"))
    allowed = _PLAIN_FIELDS.get(type(target).__name__)
    if allowed is None:
        raise TypeError(f"Unsupported editable object: {type(target).__name__}")
    return allowed


def _capture(value):
    if is_dataclass(value):
        return ObjectState(value, capture_properties(value))
    if isinstance(value, dict):
        return {k: _capture(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_capture(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_capture(v) for v in value)
    return copy.deepcopy(value)


def capture_properties(target):
    return {name: _capture(getattr(target, name)) for name in editable_fields(target)}


def _restore(value):
    if isinstance(value, ObjectState):
        restore_properties(value.target, value.values)
        return value.target
    if isinstance(value, dict):
        return {k: _restore(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_restore(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_restore(v) for v in value)
    return copy.deepcopy(value)


def restore_properties(target, state):
    for key, value in state.items():
        setattr(target, key, _restore(value))


def properties_equal(first, second):
    if isinstance(first, ObjectState) or isinstance(second, ObjectState):
        return (isinstance(first, ObjectState) and isinstance(second, ObjectState) and
                type(first.target) is type(second.target) and properties_equal(first.values, second.values))
    if isinstance(first, dict) or isinstance(second, dict):
        return (isinstance(first, dict) and isinstance(second, dict) and first.keys() == second.keys() and
                all(properties_equal(first[k], second[k]) for k in first))
    if isinstance(first, (list, tuple)) or isinstance(second, (list, tuple)):
        return (isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)) and
                len(first) == len(second) and all(properties_equal(a, b) for a, b in zip(first, second)))
    try:
        result = first == second
        return bool(result.all()) if hasattr(result, "all") else bool(result)
    except (TypeError, ValueError):
        return False


def _assign(current, value):
    """Replace values while retaining existing nested dataclass instances."""
    if is_dataclass(current):
        if is_dataclass(value) and type(value) is type(current):
            source = {name: getattr(value, name) for name in editable_fields(value)}
        elif isinstance(value, dict):
            source = value
        else:
            raise TypeError(f"Expected {type(current).__name__} or property mapping")
        allowed = set(editable_fields(current))
        if set(source) - allowed:
            raise ValueError("Unknown or protected nested property")
        for key, item in source.items():
            setattr(current, key, _assign(getattr(current, key), item))
        return current
    if isinstance(current, dict) and isinstance(value, dict):
        return {k: _assign(current[k], v) if k in current else copy.deepcopy(v) for k, v in value.items()}
    return copy.deepcopy(value)


class EditTransaction:
    """Metadata transaction. GPU storage and layer membership stay engine-owned."""
    def __init__(self, label="Edit"):
        self.label = str(label)
        self.before_states = []

    def touch(self, target):
        if not any(obj is target for obj, _ in self.before_states):
            self.before_states.append((target, capture_properties(target)))

    def apply(self, target, changes):
        allowed = set(editable_fields(target))
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError("Unknown or protected properties: " + ", ".join(sorted(invalid)))
        before = capture_properties(target)
        self.touch(target)
        try:
            for key, value in changes.items():
                setattr(target, key, _assign(getattr(target, key), value))
        except Exception:
            restore_properties(target, before)
            raise
        return not properties_equal(before, capture_properties(target))

    @property
    def changed(self):
        return any(not properties_equal(state, capture_properties(target)) for target, state in self.before_states)

    def cancel(self):
        # Child targets can also be captured individually; restore parents last.
        for target, state in reversed(self.before_states):
            restore_properties(target, state)
