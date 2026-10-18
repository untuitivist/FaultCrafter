from __future__ import annotations

import os
from pathlib import Path
import sys

from faultcrafter.services.model_defaults import EXPERIMENT32_COMPACT_PATH, EXPERIMENT32_MODEL_ID


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def checkout_root() -> Path | None:
    candidate = package_root().parent
    if (candidate / "pyproject.toml").is_file() and (candidate / ".git").exists():
        return candidate
    return None


def default_data_root() -> Path:
    checkout = checkout_root()
    if checkout is not None:
        return checkout / "user_data"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "FaultCrafter"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "faultcrafter"


def default_model_root() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled is not None:
        return Path(bundled) / "assets/compact"
    checkout = checkout_root()
    if checkout is not None:
        return checkout / EXPERIMENT32_COMPACT_PATH
    return default_data_root() / "models" / EXPERIMENT32_MODEL_ID / "compact"
