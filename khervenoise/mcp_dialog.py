"""Control panel for the MCP (Model Context Protocol) bridge.

Shows whether the bridge is listening and connects MCP hosts to it.

Editing ``claude_desktop_config.json`` by hand is the step that stops
people using the bridge at all, so the dialog detects the hosts on this
machine and writes the entry itself (see ``mcp_hosts``).  The snippet
and its Copy button stay, folded away, for the hosts we refuse to
rewrite and for anyone configuring a machine by hand.

Copyright (C) 2026 Gwilherm Kerherve

Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

from __future__ import annotations

import json
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QGroupBox,
                               QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QToolButton, QVBoxLayout, QWidget)

from . import APP_NAME, ORG_NAME
from .mcp_bridge import ACCESS_LEVELS
from .mcp_hosts import HOSTS, Host, cli_command, host_config
from .mcp_server import endpoint_path

#: Same organisation / application pair the rest of the app uses, so
#: the MCP preferences sit alongside the recent files and update flag.
SETTINGS = (ORG_NAME, APP_NAME)

#: Access level → (label, what it means).  Order matches ACCESS_LEVELS.
_ACCESS_LABELS = [
    ("Read only",
     "List and read the spectra, preview a denoising and look at the "
     "figure; no changes."),
    ("Edit (recommended)",
     "Select spectra, set parameters, create, rename and delete "
     "denoised spectra — and save over the open project file."),
    ("Full",
     "Everything, including importing, opening, saving and exporting "
     "files of its own choosing."),
]


class McpServerDialog(QDialog):
    """Enable/disable the bridge and copy the host configuration."""

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self._bridge = bridge
                self.setWindowTitle("Connect to Claude (MCP)")
        self.setMinimumWidth(620)
        self._build_ui()
        self._refresh()
        # Bound methods, not lambdas: the binding drops the connection when
        # this dialog is destroyed (it is WA_DeleteOnClose), whereas a
        # lambda would outlive it and fire on a deleted widget.
        bridge.started.connect(self._on_bridge_started)
        bridge.stopped.connect(self._refresh)
        bridge.tool_invoked.connect(self._on_tool_invoked)

    # ── UI ───────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)

        blurb = QLabel(
            "Let Claude Desktop, Claude Code, Cursor or Zed work with the "
            "spectra open here, with the login you already have — no API "
            "key. Every change it makes is undoable with Ctrl+Z.")
        blurb.setWordWrap(True)
        lay.addWidget(blurb)

        self._enable = QCheckBox("Let assistants connect to KherveNoise")
        self._enable.toggled.connect(self._on_toggled)
        lay.addWidget(self._enable)

        self._status = QLabel()
        self._status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self._status)

        acc_row = QHBoxLayout()
        acc_row.addWidget(QLabel("The assistant may:"))
        self._access = QComboBox()
        for label, tip in _ACCESS_LABELS:
            self._access.addItem(label)
            self._access.setItemData(self._access.count() - 1, tip,
                                     Qt.ToolTipRole)
        self._access.currentIndexChanged.connect(self._on_access_changed)
        acc_row.addWidget(self._access, 1)
        lay.addLayout(acc_row)

        self._access_hint = QLabel()
        self._access_hint.setWordWrap(True)
        lay.addWidget(self._access_hint)

        host_box = QGroupBox("Connect an application")
        host_lay = QVBoxLayout(host_box)
        host_lay.addWidget(QLabel(
            "KherveNoise can write its entry into these "
            "applications' own settings — no config file to edit by "
            "hand."))
        self._hosts = QListWidget()
        self._hosts.setMaximumHeight(120)
        self._hosts.currentRowChanged.connect(self._refresh_host_buttons)
        host_lay.addWidget(self._hosts)
        hrow = QHBoxLayout()
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._on_connect)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        hrow.addWidget(self._connect_btn)
        hrow.addWidget(self._disconnect_btn)
        other = QPushButton("Other application…")
        other.setToolTip(
            "Pick any MCP client's JSON config file and add "
            "KherveNoise to it.")
        other.clicked.connect(self._on_other_host)
        hrow.addWidget(other)
        hrow.addStretch(1)
        host_lay.addLayout(hrow)
        self._host_hint = QLabel()
        self._host_hint.setWordWrap(True)
        self._host_hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        host_lay.addWidget(self._host_hint)
        lay.addWidget(host_box)

        hint = QLabel(
            "Restart the application after connecting, then name "
            "KherveNoise in the chat — \"denoise C1s with VMD in "
            "KherveNoise\".")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # The by-hand configuration is for the few who need it; folded
        # away it no longer pushes the rest of the dialog off screen.
        self._manual_toggle = QToolButton()
        self._manual_toggle.setText("Configure by hand")
        self._manual_toggle.setCheckable(True)
        self._manual_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._manual_toggle.setArrowType(Qt.RightArrow)
        self._manual_toggle.setAutoRaise(True)
        self._manual_toggle.toggled.connect(self._on_manual_toggled)
        lay.addWidget(self._manual_toggle)

        self._manual = QWidget()
        man_lay = QVBoxLayout(self._manual)
        man_lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self._flavour = QComboBox()
        self._flavour.addItems([
            "Claude Desktop / Cursor / Zed (JSON)",
            "Claude Code (command line)",
        ])
        self._flavour.currentIndexChanged.connect(self._refresh_snippet)
        row.addWidget(self._flavour, 1)
        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy)
        row.addWidget(copy)
        man_lay.addLayout(row)

        self._snippet = QPlainTextEdit()
        self._snippet.setReadOnly(True)
        mono = QFont("Consolas" if sys.platform.startswith("win")
                     else "Monospace")
        mono.setStyleHint(QFont.TypeWriter)
        mono.setPointSize(9)
        self._snippet.setFont(mono)
        self._snippet.setMinimumHeight(150)
        man_lay.addWidget(self._snippet)
        self._manual.setVisible(False)
        lay.addWidget(self._manual)

        act_box = QGroupBox("Recent activity")
        act_lay = QVBoxLayout(act_box)
        self._activity = QListWidget()
        self._activity.setMaximumHeight(72)
        act_lay.addWidget(self._activity)
        lay.addWidget(act_box)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    # ── Behaviour ────────────────────────────────────────────────────

    def _on_bridge_started(self, _port: int):
        self._refresh()

    def _on_tool_invoked(self, name: str, outcome: str):
        self._activity.insertItem(0, f"{name} — {outcome}")
        while self._activity.count() > 50:
            self._activity.takeItem(self._activity.count() - 1)

    def _on_manual_toggled(self, on: bool):
        self._manual_toggle.setArrowType(Qt.DownArrow if on
                                         else Qt.RightArrow)
        self._manual.setVisible(on)
        self.adjustSize()

    def _on_access_changed(self, index: int):
        level = ACCESS_LEVELS[index]
        self._bridge.set_access(level)
        QSettings(*SETTINGS).setValue("mcp/access", level)
        self._refresh_access_hint()

    def _on_toggled(self, on: bool):
        if on:
            if not self._bridge.start():
                self._enable.setChecked(False)
                self._status.setText(
                    "<b>Could not open a local port.</b> Another "
                    "process may be holding it.")
                return
        else:
            self._bridge.stop()
        QSettings(*SETTINGS).setValue("mcp/enabled", bool(on))
        self._refresh()

    def _refresh_access_hint(self):
        idx = self._access.currentIndex()
        text = _ACCESS_LABELS[idx][1]
        if ACCESS_LEVELS[idx] == "full":
            text += (" A connected assistant can then read and overwrite "
                     "files anywhere you can — grant it only to hosts "
                     "you trust.")
        self._access_hint.setText(text)

    def _refresh(self):
        running = self._bridge.is_running()
        self._enable.blockSignals(True)
        self._enable.setChecked(running)
        self._enable.blockSignals(False)
        self._access.blockSignals(True)
        self._access.setCurrentIndex(
            ACCESS_LEVELS.index(self._bridge.access()))
        self._access.blockSignals(False)
        self._refresh_access_hint()
        self._activity.clear()
        for entry in reversed(self._bridge.log):
            self._activity.addItem(
                f"{entry['time']}  {entry['tool']} — {entry['outcome']}")
        if running:
            self._status.setText(
                f"<b style='color:#2e7d32'>Listening</b> on "
                f"127.0.0.1:{self._bridge.port()}<br>"
                f"endpoint file: {endpoint_path()}")
        else:
            self._status.setText(
                "<b style='color:#b71c1c'>Stopped</b> — assistants "
                "cannot reach KherveNoise.")
        self._refresh_snippet()
        self._refresh_hosts()

    # ── Host wiring ──────────────────────────────────────────────────

    def _selected_host(self):
        row = self._hosts.currentRow()
        return HOSTS[row] if 0 <= row < len(HOSTS) else None

    def _refresh_hosts(self):
        """Rebuild the host list, keeping the current selection."""
        row = max(self._hosts.currentRow(), 0)
        self._hosts.blockSignals(True)
        self._hosts.clear()
        for host in HOSTS:
            status = host.status()
            item = QListWidgetItem(f"{host.label} — {status}")
            if status.startswith("connected"):
                item.setForeground(Qt.darkGreen)
            elif status == "not installed":
                item.setForeground(Qt.gray)
            self._hosts.addItem(item)
        self._hosts.setCurrentRow(min(row, len(HOSTS) - 1))
        self._hosts.blockSignals(False)
        self._refresh_host_buttons()

    def _refresh_host_buttons(self):
        host = self._selected_host()
        if host is None:
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(False)
            self._host_hint.clear()
            return
        connected = host.connected()
        self._connect_btn.setEnabled(not host.manual)
        self._connect_btn.setText(
            "Update entry" if connected and not host.up_to_date()
            else "Connect")
        self._disconnect_btn.setEnabled(connected and not host.manual)
        bits = []
        if host.manual:
            bits.append("Cannot be edited automatically.")
        bits.append(host.note)
        path = host.path()
        if path:
            bits.append(f"<i>{path}</i>")
        self._host_hint.setText("  ".join(b for b in bits if b))

    def _report(self, result: dict):
        """Show what a connect/disconnect actually did."""
        host = result.get("host", "host")
        if not result.get("ok"):
            QMessageBox.warning(self, "MCP host", result.get(
                "error", f"Could not configure {host}."))
            self._refresh_hosts()
            return
        lines = [f"{host}: KherveNoise "
                 f"{result.get('action', 'updated')}.",
                 f"File: {result.get('path', '')}"]
        if result.get("backup"):
            lines.append(f"Previous version saved as {result['backup']}")
        if result.get("restart"):
            lines.append(f"\nRestart {host} for it to take effect.")
        lines.append("\nThen mention KherveNoise in the chat — e.g. "
                     "\"denoise every core level in KherveNoise\" — so "
                     "the assistant knows to use these tools.")
        QMessageBox.information(self, "MCP host", "\n".join(lines))
        self._refresh_hosts()

    def _require_running(self) -> bool:
        if self._bridge.is_running():
            return True
        QMessageBox.information(
            self, "MCP host",
            "Tick 'Let assistants connect to KherveNoise' first — the "
            "entry is only useful while KherveNoise is serving.")
        return False

    def _on_connect(self):
        host = self._selected_host()
        if host is None or not self._require_running():
            return
        self._report(host.connect())

    def _on_other_host(self):
        """Add KherveNoise to a config file the user points us at.

        The named entries cannot cover every MCP client, and guessing a
        path wrongly is worse than asking.
        """
        if not self._require_running():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose the client's MCP config file", "",
            "JSON config (*.json);;All files (*)")
        if not path:
            return
        # Match the file's own convention rather than imposing ours:
        # most clients copied Claude Desktop's "mcpServers", VS Code
        # and its relatives use "servers".
        shape = "mcpServers"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            if isinstance(doc, dict) and "servers" in doc \
                    and "mcpServers" not in doc:
                shape = "servers"
        except Exception:  # noqa: BLE001
            pass          # empty or unreadable: connect() reports it
        host = Host.for_file(path, shape=shape)
        if shape == "servers":
            host.entry_extra = {"type": "stdio"}
        self._report(host.connect())

    def _on_disconnect(self):
        host = self._selected_host()
        if host is None:
            return
        if QMessageBox.question(
                self, "MCP host",
                f"Remove KherveNoise from {host.label}'s "
                f"configuration?\nOther servers are left untouched.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._report(host.disconnect())

    def _refresh_snippet(self):
        idx = self._flavour.currentIndex()
        if idx == 0:
            self._snippet.setPlainText(host_config())
        else:
            self._snippet.setPlainText(cli_command())

    def _copy(self):
        QApplication.clipboard().setText(self._snippet.toPlainText())
