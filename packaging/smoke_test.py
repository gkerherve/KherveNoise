"""Smoke-test a frozen KherveNoise: start it, drive it, check it works.

    python packaging/smoke_test.py dist/KherveNoise/KherveNoise.exe
    python packaging/smoke_test.py dist/KherveNoise.app/Contents/MacOS/KherveNoise

A freeze fails quietly: a module PyInstaller's analysis missed is only found
when the code that imports it runs. So this starts the real executable on
Qt's offscreen platform with the MCP bridge on (KHERVENOISE_MCP=full), then
speaks MCP to it through ``<exe> --mcp-server`` — the path Claude Desktop
takes — and makes it do the app's actual work:

* the version it reports is the one stamped from git, not the 0.1.0 fallback;
* a VAMAS file imports (the ``vamas`` reader and its data files);
* all three denoising methods run (numpy, PyWavelets, the VMD engine);
* a figure renders to PNG (matplotlib's Qt backend);
* a KherveFitting workbook exports (openpyxl).

Nothing is written to the user's preferences (``KHERVENOISE_STATE_DIR`` and
the temp folder are throw-away). Exits non-zero on the first failure.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_VMS = _ROOT / "tests" / "data" / "Pt4f.vms"
_ENDPOINT = "mcp-bridge.json"


def _fail(message: str):
    print(f"SMOKE TEST FAILED: {message}", flush=True)
    raise SystemExit(1)


class Mcp:
    """A tiny synchronous MCP client over the stdio server's pipes."""

    def __init__(self, exe: str, env: dict):
        self.proc = subprocess.Popen(
            [exe, "--mcp-server"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        self._id = 0

    def _send(self, msg: dict):
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()

    def notify(self, method: str):
        self._send({"jsonrpc": "2.0", "method": method})

    def request(self, method: str, params: dict = None) -> dict:
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method,
                    "params": params or {}})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                _fail(f"the MCP server closed while waiting for {method}")
            reply = json.loads(line)
            if reply.get("id") == self._id:
                if "error" in reply:
                    _fail(f"{method}: {reply['error']}")
                return reply["result"]

    def call(self, tool: str, /, **arguments) -> dict:
        """Call a tool; returns its JSON result and the image block, if any.
        (``tool`` is positional-only: a tool argument may itself be ``name``.)"""
        result = self.request("tools/call", {"name": tool, "arguments": arguments})
        text = next((b["text"] for b in result["content"] if b["type"] == "text"), "{}")
        data = json.loads(text)
        data["_image"] = next((b["data"] for b in result["content"]
                               if b["type"] == "image"), None)
        if result.get("isError") or "error" in data:
            _fail(f"{tool}({arguments}) -> {data.get('error', data)}")
        return data

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.proc.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("exe", help="the frozen executable")
    parser.add_argument("--version", help="the 0.1.N it must report "
                                          "(default: just not the 0.1.0 fallback)")
    parser.add_argument("--timeout", type=int, default=240,
                        help="give up after this many seconds (default 240)")
    args = parser.parse_args()

    exe = str(Path(args.exe).resolve())
    if not Path(exe).is_file():
        _fail(f"{exe} not found")
    if not _VMS.is_file():
        _fail(f"{_VMS} not found (run from a full checkout)")

    work = Path(tempfile.mkdtemp(prefix="knoise_smoke_"))
    env = dict(os.environ,
               QT_QPA_PLATFORM="offscreen",
               KHERVENOISE_MCP="full",
               KHERVENOISE_NO_UPDATE="1",
               KHERVENOISE_STATE_DIR=str(work / "state"))
    app = subprocess.Popen([exe], env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    mcp = None
    watchdog = threading.Timer(args.timeout, lambda: (app.kill(), os._exit(2)))
    watchdog.daemon = True
    watchdog.start()
    try:
        endpoint = work / "state" / _ENDPOINT
        deadline = time.time() + 120
        while not endpoint.is_file():
            if app.poll() is not None:
                _fail(f"the app exited with code {app.returncode} before its "
                      "MCP bridge came up (see the crash log in the temp folder)")
            if time.time() > deadline:
                _fail("the MCP bridge did not come up within 120 s")
            time.sleep(0.5)
        print("bridge is up", flush=True)

        mcp = Mcp(exe, env)
        info = mcp.request("initialize", {"protocolVersion": "2025-06-18"})
        mcp.notify("notifications/initialized")
        version = info["serverInfo"]["version"]
        print(f"version reported: {version}", flush=True)
        if version.startswith("0.1.0") or not version.startswith("0.1."):
            _fail(f"the frozen app reports version {version!r} — "
                  "khervenoise/VERSION was not bundled")
        if args.version and version.split("+")[0] != args.version:
            _fail(f"expected version {args.version}, the app reports {version}")

        tools = {t["name"] for t in mcp.request("tools/list")["tools"]}
        for needed in ("import_file", "denoise_preview", "create_denoised",
                       "render_figure", "export_khervefitting"):
            if needed not in tools:
                _fail(f"tool {needed} missing from tools/list")

        imported = mcp.call("import_file", path=str(_VMS))["imported"]
        if imported != ["Pt4f"]:
            _fail(f"VAMAS import gave {imported}")
        print("imported Pt4f.vms", flush=True)

        for method in ("FFT filter", "Wavelet", "VMD"):
            res = mcp.call("denoise_preview", name="Pt4f", method=method, auto=True)
            if not res["residual_rms"] > 0:
                _fail(f"{method}: residual RMS {res['residual_rms']}")
            print(f"{method:11} residual RMS {res['residual_rms']:.4g}", flush=True)

        created = mcp.call("create_denoised", method="Wavelet")["created"]
        if created != ["Pt4f_wav"]:
            _fail(f"create_denoised gave {created}")

        image = mcp.call("render_figure", dpi=50)["_image"]
        if not image or base64.b64decode(image)[:8] != b"\x89PNG\r\n\x1a\n":
            _fail("render_figure did not return a PNG")
        print("rendered the figure", flush=True)

        out = work / "out.xlsx"
        mcp.call("export_khervefitting", path=str(out))
        if not out.is_file() or out.stat().st_size < 1000:
            _fail("the KherveFitting workbook was not written")
        print("exported the workbook", flush=True)
    finally:
        watchdog.cancel()
        if mcp is not None:
            mcp.close()
        app.terminate()
        try:
            app.wait(timeout=15)
        except subprocess.TimeoutExpired:
            app.kill()
    print("SMOKE TEST PASSED", flush=True)


if __name__ == "__main__":
    main()
