"""In-app help dialog — shows docs/USER_GUIDE.md.

Copyright (C) 2026 Gwilherm Kerherve

Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import re
from pathlib import Path
from typing import List, Tuple

from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QSplitter,
                               QTextBrowser, QToolButton, QVBoxLayout, QWidget)

from . import APP_NAME
from . import icons as _icons
from . import tooltips


def _app_icon():
    return _icons.app_icon()


def _user_guide_path() -> Path:
    return Path(__file__).parent.parent / "docs" / "USER_GUIDE.md"


# (level, text, char_offset) — level is 2 for "## ", 3 for "### ", …
def _parse_headings(md: str) -> List[Tuple[int, str, int]]:
    out: List[Tuple[int, str, int]] = []
    for m in re.finditer(r"(?m)^(#{2,4})\s+(.+?)\s*$", md):
        out.append((len(m.group(1)), m.group(2).strip(), m.start()))
    return out


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — User Guide")
        if _app_icon():
            self.setWindowIcon(_app_icon())
        self.setModal(False)
        self.resize(960, 680)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # --- Top toolbar: history nav + zoom + free-text search --------
        topbar = QHBoxLayout()
        topbar.setContentsMargins(0, 0, 0, 0)
        topbar.setSpacing(4)

        def _btn(text, tip, slot):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setIconSize(QSize(16, 16))
            b.clicked.connect(slot)
            return b

        self.btn_back = _btn("←", "Back (Alt+Left)", lambda: self.view.backward())
        self.btn_forward = _btn("→", "Forward (Alt+Right)", lambda: self.view.forward())
        self.btn_home = _btn("⌂", "Top of guide", self._go_home)
        self.btn_zoom_out = _btn("A−", "Zoom out (Ctrl+−)", lambda: self.view.zoomOut(1))
        self.btn_zoom_in = _btn("A+", "Zoom in (Ctrl++)", lambda: self.view.zoomIn(1))
        for b in (self.btn_back, self.btn_forward, self.btn_home,
                  self.btn_zoom_out, self.btn_zoom_in):
            topbar.addWidget(b)

        topbar.addSpacing(12)
        topbar.addWidget(QLabel("Find:"))
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find in page…  (Enter = next)")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.returnPressed.connect(self._find_next)
        topbar.addWidget(self.find_edit, stretch=1)
        outer.addLayout(topbar)

        # --- Main split: filterable TOC | rendered guide ---------------
        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter, stretch=1)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(2)
        self.toc_filter = QLineEdit()
        self.toc_filter.setPlaceholderText("Filter contents…")
        self.toc_filter.setClearButtonEnabled(True)
        self.toc_filter.textChanged.connect(self._filter_toc)
        lv.addWidget(self.toc_filter)
        self.toc = QListWidget()
        self.toc.setUniformItemSizes(True)
        lv.addWidget(self.toc, stretch=1)
        left.setMaximumWidth(280)
        splitter.addWidget(left)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        # The 'document' role gives the browser a real history we can
        # walk with backward()/forward().
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 720])

        # --- Footer hint ----------------------------------------------
        hint = QLabel(
            "F1 toggles this window · Esc closes · Ctrl+F focuses Find · "
            "Ctrl+± zooms")
        hint.setStyleSheet("color:#888; padding:2px;")
        outer.addWidget(hint)

        # (level, text, char_offset)
        self._headings: List[Tuple[int, str, int]] = []
        self._load()
        self.toc.currentRowChanged.connect(self._jump)

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+F"), self,
                  activated=lambda: (self.find_edit.setFocus(),
                                     self.find_edit.selectAll()))
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.close)
        QShortcut(QKeySequence("Alt+Left"), self,
                  activated=lambda: self.view.backward())
        QShortcut(QKeySequence("Alt+Right"), self,
                  activated=lambda: self.view.forward())

    # -- loading -------------------------------------------------------
    def _load(self):
        path = _user_guide_path()
        try:
            md = path.read_text(encoding="utf-8")
        except OSError as e:
            self.view.setPlainText(
                f"Could not load user guide:\n{path}\n\n{e}")
            return

        md, icons = self._with_toolbar_reference(md)
        try:
            self.view.setMarkdown(md)
        except Exception:  # noqa: BLE001
            self.view.setPlainText(md)
        for url, pix in icons.items():
            self.view.document().addResource(
                QTextDocument.ImageResource, QUrl(url), pix)

        self._headings = _parse_headings(md)
        self._populate_toc()

    def _with_toolbar_reference(self, md: str):
        """Fill the guide's toolbar chapter from tooltips.py, with the
        live toolbar icons when the main window is the parent."""
        marker = "<!-- toolbar-reference -->"
        if marker not in md:
            return md, {}
        win = self.parent() if hasattr(self.parent(), "findChildren") else None
        live = dict(entry for group in
                    tooltips.described_actions(win).values()
                    for entry in group) if win is not None else {}
        icons, urls = {}, {}
        for i, (key, act) in enumerate(live.items()):
            urls[key] = f"toolicon:{i}"
            icons[urls[key]] = act.icon().pixmap(28, 28)
        body = tooltips.guide_markdown(
            win, (lambda k: urls.get(k)) if urls else None)
        return md.replace(marker, body), icons

    def _populate_toc(self):
        self.toc.clear()
        for level, text, _ in self._headings:
            indent = "    " * (level - 2)
            it = QListWidgetItem(f"{indent}{text}")
            it.setData(Qt.UserRole, text)
            if level == 2:
                f = it.font(); f.setBold(True); it.setFont(f)
            self.toc.addItem(it)

    # -- navigation ----------------------------------------------------
    def _go_home(self):
        self.view.verticalScrollBar().setValue(0)

    def _jump(self, row: int):
        if row < 0 or row >= self.toc.count():
            return
        title = self.toc.item(row).data(Qt.UserRole)
        if not title:
            return
        # find() searches forward from the current cursor — start at the
        # top so jumping to any heading works even after we've scrolled.
        c = self.view.textCursor()
        c.movePosition(QTextCursor.Start)
        self.view.setTextCursor(c)
        cursor = self.view.document().find(title)
        if cursor.isNull():
            return
        cursor.movePosition(QTextCursor.StartOfBlock)
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def _filter_toc(self, text: str):
        needle = text.strip().lower()
        for i in range(self.toc.count()):
            it = self.toc.item(i)
            visible = (not needle) or (needle in it.text().lower())
            it.setHidden(not visible)

    def _find_next(self):
        needle = self.find_edit.text().strip()
        if not needle:
            return
        if not self.view.find(needle):
            # Wrap to top and try once more.
            c = self.view.textCursor()
            c.movePosition(QTextCursor.Start)
            self.view.setTextCursor(c)
            self.view.find(needle)

    # -- public --------------------------------------------------------
    def jump_to(self, title: str):
        """Show the first heading containing *title* (case-insensitive)."""
        needle = str(title or "").lower()
        for row in range(self.toc.count()):
            text = str(self.toc.item(row).data(Qt.UserRole) or "").lower()
            if needle and needle in text:
                self.toc.setCurrentRow(row)
                return True
        return False
