"""MCP (Model Context Protocol) stdio server for KherveNoise.

This module is the *client-facing half* of KherveNoise's MCP support
(the architecture of KhervePlot / KherveMol / KherveCAD).
It speaks JSON-RPC 2.0 over stdin/stdout — the transport every MCP host
(Claude Desktop, Claude Code, Cursor, Zed, Continue, …) knows how to
launch — and forwards each ``tools/call`` to a running KherveNoise
window over a loopback socket (see ``mcp_bridge.py``).

The split matters: the tools drive the live denoising panel and its
matplotlib figure, so they must run on the application's GUI thread.
The MCP host, by contrast, wants to spawn a short-lived subprocess it
owns.  This file is that subprocess; it imports **no Qt and no
third-party package of its own** — only the standard library — so it
answers ``initialize`` immediately whether or not the application is
up, and works from any Python that can see the checkout.

Run it directly with::

    python -m khervenoise.mcp_server

or, for a frozen build::

    python KherveNoise.py --mcp-server

Copyright (C) 2026 Gwilherm Kerherve

Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import sys
from typing import Any, List, Optional


# ── Protocol constants ─────────────────────────────────────────────

#: Spec revisions we know how to speak.  We echo the client's choice
#: when it is one of these, otherwise we answer with our newest.
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL = SUPPORTED_PROTOCOLS[0]

SERVER_NAME = "khervenoise"

#: Endpoint file written by the in-app bridge; names host, port, token.
ENDPOINT_FILENAME = "mcp-bridge.json"

STATE_DIR_NAME = "KherveNoise"

_CONNECT_TIMEOUT = 5.0    # seconds to establish the bridge socket
_CALL_TIMEOUT = 300.0     # a VMD batch over many spectra is slow


# ── Endpoint discovery ─────────────────────────────────────────────

def state_dir() -> str:
    """Directory holding KherveNoise's per-user runtime state.

    Kept free of Qt so both halves of the MCP stack agree on the path
    without the stdio server having to import Qt.
    ``KHERVENOISE_STATE_DIR`` overrides it (the tests use a temp folder).
    """
    override = os.environ.get("KHERVENOISE_STATE_DIR")
    if override:
        return override
    if sys.platform.startswith("win"):
        base = (os.environ.get("LOCALAPPDATA")
                or os.path.expanduser("~\\AppData\\Local"))
        return os.path.join(base, STATE_DIR_NAME)
    if sys.platform == "darwin":
        return os.path.expanduser(
            f"~/Library/Application Support/{STATE_DIR_NAME}")
    base = (os.environ.get("XDG_CONFIG_HOME")
            or os.path.expanduser("~/.config"))
    return os.path.join(base, STATE_DIR_NAME)


def endpoint_path() -> str:
    """Full path of the bridge endpoint description file."""
    return os.path.join(state_dir(), ENDPOINT_FILENAME)


def read_endpoint(path: Optional[str] = None) -> Optional[dict]:
    """Load the endpoint file, or None when the app is not serving."""
    try:
        with open(path or endpoint_path(), "r", encoding="utf-8") as fh:
            info = json.load(fh)
    except Exception:
        return None
    if not isinstance(info, dict) or "port" not in info:
        return None
    return info


_NOT_RUNNING = (
    "KherveNoise is not reachable.\n\n"
    "The MCP server drives a live KherveNoise window, so the "
    "application must be running with its bridge enabled:\n"
    "  1. Start KherveNoise.\n"
    "  2. Enable AI > Connect to Claude (MCP).\n"
    "Then retry — no need to restart this MCP connection."
)


class BridgeError(RuntimeError):
    """Raised when the running application cannot be reached."""


#: Sent to the client on initialize.  The host writes its own system
#: prompt, so everything a model must know before working in someone
#: else's open project has to travel with the connection.
_INSTRUCTIONS = """\
These tools drive a LIVE KherveNoise window — the Spectral Denoising tool \
of KherveFitting as a program of its own. It denoises spectra (XPS, Raman, \
FTIR, XAS, EELS…) WITHOUT training data, one spectrum at a time, with \
three methods. Everything you do appears in front of the user.

Start here:
- get_project_info FIRST: every spectrum by NAME (C1s, O1s, Survey, \
C1s_vmd…), its points and x range, which one is on screen, the method and \
parameters in the controls. Every other tool addresses spectra by name.
- import_file reads Excel (KherveFitting layout), VAMAS (.vms), a \
two-column data file (.asc/.txt/.dat/.xy/.csv) or an instrument file \
(Thermo Avantage/VGD/AVG, Kratos, PHI .spe/.pro, Scienta, MRS, \
VG-Microtech, Igor, Diamond, SDP) and ADDS its spectra.

The three methods (list_methods gives every parameter and its range):
- "VMD" (default) — Variational Mode Decomposition: K band-limited modes, \
keep the `keep` lowest-frequency ones; `alpha` is the bandwidth penalty.
- "Wavelet" — wavelet shrinkage: `wavelet` (db4, db8, sym4, sym8, coif5), \
`level`, `mode` (soft|hard), threshold scale `k` (higher = smoother).
- "FFT filter" — flat-topped half-Gaussian low-pass: `cutoff` coefficient \
n and `slope` (higher = sharper roll-off).
Each works on the spectrum minus the straight line joining its end points.

Working pattern:
1. auto_params gives the recommended parameters for a spectrum and \
method (the same rule as the Auto button) — start from those.
2. denoise_preview computes the result WITHOUT changing anything and \
reports the residual RMS and SNR; `apply_to_view` shows it on screen. \
A good result has a structureless residual: if peaks appear in the \
residual the filter is too strong (keep more modes, lower k, raise the \
cut-off).
3. render_figure returns a PNG of the three panels (transform, what is \
kept, Raw vs Denoised + residual). LOOK AT IT before you report.
4. create_denoised writes new spectra "<name>_vmd|_wav|_fft" (one per \
source, originals never change), with auto parameters per spectrum or \
the parameters you pass.
5. export_khervefitting writes a workbook KherveFitting opens directly; \
export_csv writes plain columns. save_project writes the .knoise file.

Working rules:
- Each changing call is ONE undo step: the user gets their data back \
with a single Ctrl+Z. open_project refuses to drop unsaved work unless \
you pass discard_unsaved_changes — offer to save instead.
- The user controls what you may do (AI > Connect to Claude). A refusal \
naming an access level is their setting, not a bug — say what you \
needed rather than working around it.
"""


# ── Bridge client ──────────────────────────────────────────────────

class BridgeClient:
    """Line-delimited JSON client for the in-app bridge.

    Connects lazily and reconnects on demand so that the MCP host may
    start this process before (or after) KherveNoise itself, and so a
    restart of the application does not require a restart of the host.
    """

    def __init__(self, endpoint_file: Optional[str] = None):
        self._endpoint_file = endpoint_file
        self._sock: Optional[socket.socket] = None
        self._buf = b""
        self._token = ""
        self._next_id = 0

    # ── Connection handling ─────────────────────────────────────

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._buf = b""

    def _connect(self):
        info = read_endpoint(self._endpoint_file)
        if info is None:
            raise BridgeError(_NOT_RUNNING)
        self._token = str(info.get("token", ""))
        host = str(info.get("host", "127.0.0.1"))
        port = int(info["port"])
        try:
            sock = socket.create_connection(
                (host, port), timeout=_CONNECT_TIMEOUT)
        except OSError as exc:
            # A stale endpoint file (app killed without cleanup) looks
            # exactly like "not running" from here — say so plainly
            # rather than leaking a connection-refused traceback.
            raise BridgeError(f"{_NOT_RUNNING}\n\n(socket error: {exc})")
        sock.settimeout(_CALL_TIMEOUT)
        self._sock = sock
        self._buf = b""

    def _readline(self) -> bytes:
        assert self._sock is not None
        while b"\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise BridgeError(
                    "KherveNoise closed the connection mid-request. "
                    "The application may have quit.")
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line

    def request(self, method: str, params: Optional[dict] = None) -> Any:
        """Send one request, returning its ``result`` payload."""
        for attempt in (0, 1):
            if self._sock is None:
                self._connect()
            self._next_id += 1
            payload = {
                "id": self._next_id,
                "token": self._token,
                "method": method,
                "params": params or {},
            }
            try:
                assert self._sock is not None
                self._sock.sendall(
                    (json.dumps(payload) + "\n").encode("utf-8"))
                line = self._readline()
            except BridgeError:
                self.close()
                if attempt == 0:
                    continue          # app restarted: reconnect once
                raise
            except OSError as exc:
                self.close()
                if attempt == 0:
                    continue
                raise BridgeError(f"Bridge I/O error: {exc}")
            try:
                reply = json.loads(line.decode("utf-8"))
            except Exception:
                self.close()
                raise BridgeError("Malformed reply from KherveNoise.")
            if reply.get("error"):
                raise BridgeError(str(reply["error"]))
            return reply.get("result")
        raise BridgeError(_NOT_RUNNING)


# ── Result shaping ─────────────────────────────────────────────────

#: Key a tool result uses to hand back a rendered picture.  The figure
#: travels to the model as a real MCP image block.
IMAGE_KEY = "image_png_base64"


def tool_content(result: Any) -> List[dict]:
    """MCP content blocks for a bridge tool result.

    A result carrying a PNG becomes an image block (plus the rest of
    the result as text), so the model can actually look at the figure.
    """
    if isinstance(result, dict) and result.get(IMAGE_KEY):
        data = str(result[IMAGE_KEY])
        rest = {k: v for k, v in result.items() if k != IMAGE_KEY}
        blocks: List[dict] = [{"type": "image", "data": data,
                               "mimeType": "image/png"}]
        if rest:
            blocks.append({"type": "text",
                           "text": json.dumps(rest, indent=2,
                                              default=str)})
        return blocks
    return [{"type": "text",
             "text": json.dumps(result, indent=2, default=str)}]


def valid_png_b64(data: str) -> bool:
    """True when *data* decodes to something with a PNG signature."""
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:
        return False
    return raw[:8] == b"\x89PNG\r\n\x1a\n"


# ── MCP server ─────────────────────────────────────────────────────

def _log(msg: str):
    """Diagnostics go to stderr — stdout carries the protocol."""
    sys.stderr.write(f"[khervenoise-mcp] {msg}\n")
    sys.stderr.flush()


class McpServer:
    """Minimal, dependency-free MCP server over stdio."""

    def __init__(self, bridge: BridgeClient):
        self._bridge = bridge
        self._tools_cache: Optional[List[dict]] = None

    # ── Dispatch ────────────────────────────────────────────────

    def handle(self, msg: dict) -> Optional[dict]:
        """Handle one JSON-RPC message; None means 'no reply'."""
        method = msg.get("method")
        msg_id = msg.get("id")
        if method is None:                    # a response — ignore
            return None
        try:
            if method == "initialize":
                result = self._initialize(msg.get("params") or {})
            elif method in ("notifications/initialized",
                            "notifications/cancelled",
                            "initialized"):
                return None                   # notifications: no reply
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self._list_tools()}
            elif method == "tools/call":
                result = self._call_tool(msg.get("params") or {})
            elif method in ("resources/list", "resources/templates/list"):
                # Declared empty rather than unsupported so hosts that
                # probe every capability do not surface an error.
                key = ("resourceTemplates"
                       if method.endswith("templates/list")
                       else "resources")
                result = {key: []}
            elif method == "prompts/list":
                result = {"prompts": []}
            else:
                if msg_id is None:
                    return None
                return _error(msg_id, -32601, f"Unknown method: {method}")
        except BridgeError as exc:
            if msg_id is None:
                return None
            return _error(msg_id, -32000, str(exc))
        except Exception as exc:              # never take the loop down
            if msg_id is None:
                return None
            return _error(msg_id, -32603, f"Internal error: {exc}")
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    # ── Methods ─────────────────────────────────────────────────

    def _initialize(self, params: dict) -> dict:
        asked = params.get("protocolVersion")
        version = (asked if asked in SUPPORTED_PROTOCOLS
                   else LATEST_PROTOCOL)
        # Best-effort: the app may not be up yet, and initialize must
        # never fail for that reason.
        app_version = "unknown"
        try:
            status = self._bridge.request("get_status")
            app_version = str((status or {}).get("version", "unknown"))
        except Exception:
            pass
        return {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {},
                "prompts": {},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "title": "KherveNoise",
                "version": app_version,
            },
            "instructions": _INSTRUCTIONS,
        }

    def _list_tools(self) -> List[dict]:
        if self._tools_cache is None:
            tools = self._bridge.request("list_tools") or []
            self._tools_cache = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "inputSchema": t.get(
                        "input_schema", {"type": "object",
                                         "properties": {}}),
                }
                for t in tools
            ]
        return self._tools_cache

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        if not name:
            raise BridgeError("tools/call requires a tool name.")
        args = params.get("arguments") or {}
        result = self._bridge.request(
            "call_tool", {"name": name, "input": args})
        is_error = isinstance(result, dict) and "error" in result
        return {"content": tool_content(result), "isError": bool(is_error)}


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": code, "message": message}}


# ── Entry point ────────────────────────────────────────────────────

def serve(endpoint_file: Optional[str] = None) -> int:
    """Run the stdio loop until stdin closes."""
    bridge = BridgeClient(endpoint_file)
    server = McpServer(bridge)
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    _log(f"listening on stdio; endpoint="
         f"{endpoint_file or endpoint_path()}")
    while True:
        line = stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception as exc:
            _log(f"bad JSON on stdin: {exc}")
            continue
        # A host may batch messages into a JSON array.
        batch = msg if isinstance(msg, list) else [msg]
        replies = [r for r in (server.handle(m) for m in batch)
                   if r is not None]
        for reply in replies:
            stdout.write((json.dumps(reply) + "\n").encode("utf-8"))
        if replies:
            stdout.flush()
    bridge.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    endpoint_file = None
    if "--endpoint" in args:
        i = args.index("--endpoint")
        if i + 1 < len(args):
            endpoint_file = args[i + 1]
    return serve(endpoint_file)


if __name__ == "__main__":
    sys.exit(main())
