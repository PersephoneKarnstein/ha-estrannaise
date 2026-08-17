"""JSON-file configuration, standing in for Home Assistant config entries.

Each regimen mirrors one HA config entry, including its ``entry_id`` (which the
database uses as a foreign key) and ``user_id`` (which drives per-user grouping).
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .core import const

_DEFAULTS: dict[str, Any] = {
    "ester": const.DEFAULT_ESTER,
    "method": const.DEFAULT_METHOD,
    "dose_mg": const.DEFAULT_DOSE_MG,
    "interval_days": const.DEFAULT_INTERVAL_DAYS,
    "mode": const.DEFAULT_MODE,
    "enable_calendar": const.DEFAULT_ENABLE_CALENDAR,
    "dose_time": const.DEFAULT_DOSE_TIME,
    "auto_regimen": const.DEFAULT_AUTO_REGIMEN,
    "target_type": const.DEFAULT_TARGET_TYPE,
    "phase_days": const.DEFAULT_PHASE_DAYS,
    "backfill_doses": const.DEFAULT_BACKFILL_DOSES,
    "user_id": const.DEFAULT_USER_ID,
}


class ConfigError(RuntimeError):
    """Raised when the config file exists but cannot be read.

    Deliberately fatal rather than silently falling back to defaults: quietly
    discarding a regimen would silently change computed levels.
    """


def normalise_regimen(raw: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and guarantee an entry_id."""
    regimen = {**_DEFAULTS, **(raw or {})}
    if not regimen.get("entry_id"):
        regimen["entry_id"] = uuid.uuid4().hex
    if not regimen.get("user_id"):
        regimen["user_id"] = const.DEFAULT_USER_ID
    return regimen


def default_config() -> dict[str, Any]:
    return {"units": const.DEFAULT_UNITS, "regimens": []}


def load_config(path: Path) -> dict[str, Any]:
    """Read the config file, or return defaults if it does not exist yet.

    A corrupt or unreadable file raises rather than resetting your regimens.
    """
    if not path.exists():
        return default_config()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise ConfigError(
            f"Could not read config at {path}: {err}. Refusing to start with "
            "default settings, which would change your computed levels. Fix or "
            "remove the file."
        ) from err

    if not isinstance(raw, dict):
        raise ConfigError(f"Config at {path} is not a JSON object.")

    units = raw.get("units", const.DEFAULT_UNITS)
    if units not in const.AVAILABLE_UNITS:
        units = const.DEFAULT_UNITS

    return {
        "units": units,
        "regimens": [normalise_regimen(r) for r in raw.get("regimens", [])],
    }


def save_config(path: Path, config: dict[str, Any]) -> None:
    """Write the config atomically.

    Write to a temp file in the same directory, fsync, then rename. A crash
    mid-write leaves the previous config intact instead of a truncated file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "units": config.get("units", const.DEFAULT_UNITS),
        "regimens": [normalise_regimen(r) for r in config.get("regimens", [])],
    }

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
