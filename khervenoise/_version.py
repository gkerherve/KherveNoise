"""Runtime-derived version string.

The version is `0.1.{commit_count}+{short_sha}`, where commit_count comes
from `git rev-list --count HEAD`, so it bumps on every commit without
anyone editing a constant. Outside a git checkout it falls back to
``_FALLBACK`` — bump that by hand for tagged releases.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import subprocess
from functools import lru_cache
from pathlib import Path

_FALLBACK = "0.1.0"


@lru_cache(maxsize=1)
def get_version() -> str:
    root = Path(__file__).resolve().parent.parent
    if not (root / ".git").exists():
        return _FALLBACK
    try:
        count = subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=root, stderr=subprocess.DEVNULL,
        ).strip().decode()
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, stderr=subprocess.DEVNULL,
        ).strip().decode()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return _FALLBACK
    return f"0.1.{count}+{sha}" if count and sha else _FALLBACK
