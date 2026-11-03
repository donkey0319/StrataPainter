"""Visible estimates and configurable limits, without claiming driver memory usage."""
from imgui_bundle import imgui


class MemoryUI:
    def __init__(self, app):
        self.app = app
        self.resource = int(app.settings.get("gpu_texture_budget_mib", 5120))
        self.history = int(app.settings.get("history_budget_mib", 1536))
        self.steps = int(app.settings.get("history_steps", 24))
        self.app.engine.configure_memory(self.resource, self.history, self.steps)

    def draw(self):
        app, e = self.app, self.app.engine
        if not app._section("Memory and history", ["Texture budget", "History budget", "History steps", "Usage"]):
            return
        if app._row("Usage"):
            memory = e.gpu.memory
            imgui.text_wrapped(f"Textures: {memory.live_bytes / 1024**2:.1f} MiB; peak {memory.peak_bytes / 1024**2:.1f} MiB")
            imgui.text_wrapped(f"History: {e.history_usage() / 1024**2:.1f} MiB. Estimates exclude depth, buffers and driver overhead.")
            if e.memory_notice:
                imgui.text_wrapped(e.memory_notice)
        if app._row("Texture budget"):
            _, self.resource = imgui.slider_int("##texture_budget", self.resource, 64, 16384, "%d MiB")
        if app._row("History budget"):
            _, self.history = imgui.slider_int("##history_budget", self.history, 1, 8192, "%d MiB")
        if app._row("History steps"):
            _, self.steps = imgui.slider_int("##history_steps", self.steps, 1, 256)
            imgui.text_wrapped("Applying smaller history limits discards older undo steps.")
            if imgui.button("Apply memory limits"):
                try:
                    e.configure_memory(self.resource, self.history, self.steps)
                    app._memory_error = None
                    app.settings.update(gpu_texture_budget_mib=self.resource, history_budget_mib=self.history, history_steps=self.steps)
                    app._save_settings()
                except Exception as error:
                    app.msg(str(error))
        app._end_section()
