"""Offscreen Qt, a throw-away QSettings / MCP state dir, no update checks."""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["KHERVENOISE_NO_UPDATE"] = "1"
os.environ["KHERVENOISE_STATE_DIR"] = tempfile.mkdtemp(prefix="knoise_state_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402

QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                  tempfile.mkdtemp(prefix="knoise_settings_"))

DATA = os.path.join(os.path.dirname(__file__), "data")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    # Never block on a message box in a test.
    for name in ("information", "warning", "critical"):
        setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    return app


@pytest.fixture
def window(qapp):
    from khervenoise.mainwindow import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w.document.dirty = False
    if w.bridge is not None:
        w.bridge.stop()
    w.close()
    w.deleteLater()


@pytest.fixture
def vamas_path():
    return os.path.join(DATA, "Pt4f.vms")
