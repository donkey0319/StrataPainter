"""Closing the window with unsaved changes asks to save first.

    xvfb-run -s "-screen 0 1600x960x24" python tests/unsaved_ui_check.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = os.environ["USERPROFILE"] = tempfile.mkdtemp(prefix="strata_unsaved_")

import glfw  # noqa: E402
from imgui_bundle import imgui  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strata import app as A  # noqa: E402

fails = []
SAVE_PATH = os.path.join(os.environ["HOME"], "quit_test.strata")


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


def popup_open():
    return imgui.is_popup_open("", imgui.PopupFlags_.any_popup_id)


class T(A.App):
    def __init__(self):
        self.script, self.frames = [], 0
        super().__init__(1600, 960)
        self._run_busy("Baking...", lambda: self._new_project("Rounded Cube", 512))
        self.steps = self.build()

    def key(self, k):
        io = imgui.get_io()
        io.add_key_event(k, True)
        self.script.append(lambda: io.add_key_event(k, False))

    def frame(self):
        self.frames += 1
        if self.frames > 600:
            check(False, "test finished in time")
            self._quit_now()
        while self.script:
            self.script.pop(0)()
        if self.engine.comp is not None and not self.pending and self.steps:
            self.steps.pop(0)()
        super().frame()

    def build(self):
        e = self.engine
        S = [lambda: None] * 3

        def clean_quit_closes():
            check(not e.modified, "fresh project has no unsaved changes")
            glfw.set_window_should_close(self.window, True)
            self._on_close_request(self.window)            # what the window close button runs
            check(glfw.window_should_close(self.window) and not self.open_quit,
                  "no changes: closing goes ahead without a prompt")
            glfw.set_window_should_close(self.window, False)
        S.append(clean_quit_closes)

        def edit():
            e.layer.opacity = 0.4
            e.dirty = True
        S.append(edit)

        def close_button():
            glfw.set_window_should_close(self.window, True)
            self._on_close_request(self.window)
            check(not glfw.window_should_close(self.window), "unsaved: window close is held back")
            check(self.open_quit, "unsaved: the save prompt is requested")
        S.append(close_button)
        S.append(lambda: check(popup_open(), "\"Unsaved Changes\" dialog is shown"))
        S.append(lambda: self.key(imgui.Key.escape))
        S.append(lambda: None)
        S.append(lambda: check(not popup_open() and not glfw.window_should_close(self.window) and e.modified,
                               "Cancel (Esc) keeps the app open with the changes"))

        def menu_quit():
            self.reg.run("file.quit")
            check(not glfw.window_should_close(self.window) and self.open_quit,
                  "File > Quit goes through the same prompt")
        S.append(menu_quit)
        S.append(lambda: None)

        def save_choice():
            self.project_path = SAVE_PATH          # skip the OS file dialog
            check(popup_open(), "dialog open again")
            self.key(imgui.Key.enter)
        S.append(save_choice)
        return S


app = T()
app.run()
check(app._quit_ok, "Save (Enter) quits after saving")
check(os.path.exists(SAVE_PATH), "the project file was written")
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
