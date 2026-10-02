"""MCP: the tool table, the executor, and the real stdio → bridge path."""

import base64
import json
import subprocess
import sys
import threading
import time

from khervenoise import mcp_bridge, mcp_schema
from khervenoise.mcp_tools import McpToolExecutor


def test_every_tool_has_a_handler_and_a_class():
    for name in mcp_schema.TOOL_NAMES:
        assert hasattr(McpToolExecutor, f"_t_{name}"), name
    handlers = {n[3:] for n in dir(McpToolExecutor) if n.startswith("_t_")}
    assert handlers == set(mcp_schema.TOOL_NAMES)
    assert mcp_bridge._READ_ONLY_TOOLS <= set(mcp_schema.TOOL_NAMES)
    assert mcp_bridge._FILE_TOOLS <= set(mcp_schema.TOOL_NAMES)


def test_access_levels():
    assert mcp_bridge.tool_allowed("get_spectrum", "read")
    assert not mcp_bridge.tool_allowed("create_denoised", "read")
    assert mcp_bridge.tool_allowed("create_denoised", "edit")
    assert mcp_bridge._names_a_path("import_file", {"path": "/x"})


def test_check_args():
    assert mcp_schema.check_args("get_spectrum", {}) != ""
    assert mcp_schema.check_args("get_spectrum", {"name": "C1s"}) == ""
    assert "one of" in mcp_schema.check_args("auto_params", {"name": "a", "method": "x"})
    assert "unknown" in mcp_schema.check_args("list_methods", {"zz": 1})


def test_executor(window, vamas_path):
    ex = McpToolExecutor(window)
    assert ex.execute("import_file", {"path": vamas_path})["imported"] == ["Pt4f"]
    info = ex.execute("get_project_info", {})
    assert info["spectra"][0]["name"] == "Pt4f" and info["unsaved_changes"]
    pre = ex.execute("denoise_preview", {"name": "Pt4f", "method": "Wavelet",
                                         "params": {"k": 1.5}, "apply_to_view": True})
    assert pre["params"]["k"] == 1.5 and pre["residual_rms"] > 0
    assert window.panel.method == "Wavelet"
    bad = ex.execute("set_params", {"method": "VMD", "params": {"K": 4, "keep": 9}})
    assert "keep cannot exceed K" in bad["error"]
    out = ex.execute("create_denoised", {"method": "VMD"})
    assert out["created"] == ["Pt4f_vmd"]
    img = ex.execute("render_figure", {"dpi": 50})
    assert base64.b64decode(img["image_png_base64"])[:4] == b"\x89PNG"
    assert "error" in ex.execute("get_spectrum", {"name": "nope"})


def test_stdio_server_through_bridge(window, vamas_path, qapp):
    bridge = window._ensure_bridge()
    bridge.set_access("full")
    assert bridge.start()
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "import_file", "arguments": {"path": vamas_path}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "render_figure", "arguments": {"dpi": 40}}},
    ]
    proc = subprocess.Popen([sys.executable, "-m", "khervenoise.mcp_server"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    proc.stdin.write(("\n".join(json.dumps(m) for m in msgs) + "\n").encode())
    proc.stdin.close()
    lines = []
    reader = threading.Thread(target=lambda: lines.extend(
        proc.stdout.read().decode().splitlines()))
    reader.start()
    deadline = time.time() + 60
    while reader.is_alive() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    replies = {r["id"]: r for r in map(json.loads, lines)}
    assert replies[1]["result"]["serverInfo"]["name"] == "khervenoise"
    assert len(replies[2]["result"]["tools"]) == len(mcp_schema.TOOLS)
    assert not replies[3]["result"]["isError"]
    assert replies[4]["result"]["content"][0]["type"] == "image"
    assert window.document.names() == ["Pt4f"]
