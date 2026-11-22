#!/usr/bin/env python3
"""Native Codex TUI status line, served as a local stdio MCP resource."""

import json
import os
import subprocess
import sys
import time


URI = "ui://codex-usage/footer"
TOOL = {
    "name": "usage_statusline",
    "title": "Codex usage bars",
    "description": "Show model, location, context usage, and rate limit bars.",
    "inputSchema": {"type": "object", "properties": {}},
    "_meta": {"openai/ui": {"entrypoints": [{"type": "statusline", "resourceUri": URI}]}},
}
PARTS = " ▏▎▍▌▋▊▉"


def text(value, color=None):
    props = {"color": color} if color else {}
    return {"type": "text", "props": props, "children": [str(value)]}


def bar(label, value):
    try:
        percent = max(0, round(float(value)))
    except (TypeError, ValueError):
        return None
    color = "red" if percent >= 80 else "yellow" if percent >= 50 else "green"
    steps = max(1, min(100, percent) * 6 * 8 // 100) if percent else 0
    full, partial = divmod(steps, 8)
    filled = "█" * full + (PARTS[partial] if partial else "")
    empty = "░" * (6 - len(filled))
    return {"type": "row", "props": {"gap": 1}, "children": [
        text(label),
        {"type": "row", "props": {"gap": 0, "background": "surface"},
         "children": [text(filled, color), text(empty, "status-metadata")]},
        text(f"{percent}%", color),
    ]}


def remaining(reset):
    try:
        seconds = int(float(reset) - time.time())
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    if seconds >= 86400:
        return f"({seconds // 86400}d{seconds % 86400 // 3600}h)"
    if seconds >= 3600:
        return f"({seconds // 3600}h{seconds % 3600 // 60}m)"
    return f"({seconds // 60}m)"


def branch(cwd):
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "--no-optional-locks", "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True, text=True, timeout=0.2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    name = result.stdout.strip()
    return "…/" + name.rsplit("/", 1)[-1] if "/" in name else name


def render(state):
    thread = state.get("thread") or {}
    model = thread.get("model") or {}
    workspace = thread.get("workspace") or {}
    usage = thread.get("usage") or {}
    account = state.get("account") or {}
    children = []

    name = model.get("display_name") or model.get("id") or "Codex"
    reasoning = model.get("reasoning_level")
    children.append(text(f"{name} ({reasoning})" if reasoning else name, "status-model"))
    cwd = workspace.get("cwd")
    if isinstance(cwd, str) and cwd:
        children.append(text(os.path.basename(cwd.rstrip("/")) or "/", "status-path"))
        if current_branch := branch(cwd):
            children.append(text(f"⎇ {current_branch}", "status-branch"))

    context = (usage.get("context") or {}).get("used_percentage")
    if item := bar("ctx", context):
        children.append(item)

    snapshots = account.get("rate_limits") or []
    snapshot = next((item for item in snapshots if item.get("limit_id") == "codex"), None)
    if snapshot:
        for label, key in (("5h", "primary_limit"), ("7d", "secondary_limit")):
            window = snapshot.get(key) or {}
            if item := bar(label, window.get("used_percent")):
                children.append(item)
                if reset := remaining(window.get("resets_at")):
                    children.append(text(reset, "status-metadata"))

    return {"type": "row", "props": {"gap": 1, "wrap": "wrap"}, "children": children}


def respond(method, params):
    if method == "initialize":
        return {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "codex-usage-statusline", "version": "1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "tools/call":
        if params.get("name") != TOOL["name"]:
            raise ValueError("Unknown tool")
        return {"content": [{"type": "text", "text": URI}]}
    if method == "resources/list":
        return {"resources": [{"name": "footer", "uri": URI, "mimeType": "application/json"}]}
    if method == "resources/templates/list":
        return {"resourceTemplates": []}
    if method == "resources/read":
        if params.get("uri") != URI:
            raise ValueError("Unknown URI")
        state = (params.get("_meta") or {}).get("com.openai/codex-statusline-state") or {}
        return {"contents": [{"uri": URI, "mimeType": "application/json",
                             "text": json.dumps(render(state), ensure_ascii=False)}]}
    raise KeyError(method)


def main():
    for line in sys.stdin.buffer:
        reply = {"jsonrpc": "2.0", "id": None}
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or not isinstance(request.get("method"), str):
                reply["error"] = {"code": -32600, "message": "Invalid request"}
            elif "id" not in request:
                continue
            else:
                reply["id"] = request["id"]
                reply["result"] = respond(request["method"], request.get("params") or {})
        except json.JSONDecodeError:
            reply["error"] = {"code": -32700, "message": "Parse error"}
        except KeyError:
            reply["error"] = {"code": -32601, "message": "Method not found"}
        except (TypeError, ValueError, AttributeError):
            reply["error"] = {"code": -32602, "message": "Invalid parameters"}
        print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
