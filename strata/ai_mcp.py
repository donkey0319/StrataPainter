"""Minimal stdio MCP adapter for a running Strata UI. No GPU/UI imports.

Run with the project's Python: python -m strata.ai_mcp
STRATA_BRIDGE_URL and STRATA_BRIDGE_TOKEN come from AI Assistant > Connection.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def rpc(method, params):
    url = os.environ.get("STRATA_BRIDGE_URL", "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path != "/rpc":
        raise ValueError("Start a Strata AI connection and supply its loopback URL")
    token = os.environ.get("STRATA_BRIDGE_TOKEN", "")
    if not token:
        raise ValueError("Missing Strata connection token")
    request = urllib.request.Request(url, json.dumps({"method": method, "params": params}).encode(),
                                     {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    # Do not send loopback credentials to configured HTTP proxies or redirects.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=125) as response:
        result = json.load(response)
    if "error" in result:
        raise RuntimeError(result["error"])
    return result["result"]


def handle(message, transport=rpc):
    if not isinstance(message, dict) or "id" not in message:
        return None
    ident, method = message["id"], message.get("method")
    try:
        if method == "initialize":
            requested = message.get("params", {}).get("protocolVersion", "2024-11-05")
            supported = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
            result = {"protocolVersion": requested if requested in supported else "2025-11-25",
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "strata-painter", "version": "1.0.0"},
                      "instructions": "Read strata_guide and strata_inspect before editing the live project."}
        elif method == "ping":
            result = {}
        elif method in ("resources/list", "prompts/list"):
            result = {"resources" if method.startswith("resources") else "prompts": []}
        elif method in ("tools/list", "tools/call"):
            try:
                result = transport(method, message.get("params", {}))
            except Exception as error:
                if method != "tools/call":
                    raise
                result = {"isError": True, "content": [{"type": "text", "text": str(error)}]}
        else:
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": ident, "result": result}
    except Exception as error:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32603, "message": str(error)}}


def main():
    for line in sys.stdin:
        try:
            if len(line) > 2 * 1024 * 1024:
                raise ValueError("MCP request too large")
            response = handle(json.loads(line))
        except (ValueError, TypeError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON request"}}
        if response is not None:
            print(json.dumps(response, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
