"""Application entry point.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import faulthandler
import os
import sys
import tempfile

_CRASH_LOG_FILE = None

# Light palette on top of Fusion — the family look (KhervePlot / KherveSlide).
_LIGHT_QSS = """
QMainWindow, QDialog { background: #f4f5f7; }
QMenuBar { background: #ffffff; border-bottom: 1px solid #d4d6db; padding: 2px; }
QMenuBar::item:selected { background: #d6efe7; }
QMenu::item:selected { background: #d6efe7; color: #202329; }
QToolBar { background: #ffffff; border-bottom: 1px solid #d4d6db; spacing: 2px; }
QStatusBar { background: #f0f0f0; border-top: 1px solid #d4d6db; }
QPushButton {
    background: #fafafa; border: 1px solid #aab0b8;
    padding: 3px 10px; border-radius: 3px;
}
QPushButton:hover  { background: #e8f6f1; border-color: #3a9c80; }
QPushButton:pressed { background: #d6efe7; }
QToolButton:hover { background: #e8f6f1; border-radius: 3px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: white; border: 1px solid #b8bcc3; border-radius: 2px; padding: 2px 4px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #3a9c80;
}
QGroupBox {
    border: 1px solid #c8ccd1; border-radius: 4px; margin-top: 8px; padding-top: 8px;
    font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QPushButton,
QGroupBox QComboBox, QGroupBox QListWidget { font-weight: normal; }
QListWidget, QTreeWidget { background: white; border: 1px solid #c8ccd1; }
"""


def _enable_crash_logging():
    """faulthandler to a log file, so a native crash leaves a traceback."""
    global _CRASH_LOG_FILE
    try:
        path = os.path.join(tempfile.gettempdir(), "khervenoise_crash.log")
        _CRASH_LOG_FILE = open(path, "a+", encoding="utf-8", buffering=1)
        _CRASH_LOG_FILE.write("\n=== KherveNoise start ===\n")
        faulthandler.enable(file=_CRASH_LOG_FILE, all_threads=True)
    except Exception:  # noqa: BLE001
        try:
            faulthandler.enable()
        except Exception:  # noqa: BLE001
            pass


def _apply_palette(app):
    from PySide6.QtGui import QColor, QPalette
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#f4f5f7"))
    pal.setColor(QPalette.WindowText, QColor("#202329"))
    pal.setColor(QPalette.Base, QColor("#ffffff"))
    pal.setColor(QPalette.AlternateBase, QColor("#f7f8fa"))
    pal.setColor(QPalette.ToolTipBase, QColor("#fffbe6"))
    pal.setColor(QPalette.ToolTipText, QColor("#202329"))
    pal.setColor(QPalette.Text, QColor("#202329"))
    pal.setColor(QPalette.Button, QColor("#fafafa"))
    pal.setColor(QPalette.ButtonText, QColor("#202329"))
    pal.setColor(QPalette.Highlight, QColor("#3a9c80"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.Link, QColor("#2f8a70"))
    app.setPalette(pal)


def _make_app_class():
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    class KherveNoiseApp(QApplication):
        """Receives the files Finder opens with KherveNoise (double-click,
        drag onto the Dock icon, Open With): on macOS they arrive as a
        QFileOpenEvent, not on the command line."""

        def __init__(self, argv):
            super().__init__(argv)
            self.window = None
            self.pending = []

        def event(self, ev):
            if ev.type() == QEvent.FileOpen:
                path = ev.file()
                if path:
                    if self.window is None:
                        self.pending.append(path)
                    else:
                        self.window.open_or_import(path)
                return True
            return super().event(ev)

    return KherveNoiseApp


def main():
    # An MCP host launches us as a plain stdio subprocess it owns. That
    # half must not build a QApplication, so it forks off before any Qt.
    if "--mcp-server" in sys.argv[1:]:
        from .mcp_server import main as mcp_main
        sys.exit(mcp_main([a for a in sys.argv[1:] if a != "--mcp-server"]))

    import logging
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    _enable_crash_logging()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QStyleFactory
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:  # noqa: BLE001
        pass

    from . import APP_NAME, ORG_NAME
    app = _make_app_class()(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    QApplication.setStyle(QStyleFactory.create("Fusion"))
    _apply_palette(app)
    app.setStyleSheet(_LIGHT_QSS)

    from . import icons
    from .mainwindow import MainWindow
    app.setWindowIcon(icons.app_icon())
    w = MainWindow()
    w.show()
    app.window = w
    files = [a for a in sys.argv[1:] if not a.startswith("-") and os.path.isfile(a)]
    files += app.pending
    app.pending = []
    for path in files:
        w.open_or_import(path)
    w.start_mcp_if_enabled()
    w.updater.schedule()
    sys.exit(app.exec())
