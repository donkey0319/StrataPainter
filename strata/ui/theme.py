"""Colours, sizes, fonts and icon glyphs for the Strata UI.

Layout follows Substance 3D Painter's default workspace so Painter users find things where
they expect them; the theme is neutral dark grey, with selections and highlights in light grey.
"""
from __future__ import annotations

import os

from imgui_bundle import imgui

V2, V4 = imgui.ImVec2, imgui.ImVec4

ACCENT = (0.80, 0.81, 0.83)         # highlight: text, outlines, slider grabs, check marks
ACCENT_HI = (0.92, 0.93, 0.94)
SEL_BG = (0.36, 0.37, 0.39)         # selected rows, tabs, active buttons
SEL_BG_HI = (0.43, 0.44, 0.46)      # ... hovered
SEL_BG_SOFT = (0.27, 0.28, 0.30)    # secondary selection (multi-select)
PAINT_COL = (0.74, 0.76, 0.80)      # paint-layer tag colour
FILL_COL = (0.85, 0.70, 0.40)       # fill-layer tag colour
WARN_COL = (0.95, 0.70, 0.35)
TEXT_DIM = (0.55, 0.57, 0.60)

_icons_loaded = False


def col32(r, g, b, a=1.0) -> int:
    return imgui.get_color_u32(V4(r, g, b, a))


def apply_theme():
    s = imgui.get_style()
    s.window_rounding = 0.0
    s.child_rounding = 3.0
    s.frame_rounding = 3.0
    s.popup_rounding = 4.0
    s.grab_rounding = 3.0
    s.tab_rounding = 3.0
    s.window_border_size = 1.0
    s.frame_padding = V2(6, 4)
    s.item_spacing = V2(6, 5)
    s.item_inner_spacing = V2(5, 4)
    s.window_padding = V2(8, 8)
    s.scrollbar_size = 12
    s.grab_min_size = 9
    s.indent_spacing = 14
    s.window_menu_button_position = imgui.Dir.none   # no tiny docking menu arrow on each tab bar
    C = imgui.Col_
    acc = V4(*ACCENT, 1.0)
    pal = {
        C.window_bg: (0.13, 0.135, 0.145, 1.0), C.child_bg: (0.115, 0.12, 0.13, 1.0),
        C.popup_bg: (0.14, 0.145, 0.155, 0.98), C.menu_bar_bg: (0.10, 0.105, 0.115, 1.0),
        C.border: (0.22, 0.23, 0.25, 1.0), C.frame_bg: (0.19, 0.2, 0.215, 1.0),
        C.frame_bg_hovered: (0.24, 0.25, 0.27, 1.0), C.frame_bg_active: (0.27, 0.28, 0.3, 1.0),
        C.title_bg: (0.10, 0.105, 0.115, 1.0), C.title_bg_active: (0.10, 0.105, 0.115, 1.0),
        C.title_bg_collapsed: (0.10, 0.105, 0.115, 1.0),
        C.header: (*SEL_BG, 0.9), C.header_hovered: (*SEL_BG_HI, 0.9),
        C.header_active: (*SEL_BG_HI, 1.0), C.button: (0.21, 0.22, 0.24, 1.0),
        C.button_hovered: (0.29, 0.30, 0.32, 1.0), C.button_active: (*SEL_BG_HI, 1.0),
        C.tab: (0.13, 0.135, 0.145, 1.0), C.tab_hovered: (*SEL_BG_HI, 1.0),
        C.tab_selected: (*SEL_BG, 1.0), C.tab_dimmed: (0.11, 0.115, 0.125, 1.0),
        C.tab_dimmed_selected: (*SEL_BG_SOFT, 1.0), C.text_selected_bg: (*SEL_BG_HI, 0.8),
        C.separator: (0.22, 0.23, 0.25, 1.0), C.text: (0.88, 0.89, 0.9, 1.0),
        C.text_disabled: (*TEXT_DIM, 1.0), C.docking_preview: (*ACCENT, 0.55),
        C.docking_empty_bg: (0.08, 0.085, 0.09, 1.0), C.resize_grip: (0, 0, 0, 0),
        C.table_row_bg_alt: (1, 1, 1, 0.025), C.nav_cursor: (*ACCENT, 1.0),
    }
    for k, v in pal.items():
        s.set_color_(k, V4(*v))
    s.set_color_(C.modal_window_dim_bg, V4(0.0, 0.0, 0.0, 0.45))
    s.set_color_(C.check_mark, acc)
    # slider grabs sit under the value text, so they stay mid grey to keep the numbers readable
    s.set_color_(C.slider_grab, V4(0.50, 0.51, 0.53, 1.0))
    s.set_color_(C.slider_grab_active, V4(0.62, 0.63, 0.65, 1.0))


def load_fonts(px: float = 15.0) -> bool:
    """Text font plus Font Awesome icons merged into it. Returns True if icons are available."""
    global _icons_loaded
    import imgui_bundle
    io = imgui.get_io()
    base = os.path.join(os.path.dirname(imgui_bundle.__file__), "assets", "fonts")
    for p in (os.path.join(base, "Roboto", "Roboto-Regular.ttf"), os.path.join(base, "DroidSans.ttf")):
        if os.path.exists(p):
            io.fonts.add_font_from_file_ttf(p, px)
            break
    fa = os.path.join(base, "Font_Awesome_6_Free-Solid-900.otf")
    if os.path.exists(fa):
        try:
            cfg = imgui.ImFontConfig()
            cfg.merge_mode = True
            cfg.glyph_min_advance_x = px            # icons line up in columns
            io.fonts.add_font_from_file_ttf(fa, px * 0.88, cfg)
            _icons_loaded = True
        except Exception:
            _icons_loaded = False
    return _icons_loaded


class _Icons:
    """ICON.paint etc. Falls back to short text if the icon font could not be loaded."""
    _map = {
        "paint": ("PAINTBRUSH", "P"), "erase": ("ERASER", "E"), "mask": ("CIRCLE_HALF_STROKE", "M"),
        "fill": ("FILL_DRIP", "F"), "smart": ("WAND_MAGIC_SPARKLES", "S"), "eye": ("EYE", "o"),
        "eye_off": ("EYE_SLASH", "-"), "trash": ("TRASH_CAN", "x"), "copy": ("COPY", "D"),
        "up": ("ARROW_UP", "^"), "down": ("ARROW_DOWN", "v"), "search": ("MAGNIFYING_GLASS", "?"),
        "cube": ("CUBE", "3D"), "image": ("IMAGE", "2D"), "split": ("TABLE_CELLS_LARGE", "|"),
        "sun": ("SUN", "*"), "history": ("CLOCK_ROTATE_LEFT", "H"), "log": ("TERMINAL", ">"),
        "keys": ("KEYBOARD", "K"), "gear": ("GEAR", "S"), "frame": ("EXPAND", "F"),
        "plus": ("PLUS", "+"), "open": ("FOLDER_OPEN", "O"), "save": ("FLOPPY_DISK", "S"),
        "export": ("FILE_EXPORT", "E"), "layers": ("LAYER_GROUP", "L"), "undo": ("ROTATE_LEFT", "<"),
        "redo": ("ROTATE_RIGHT", ">"), "info": ("CIRCLE_INFO", "i"), "palette": ("PALETTE", "M"),
        "hide": ("UP_RIGHT_AND_DOWN_LEFT_FROM_CENTER", "[]"), "display": ("DISPLAY", "D"),
        "box": ("BOX", "T"), "generator": ("MOUNTAIN", "G"), "swatch": ("SWATCHBOOK", "A"),
        "polyfill": ("DRAW_POLYGON", "4"), "smudge": ("HAND_POINTER", "5"), "clone": ("CLONE", "6"),
        "picker": ("EYE_DROPPER", "P"), "quickmask": ("MASK", "U"), "folder": ("FOLDER", "F"),
        "folder_open": ("FOLDER_OPEN", "F"), "caret_r": ("CARET_RIGHT", ">"), "caret_d": ("CARET_DOWN", "v"),
        "sym": ("ARROWS_LEFT_RIGHT", "L"), "lazy": ("FEATHER", "D"), "pause": ("PAUSE", "||"),
        "refresh": ("ARROWS_ROTATE", "R"), "import": ("FILE_IMPORT", "I"),
    }

    def __getattr__(self, name):
        glyph, fallback = self._map[name]
        if _icons_loaded:
            from imgui_bundle import icons_fontawesome_6 as FA
            return getattr(FA, "ICON_FA_" + glyph, fallback)
        return fallback


ICON = _Icons()
