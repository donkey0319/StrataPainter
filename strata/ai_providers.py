"""Streaming adapters for installed agents. Credentials remain with their CLIs."""
from __future__ import annotations

import json
from contextlib import nullcontext
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading

from .ai_tools import GUIDE


def hidden_process_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


class AgentRun:
    """One streamed turn; UI consumes events, never waits for the agent process."""
    def __init__(self, provider, executable, model, prompt, bridge, session=None, workspace=None):
        self.provider, self.executable, self.model = provider, executable, model
        self.prompt, self.bridge, self.session = prompt, bridge, session
        self.workspace = Path(workspace) if workspace else Path.home() / ".strata" / "ai_workspaces" / "default"
        self.events, self.cancelled = queue.Queue(), threading.Event()
        self.process, self.lock = None, threading.Lock()
        self.write_lock = threading.Lock()
        self.worker = threading.Thread(target=self.run, daemon=True, name="strata-ai-agent")
        self.worker.start()

    def emit(self, kind, text="", **extra):
        self.events.put({"kind": kind, "text": text, **extra})

    def stop(self):
        self.cancelled.set()
        # Windows must terminate the spawned MCP child too; don't block the UI.
        threading.Thread(target=self._terminate, daemon=True).start()

    def _terminate(self):
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None:
                return
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               **hidden_process_options())
            else:
                import signal
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def mcp_config(self):
        # ai_mcp.py is also directly executable, so no import-path assumptions.
        return {"command": sys.executable,
                "args": [str(Path(__file__).with_name("ai_mcp.py"))]}

    def run(self):
        try:
            executable = shutil.which(self.executable)
            if not executable:
                raise RuntimeError(f"Cannot find {self.executable}. Install/sign in to {self.provider}, or set its executable path in Connection.")
            if sys.platform == "win32" and Path(executable).suffix.lower() in (".cmd", ".bat"):
                raise RuntimeError("Choose the native agent .exe, not a .cmd/.bat wrapper")
            if getattr(sys, "frozen", False):
                raise RuntimeError("Embedded agents currently require Strata's Python source installation")
            # Claude session lookup is scoped to cwd. Keep it stable per project,
            # separate from the source repo and the user's asset directories.
            self.workspace.mkdir(parents=True, exist_ok=True)
            with nullcontext(str(self.workspace.resolve())) as cwd:
                command = self.codex_command(executable) if self.provider == "Codex" else self.claude_command(executable)
                options = hidden_process_options()
                if os.name != "nt":
                    options["start_new_session"] = True
                with self.lock:
                    if self.cancelled.is_set():
                        return
                    environment = dict(os.environ, STRATA_BRIDGE_URL=self.bridge.url,
                                       STRATA_BRIDGE_TOKEN=self.bridge.token)
                    self.process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.PIPE,
                                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                    text=True, encoding="utf-8", errors="replace", bufsize=1, **options)
                errors = []
                def read_errors():
                    for line in self.process.stderr:
                        errors.append(line.rstrip())
                        del errors[:-12]
                reader = threading.Thread(target=read_errors, daemon=True)
                reader.start()
                try:
                    if self.provider == "Codex":
                        self.run_codex(cwd)
                    else:
                        self.run_claude()
                    if not self.cancelled.is_set() and self.process.poll() not in (None, 0):
                        raise RuntimeError(f"{self.provider} exited with code {self.process.returncode}: " + "\n".join(errors)[-2000:])
                finally:
                    self._terminate()
                    self.process.wait(timeout=10)
                    for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                        stream.close()
        except Exception as error:
            if not self.cancelled.is_set():
                self.emit("error", str(error).replace(self.bridge.token, "[connection token]"))
        finally:
            self.emit("done", "Stopped; completed edits remain in native history." if self.cancelled.is_set() else "Ready")

    def codex_command(self, executable):
        config = self.mcp_config()
        config["env_vars"] = ["STRATA_BRIDGE_URL", "STRATA_BRIDGE_TOKEN"]
        args = [executable, "app-server"]
        for key, value in config.items():
            args += ["-c", "mcp_servers.strata." + key + "=" + json.dumps(value)]
        return args

    def claude_command(self, executable):
        args = [executable, "-p", "--verbose", "--output-format", "stream-json",
                "--include-partial-messages", "--strict-mcp-config", "--mcp-config",
                json.dumps({"mcpServers": {"strata": self.mcp_config()}}),
                "--tools", "", "--allowedTools", "mcp__strata__*",
                "--append-system-prompt", GUIDE]
        if self.session:
            args += ["--resume", self.session]
        if self.model:
            args += ["--model", self.model]
        return args

    def send(self, message):
        with self.write_lock:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()

    def answer(self, request_id, answers):
        self.send({"id": request_id, "result": {"answers": {
            key: {"answers": [value]} for key, value in answers.items()}}})

    def messages(self):
        for line in self.process.stdout:
            if self.cancelled.is_set():
                return
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                yield value

    def run_codex(self, cwd):
        self.send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "strata_painter", "title": "Strata Painter", "version": "1.0.0"}}})
        streamed, completed = set(), False
        for event in self.messages():
            ident, method, p = event.get("id"), event.get("method", ""), event.get("params", {})
            if ident is not None and method:
                if method in ("item/tool/requestUserInput", "tool/requestUserInput"):
                    self.emit("question", request_id=ident, questions=p.get("questions", []))
                    continue
                self.emit("notice", "Agent requested unsupported interaction: " + method)
                # This UI only exposes Strata tools, not interactive shell/file approvals.
                self.send({"id": ident, "error": {"code": -32601,
                           "message": "This client supports Strata tools only. Ask the user in chat."}})
                continue
            if "error" in event:
                raise RuntimeError(str(event["error"].get("message", event["error"])))
            if ident == 1:
                self.send({"method": "initialized", "params": {}})
                self.send({"id": 2, "method": "account/read", "params": {}})
            elif ident == 2:
                if not event.get("result", {}).get("account"):
                    raise RuntimeError("Sign in to Codex first: run 'codex login' in a terminal, then retry.")
                params = {"cwd": cwd, "approvalPolicy": "on-request", "sandbox": "read-only",
                          "developerInstructions": GUIDE}
                if self.model:
                    params["model"] = self.model
                if self.session:
                    params["threadId"] = self.session
                self.send({"id": 3, "method": "thread/resume" if self.session else "thread/start", "params": params})
            elif ident == 3:
                self.session = event["result"]["thread"]["id"]
                self.emit("session", self.session)
                self.send({"id": 4, "method": "turn/start", "params": {
                    "threadId": self.session, "input": [{"type": "text", "text": self.prompt}]}})
            elif method == "item/agentMessage/delta":
                item = p.get("itemId", "message")
                streamed.add(item)
                self.emit("delta", p.get("delta", ""), item=item)
            elif method == "item/completed":
                item = p.get("item", {})
                if item.get("type") == "agentMessage" and item.get("id") not in streamed:
                    self.emit("delta", item.get("text", ""), item=item.get("id", "message"))
            elif method == "turn/completed":
                turn = p.get("turn", {})
                if turn.get("error"):
                    raise RuntimeError(str(turn["error"]))
                if turn.get("status") == "failed":
                    raise RuntimeError("Codex turn failed")
                completed = True
                break
        if not completed and not self.cancelled.is_set():
            raise RuntimeError("Codex disconnected before completing the turn. Check its login and connection.")

    def run_claude(self):
        self.process.stdin.write(self.prompt)
        self.process.stdin.close()
        streamed, completed = False, False
        for event in self.messages():
            if event.get("session_id"):
                self.emit("session", event["session_id"])
            kind = event.get("type")
            if kind == "stream_event":
                inner = event.get("event", {})
                if inner.get("type") == "content_block_delta" and inner.get("delta", {}).get("type") == "text_delta":
                    streamed = True
                    self.emit("delta", inner["delta"].get("text", ""), item="claude")
            elif kind == "assistant" and not streamed:
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        self.emit("delta", block.get("text", ""), item="claude")
            elif kind == "result":
                completed = True
                if event.get("is_error"):
                    raise RuntimeError(event.get("result") or str(event.get("errors", "Claude turn failed")))
                if not streamed and event.get("result"):
                    # Most versions also emitted an assistant message; UI deduplicates final text.
                    self.emit("final", event["result"], item="claude")
        if not completed and not self.cancelled.is_set():
            raise RuntimeError("Claude disconnected before completing the turn. Run 'claude' in a terminal to check login.")
