"""Authenticated loopback RPC; worker threads never touch the engine or OpenGL."""
from __future__ import annotations

import hmac
import json
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .ai_tools import specifications


class Request:
    def __init__(self, payload):
        self.payload, self.done = payload, threading.Event()
        self.lock, self.cancelled, self.result = threading.Lock(), False, None


class Bridge:
    def __init__(self, tools, log=lambda text: None):
        self.tools, self.log = tools, log
        self.pending, self.token = queue.Queue(maxsize=32), secrets.token_urlsafe(32)
        self.closed = False
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Never log bearer credentials or project data.

            def do_POST(self):
                self.connection.settimeout(5)
                supplied = self.headers.get("Authorization", "")
                if (self.path != "/rpc" or self.headers.get("Origin") or
                        not hmac.compare_digest(supplied.encode(), ("Bearer " + bridge.token).encode())):
                    self.send_error(403)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 2 * 1024 * 1024:
                        raise ValueError("Invalid request size")
                    payload = json.loads(self.rfile.read(size))
                    request = Request(payload)
                    if bridge.closed:
                        raise RuntimeError("Strata connection is closed")
                    bridge.pending.put_nowait(request)
                    if bridge.closed:
                        request.cancelled = True
                        request.result = {"error": "Strata connection is closed"}
                        request.done.set()
                    if not request.done.wait(120):
                        with request.lock:
                            # A running native operation holds this lock. If it
                            # completed while we waited, return its actual result.
                            if not request.done.is_set():
                                request.cancelled = True
                                raise TimeoutError("Strata did not process the queued request; it was cancelled")
                    result = request.result
                except Exception as error:
                    result = {"error": str(error)}
                data = json.dumps(result, allow_nan=False).encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (OSError, TimeoutError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}/rpc"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="strata-ai-bridge")
        self.thread.start()

    def tick(self):
        """Called by the UI before drawing, outside an active artist gesture."""
        for _ in range(4):
            try:
                request = self.pending.get_nowait()
            except queue.Empty:
                return
            with request.lock:
                if request.cancelled or self.closed:
                    request.result = {"error": "Operation cancelled"}
                else:
                    try:
                        request.result = {"result": self.dispatch(request.payload)}
                    except Exception as error:
                        request.result = {"error": str(error)}
                        self.log(f"Tool failed: {error}")
                request.done.set()

    def dispatch(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Expected an RPC object")
        method, params = payload.get("method"), payload.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("Expected parameters object")
        if method == "tools/list":
            return {"tools": specifications()}
        if method == "tools/call":
            name = params.get("name")
            result = self.tools.call(name, params.get("arguments", {}))
            self.log("Completed: " + name)
            if isinstance(result, dict) and "content" in result:
                return result
            return {"content": [{"type": "text", "text": json.dumps(result, allow_nan=False)}]}
        raise ValueError("Unsupported RPC method")

    def close(self):
        self.closed = True
        self.token = secrets.token_urlsafe(32)
        while True:
            try:
                request = self.pending.get_nowait()
            except queue.Empty:
                break
            with request.lock:
                request.cancelled = True
                request.result = {"error": "Strata connection closed; queued operation cancelled"}
                request.done.set()
        # shutdown must not stall the render thread.
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        self.server.server_close()
