"""Dockable agent chat, project-scoped history and main-thread tool dispatch."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import queue
import sys

from imgui_bundle import imgui

from ..ai_bridge import Bridge
from ..ai_providers import AgentRun
from ..ai_tools import StrataTools
from .theme import V2


class AssistantUI:
    def __init__(self, app, config_dir):
        self.app = app
        self.history_dir = Path(config_dir) / "ai_history"
        self.workspace_dir = Path(config_dir) / "ai_workspaces"
        settings = app.settings.get("ai", {})
        self.provider = settings.get("provider", "Codex")
        if self.provider not in ("Codex", "Claude Code"):
            self.provider = "Codex"
        self.paths = {"Codex": settings.get("codex", "codex"), "Claude Code": settings.get("claude", "claude")}
        self.model = settings.get("model", "")
        self.messages, self.sessions = [], {}
        self.prompt, self.status = "", "Choose an agent, then send a request."
        self.tools = StrataTools(app.engine, self.capture, lambda path: setattr(app, "project_path", path))
        self.bridge, self.run = None, None
        self.document, self.scroll = None, False
        self.project_instance = None
        self.items, self.log_lines = {}, []
        self.questions = []
        self.history_dirty = False

    def record(self, role, text):
        self.messages.append({"role": role, "text": text[:40000]})
        self.messages = self.messages[-100:]
        self.scroll, self.history_dirty = True, True

    def log(self, text):
        self.log_lines.append(text)
        self.log_lines = self.log_lines[-30:]
        self.record("Action", text)

    def settings(self):
        self.app.settings["ai"] = {"provider": self.provider, "model": self.model,
                                   "codex": self.paths["Codex"], "claude": self.paths["Claude Code"]}

    def save_history(self):
        if not self.document or not self.history_dirty:
            return
        try:
            self.history_dir.mkdir(parents=True, exist_ok=True)
            path = self.history_dir / (self.document + ".json")
            temporary = path.with_suffix(".tmp")
            messages = self.messages[-100:]
            while True:
                data = json.dumps({"messages": messages, "sessions": self.sessions}, ensure_ascii=False)
                if len(data.encode("utf-8")) <= 4 * 1024 * 1024 or not messages:
                    break
                messages = messages[1:]
            temporary.write_text(data, encoding="utf-8")
            temporary.replace(path)
            self.history_dirty = False
        except OSError as error:
            self.status = f"Could not save local chat history: {error}"

    def connection(self):
        if self.bridge is None:
            self.bridge = Bridge(self.tools, self.log)
        return self.bridge

    def stop(self):
        self.questions = []
        if self.run:
            self.run.stop()
        if self.bridge:
            self.bridge.close()
            self.bridge = None
        self.status = "Stopped. Completed edits remain in native undo history."

    def close(self):
        self.stop()
        self.settings()
        self.save_history()

    def tick(self):
        e = self.app.engine
        identity = ":".join(ts.pid for ts in e.sets)
        document = hashlib.sha256(identity.encode()).hexdigest() if identity else None
        instance = (id(e.mesh), id(e.sets))
        if document != self.document or instance != self.project_instance:
            self.save_history()
            self.stop()
            self.run = None
            self.document, self.messages, self.sessions, self.items = document, [], {}, {}
            self.project_instance, self.prompt = instance, ""
            self.tools.allow_output = False
            self.status = "Ready. Inspect the project or describe the changes you want."
            if document:
                try:
                    path = self.history_dir / (document + ".json")
                    if path.stat().st_size > 5 * 1024 * 1024:
                        raise ValueError("History exceeds size limit")
                    history = json.loads(path.read_text(encoding="utf-8"))
                    self.messages = [{"role": str(m["role"]), "text": str(m["text"])[:40000]}
                                     for m in history.get("messages", [])[-100:]]
                    self.sessions = {k: v for k, v in history.get("sessions", {}).items()
                                     if k in ("Codex", "Claude Code") and isinstance(v, str)}
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    pass
                self.scroll = True
        # Never commit an artist's half-finished slider gesture or brush stroke.
        gesture = (e.edit_active or e._stroke is not None or e._tile_stroke is not None
                   or getattr(self.app, "drag", None) is not None or self.app.pending
                   or getattr(self.app, "_property_edit_key", None) is not None)
        if self.bridge and not gesture:
            self.bridge.tick()
        if self.run:
            for _ in range(300):
                try:
                    event = self.run.events.get_nowait()
                except queue.Empty:
                    break
                kind, text = event["kind"], event["text"]
                if kind == "session":
                    self.sessions[self.run.provider] = text
                    self.history_dirty = True
                elif kind in ("delta", "final"):
                    item = event.get("item", "message")
                    if item not in self.items:
                        self.record("Assistant", "")
                        self.items[item] = self.messages[-1]
                    message = self.items[item]
                    if kind == "final":
                        message["text"] = text[:40000]
                    else:
                        message["text"] = (message["text"] + text)[:40000]
                    self.scroll, self.history_dirty = True, True
                elif kind == "error":
                    self.record("Error", text)
                    self.status = text
                elif kind == "notice":
                    self.log(text)
                elif kind == "question":
                    self.questions.append({**event, "answers": {}})
                    self.status = "The agent needs your response below."
                elif kind == "done":
                    if not any(m["role"] == "Error" for m in self.messages[-1:]):
                        self.status = text
                    self.run = None
                    self.questions = []
                    self.save_history()
                    break

    def send(self, prompt=None):
        text = (self.prompt if prompt is None else prompt).strip()
        if self.run or not text or not self.document:
            return
        self.settings()
        self.app._save_settings()
        self.record("You", text)
        self.save_history()
        self.prompt, self.items, self.status = "", {}, "Working..."
        self.run = AgentRun(self.provider, self.paths[self.provider], self.model.strip(), text,
                            self.connection(), self.sessions.get(self.provider),
                            self.workspace_dir / self.document / self.provider.replace(" ", "-"))

    def capture(self):
        """Render a fresh 3D view, rather than stale pixels or other chat windows."""
        from PIL import Image
        e, ctx = self.app.engine, self.app.ctx
        old_size, old_fbo, old_viewport = e.view_size, ctx.fbo, ctx.viewport
        width = 768
        height = max(128, min(768, round(width * old_size[1] / max(old_size[0], 1))))
        target = ctx.simple_framebuffer((width, height), components=3)
        try:
            target.use()
            target.clear(.08, .085, .09)
            e.update_view(width, height)
            target.use()
            e.render((0, 0, width, height))
            image = Image.frombytes("RGB", (width, height), target.read(components=3, alignment=1))
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("ascii")
        finally:
            try:
                e.update_view(*old_size)
            finally:
                old_fbo.use()
                ctx.viewport = old_viewport
                target.release()

    def external_config(self):
        if getattr(sys, "frozen", False):
            raise RuntimeError("MCP currently requires Strata's Python source installation")
        bridge = self.connection()
        return json.dumps({"mcpServers": {"strata": {
            "command": sys.executable,
            "args": [str(Path(__file__).resolve().parents[1] / "ai_mcp.py")],
            "env": {"STRATA_BRIDGE_URL": bridge.url, "STRATA_BRIDGE_TOKEN": bridge.token}}}}, indent=2)

    def answer(self, request, answers):
        if not self.run:
            return
        try:
            self.run.answer(request["request_id"], answers)
            self.questions.remove(request)
            self.status = "Working..."
        except (OSError, ValueError) as error:
            self.status = str(error)

    def draw(self):
        busy = self.run is not None
        imgui.begin_disabled(busy)
        _, index = imgui.combo("Agent", 0 if self.provider == "Codex" else 1, ["Codex", "Claude Code"])
        self.provider = ["Codex", "Claude Code"][index]
        if imgui.collapsing_header("Connection"):
            _, self.paths[self.provider] = imgui.input_text("Executable", self.paths[self.provider])
            _, self.model = imgui.input_text("Model (optional)", self.model)
            imgui.text_wrapped("Uses your installed agent and its login. Sign in with 'codex login' or 'claude' in a terminal first.")
            imgui.text_wrapped("Messages, project details and requested viewport images go to the selected provider. Chat history stays in Strata's local settings folder.")
            if imgui.button("Copy external MCP connection"):
                try:
                    imgui.set_clipboard_text(self.external_config())
                    self.status = "Connection copied. Add it to your agent's MCP settings; keep Strata open."
                except Exception as error:
                    self.status = str(error)
            imgui.text_wrapped("The copied connection controls this project. Stop disconnects it; reconnect after reopening Strata or switching projects.")
        imgui.end_disabled()
        _, self.tools.allow_output = imgui.checkbox("Allow saving and export", self.tools.allow_output)
        imgui.text_wrapped(self.status[:500])
        if self.questions:
            request = self.questions[0]
            for question in request["questions"]:
                ident = question["id"]
                imgui.push_id(ident)
                imgui.text_wrapped(question["question"])
                for option in question.get("options") or []:
                    if imgui.radio_button(option["label"], request["answers"].get(ident) == option["label"]):
                        request["answers"][ident] = option["label"]
                    if imgui.is_item_hovered():
                        imgui.set_tooltip(option.get("description", ""))
                flags = imgui.InputTextFlags_.password if question.get("isSecret") else 0
                changed, value = imgui.input_text("Response", request["answers"].get(ident, ""), flags)
                if changed:
                    request["answers"][ident] = value
                imgui.pop_id()
            imgui.begin_disabled(any(not request["answers"].get(q["id"]) for q in request["questions"]))
            if imgui.button("Reply to agent"):
                self.answer(request, request["answers"])
            imgui.end_disabled()
        height = max(100, imgui.get_content_region_avail().y - 150 * self.app.ui_scale)
        imgui.begin_child("##ai_chat", V2(0, height), imgui.ChildFlags_.borders)
        for message in self.messages:
            imgui.text_disabled(message["role"])
            imgui.text_wrapped(message["text"])
            imgui.spacing()
        if self.scroll:
            imgui.set_scroll_here_y(1.0)
            self.scroll = False
        imgui.end_child()
        imgui.begin_disabled(busy or self.document is None)
        _, self.prompt = imgui.input_text_multiline("##ai_prompt", self.prompt, V2(-1, 65 * self.app.ui_scale))
        if imgui.button("Send"):
            self.send()
        imgui.same_line()
        if imgui.button("Inspect view"):
            self.send("Inspect the live project and capture its viewport. Describe the material and suggest useful next edits.")
        imgui.end_disabled()
        imgui.same_line()
        if imgui.button("Stop"):
            self.stop()
        imgui.begin_disabled(busy)
        if imgui.button("New chat"):
            self.messages, self.sessions, self.items = [], {}, {}
            self.history_dirty = True
            self.save_history()
        imgui.end_disabled()
        imgui.same_line()
        if imgui.button("Undo last edit"):
            # Stop first so a queued operation cannot race the user's undo.
            self.stop()
            self.app.engine.undo()
        self.settings()
