"""Hover help for every toolbar icon.

`apply_to_toolbars()` gives each toolbar action a wide HTML tooltip —
what the tool does, numbered how-to steps, a tip and its shortcut — and a
one-line status-bar text. The words live in tooltip_texts.py.
`guide_markdown()` builds the Toolbar reference chapter of the User Guide
from the very same entries, so the two can never disagree.

Copyright (C) 2026 Gwilherm Kerherve

Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtWidgets import QToolBar, QWidgetAction

from .tooltip_texts import TIPS

#: tooltip width in pixels — QToolTip otherwise lays a long paragraph
#: out on a single line as wide as the screen
WIDTH = 380

#: toolbar window title -> (guide heading, where it sits, one-line blurb)
BARS: List[Tuple[str, str, str, str]] = [
    ("File", "File", "top",
     "new instance, open, import Excel / data / VAMAS files, save and export"),
    ("Denoise", "Denoise", "top",
     "apply, auto-tune and create denoised spectra"),
    ("View", "View", "top", "zoom the Raw vs Denoised panel"),
    ("Help", "Help", "top",
     "the Claude connection, the guide, the references and About"),
]

#: shortcuts of the matching menu entries, for icons whose action carries
#: none itself
SHORTCUTS = {
    "File|Open": "Ctrl+O", "File|Save": "Ctrl+S",
    "File|New Instance": "Ctrl+Shift+N", "Denoise|Apply": "F5",
    "Denoise|Auto": "Ctrl+Shift+A", "Denoise|Create": "Ctrl+Enter",
    "Help|User Guide": "F1",
}

_KEY_PROP = "tipKey"


def _label(act) -> str:
    """The name a toolbar action is filed under: its text, or its short
    tooltip when it is an icon-only button."""
    return (act.text().replace("&", "") or act.toolTip()).strip()


def entry(key: str):
    """(title, what, steps, tip) for *key*; an icon nobody wrote up still
    gets a line, so a new button is never silent."""
    if key in TIPS:
        return TIPS[key]
    label = key.split("|", 1)[-1]
    return (label, f"{label}.", [], None)


def summary(key: str) -> str:
    """One line for the status bar."""
    title, what, _steps, _tip = entry(key)
    return f"{title} — {what}"


def rich(key: str, shortcut: str = "", footer: str = "") -> str:
    """The HTML tooltip for *key*: title (+ shortcut), what it does,
    numbered how-to steps, a tip and an optional footer line."""
    title, what, steps, tip = entry(key)
    keys = (f" &nbsp;<span style='color:#8a8a8a'>{shortcut}</span>"
            if shortcut else "")
    parts = [f"<b>{title}</b>{keys}",
             f"<p style='margin:4px 0 0 0'>{what}</p>"]
    if steps:
        items = "".join(f"<li>{s}</li>" for s in steps)
        parts.append("<p style='margin:6px 0 0 0'><b>How to use</b></p>"
                     f"<ol style='margin:2px 0 0 0'>{items}</ol>")
    if tip:
        parts.append("<p style='margin:4px 0 0 0; color:#8a8a8a'>"
                     f"<i>Tip:</i> {tip}</p>")
    if footer:
        parts.append("<p style='margin:6px 0 0 0; color:#8a8a8a'>"
                     f"{footer}</p>")
    return (f"<table width='{WIDTH}' cellspacing='0' cellpadding='0'>"
            f"<tr><td>{''.join(parts)}</td></tr></table>")


def _bars(window) -> List[QToolBar]:
    return window.findChildren(QToolBar)


def _members(bar):
    """(action, family button or None) for every tool of *bar*; a grouped
    button contributes each of its members."""
    for act in bar.actions():
        if act.isSeparator():
            continue
        w = act.defaultWidget() if isinstance(act, QWidgetAction) else None
        family = getattr(w, "family", None)
        if isinstance(act, QWidgetAction) and not family:
            continue                    # a spin box or label, not a tool
        if family:
            for member in family:
                yield member, w
        else:
            yield act, None


def group_footer(button) -> str:
    """The line a grouped tool adds under its tip."""
    names = ", ".join(a.text().replace("&", "") for a in button.family)
    return (f"<b>{button.title}</b> group — the ▾ arrow lists: {names}.")


def _shortcut(key: str, act) -> str:
    return act.shortcut().toString() or SHORTCUTS.get(key, "")


def apply_to_toolbars(window) -> int:
    """Tooltip + status tip on every action of every toolbar of
    *window*. Returns how many icons were described."""
    n = 0
    for bar in _bars(window):
        for act, button in _members(bar):
            key = act.property(_KEY_PROP) or f"{bar.windowTitle()}|{_label(act)}"
            act.setProperty(_KEY_PROP, key)
            act.setToolTip(rich(key, _shortcut(key, act),
                                group_footer(button) if button else ""))
            act.setStatusTip(summary(key))
            n += 1
    return n


def described_actions(window) -> Dict[str, list]:
    """toolbar title -> [(key, action)] in toolbar order, for the guide
    and the tests."""
    out: Dict[str, list] = {}
    for bar in _bars(window):
        for act, _button in _members(bar):
            key = act.property(_KEY_PROP)
            if key:
                out.setdefault(bar.windowTitle(), []).append((key, act))
    return out


def guide_markdown(window=None,
                   icon_url: Optional[Callable[[str], str]] = None) -> str:
    """The body of the Toolbar reference chapter. With a *window* the
    icons follow the live toolbar order and each gets an image reference
    from *icon_url(key)*; without one the written entries are listed in
    file order (used by the tests and the plain-text fallback)."""
    live = described_actions(window) if window is not None else {}
    lines: List[str] = []
    for bar_title, heading, where, blurb in BARS:
        prefix = bar_title + "|"
        keys = [k for k, _a in live.get(bar_title, [])] or \
            [k for k in TIPS if k.startswith(prefix)]
        if not keys:
            continue
        lines += [f"### {heading} toolbar ({where})", "", f"{blurb.capitalize()}.", ""]
        for key in keys:
            title, what, steps, tip = entry(key)
            url = icon_url(key) if icon_url else None
            img = f"![icon]({url}) " if url else ""
            sc = ""
            act = dict(live.get(bar_title, [])).get(key)
            short = _shortcut(key, act) if act is not None else \
                SHORTCUTS.get(key, "")
            if short:
                sc = f" — `{short}`"
            lines += [f"{img}**{title}**{sc}", "", what, ""]
            lines += [f"{i}. {s}" for i, s in enumerate(steps, 1)]
            if steps:
                lines.append("")
            if tip:
                lines += [f"*Tip:* {tip}", ""]
    return "\n".join(lines)
