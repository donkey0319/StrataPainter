"""Command registry: every action in one list, so menus, shortcuts, the Ctrl+K command palette
and the shortcut editor stay in sync. Users can rebind any command (stored in settings.json).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from imgui_bundle import imgui

from .theme import V2, V4, TEXT_DIM

# ----------------------------------------------------------------------------- key names
_NAMED = {
    "Delete": "delete", "Tab": "tab", "Space": "space", "Escape": "escape", "Enter": "enter",
    "Backspace": "backspace", "Insert": "insert", "Home": "home", "End": "end",
    "PageUp": "page_up", "PageDown": "page_down", "Up": "up_arrow", "Down": "down_arrow",
    "Left": "left_arrow", "Right": "right_arrow", "[": "left_bracket", "]": "right_bracket",
    ",": "comma", ".": "period", "/": "slash", ";": "semicolon", "'": "apostrophe",
    "-": "minus", "=": "equal", "`": "grave_accent", "\\": "backslash",
}


def _key_enum(name: str):
    K = imgui.Key
    if len(name) == 1 and name.isalpha():
        return getattr(K, name.lower())
    if len(name) == 1 and name.isdigit():
        return getattr(K, "_" + name)
    if name.upper().startswith("F") and name[1:].isdigit():
        return getattr(K, "f" + name[1:])
    if name in _NAMED:
        return getattr(K, _NAMED[name])
    raise ValueError(f"Unknown key '{name}'")


def capturable_keys():
    names = [chr(c) for c in range(ord("A"), ord("Z") + 1)] + [str(d) for d in range(10)]
    names += [f"F{i}" for i in range(1, 13)] + list(_NAMED)
    return [(n, _key_enum(n)) for n in names if n not in ("Escape",)]


@dataclass(frozen=True)
class Chord:
    key: str
    ctrl: bool = False
    shift: bool = False
    alt: bool = False

    @staticmethod
    def parse(text: str) -> "Chord":
        parts = [p for p in text.replace(" ", "").split("+")]
        # allow a literal "+" key written as "Ctrl++"
        if text.endswith("++"):
            parts = parts[:-2] + ["+"]
        mods = {p.lower() for p in parts[:-1]}
        _key_enum(parts[-1])                       # validate
        return Chord(parts[-1], "ctrl" in mods, "shift" in mods, "alt" in mods)

    def __str__(self):
        return "+".join([m for m, on in (("Ctrl", self.ctrl), ("Shift", self.shift), ("Alt", self.alt)) if on]
                        + [self.key])

    def pressed(self, io, repeat=False) -> bool:
        if (io.key_ctrl, io.key_shift, io.key_alt) != (self.ctrl, self.shift, self.alt):
            return False
        return imgui.is_key_pressed(_key_enum(self.key), repeat)


@dataclass
class Command:
    id: str
    name: str
    category: str
    run: Callable[[], None]
    keys: list = field(default_factory=list)          # default bindings, e.g. ["Ctrl+S"]
    enabled: Optional[Callable[[], "bool | str"]] = None   # True, or a string saying why not
    checked: Optional[Callable[[], bool]] = None
    repeat: bool = False                               # key auto-repeat (brush size etc.)
    tip: str = ""
    in_palette: bool = True

    def state(self):
        """(enabled, reason)."""
        if self.enabled is None:
            return True, ""
        r = self.enabled()
        if isinstance(r, str):
            return (not r), r
        return bool(r), ""


class Registry:
    def __init__(self):
        self.cmds: dict[str, Command] = {}
        self.order: list[str] = []
        self.overrides: dict[str, list] = {}           # id -> ["Ctrl+X", ...] from settings

    def add(self, *args, **kw) -> Command:
        c = Command(*args, **kw)
        if c.id not in self.cmds:
            self.order.append(c.id)
        self.cmds[c.id] = c
        return c

    def __getitem__(self, cid) -> Command:
        return self.cmds[cid]

    def bindings(self, cid) -> list:
        keys = self.overrides.get(cid, self.cmds[cid].keys)
        out = []
        for k in keys:
            try:
                out.append(Chord.parse(k))
            except Exception:
                pass
        return out

    def shortcut(self, cid) -> str:
        b = self.bindings(cid)
        return str(b[0]) if b else ""

    def all_shortcuts(self, cid) -> str:
        return "  /  ".join(str(b) for b in self.bindings(cid))

    def run(self, cid, msg=None) -> bool:
        c = self.cmds[cid]
        ok, why = c.state()
        if not ok:
            if msg and why:
                msg(f"{c.name}: {why}")
            return False
        try:
            c.run()
        except MemoryError as error:
            if msg:
                msg(str(error))
            return False
        return True

    def dispatch(self, io, msg=None):
        """Fire commands whose shortcut was pressed this frame. Longest modifier sets win."""
        hits = []
        for cid in self.order:
            for ch in self.bindings(cid):
                if ch.pressed(io, self.cmds[cid].repeat):
                    hits.append(cid)
                    break
        for cid in hits[:1]:
            self.run(cid, msg)

    def conflicts(self, chord: Chord, except_id=None):
        return [c for c in self.order if c != except_id and chord in self.bindings(c)]


# ----------------------------------------------------------------------------- palette
def _score(query: str, text: str) -> int:
    """0 = no match. Every query word must appear; prefix and word-start matches rank higher."""
    q = query.lower().split()
    t = text.lower()
    if not q:
        return 1
    score = 0
    for w in q:
        i = t.find(w)
        if i < 0:
            return 0
        score += 3 if i == 0 else (2 if t[i - 1] in " :/(" else 1)
    return score


class Palette:
    """Ctrl+K: type to find and run any command."""

    def __init__(self):
        self.open_req = False
        self.is_open = False
        self.query = ""
        self.index = 0

    def request(self):
        self.open_req = True

    def draw(self, reg: Registry, msg, scale=1.0):
        if self.open_req:
            imgui.open_popup("##command_palette")
            self.open_req, self.query, self.index = False, "", 0
            self._focus = True
        vp = imgui.get_main_viewport()
        w = min(560 * scale, vp.size.x - 40)
        imgui.set_next_window_pos(V2(vp.pos.x + vp.size.x / 2, vp.pos.y + 70 * scale), imgui.Cond_.always, V2(0.5, 0))
        imgui.set_next_window_size(V2(w, 0))
        self.is_open = imgui.begin_popup("##command_palette")
        if not self.is_open:
            return
        if getattr(self, "_focus", False):
            imgui.set_keyboard_focus_here()
            self._focus = False
        imgui.set_next_item_width(-1)
        ch, self.query = imgui.input_text_with_hint("##q", "Type a command, layer action, material...", self.query)
        if ch:
            self.index = 0
        items = []
        for cid in reg.order:
            c = reg.cmds[cid]
            if not c.in_palette:
                continue
            s = _score(self.query, f"{c.category}: {c.name}")
            if s:
                items.append((-s, len(items), c))
        items.sort(key=lambda t: (t[0], t[1]))
        items = [c for _, _, c in items][:400]
        if imgui.is_key_pressed(imgui.Key.down_arrow):
            self.index = min(self.index + 1, max(len(items) - 1, 0))
        if imgui.is_key_pressed(imgui.Key.up_arrow):
            self.index = max(self.index - 1, 0)
        run = None
        if imgui.is_key_pressed(imgui.Key.enter) or imgui.is_key_pressed(imgui.Key.keypad_enter):
            if items:
                run = items[min(self.index, len(items) - 1)]
        if imgui.is_key_pressed(imgui.Key.escape):
            imgui.close_current_popup()
        line = imgui.get_text_line_height_with_spacing()
        imgui.begin_child("##list", V2(0, min(max(len(items), 1), 12) * (line + 2) + 8))
        right = imgui.get_cursor_pos().x + imgui.get_content_region_avail().x
        for i, c in enumerate(items):
            ok, why = c.state()
            imgui.push_id(c.id)
            sel = i == self.index
            if sel:
                imgui.set_scroll_here_y()
            if not ok:
                imgui.push_style_color(imgui.Col_.text, V4(*TEXT_DIM, 1))
            if imgui.selectable(f"{c.category}:  {c.name}", sel)[0]:
                run = c
            if not ok:
                imgui.pop_style_color()
            if why and imgui.is_item_hovered():
                imgui.set_tooltip(why)
            sc = reg.shortcut(c.id)
            if c.checked and c.checked():
                sc = ("on   " + sc) if sc else "on"
            if sc:
                imgui.same_line(right - imgui.calc_text_size(sc).x - 4)
                imgui.text_disabled(sc)
            imgui.pop_id()
        if not items:
            imgui.text_disabled("No matching command.")
        imgui.end_child()
        imgui.text_disabled("Enter: run   Up/Down: choose   Esc: close")
        if run is not None:
            imgui.close_current_popup()
        imgui.end_popup()
        if run is not None:
            reg.run(run.id, msg)
