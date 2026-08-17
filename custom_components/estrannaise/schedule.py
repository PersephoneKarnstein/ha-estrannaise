"""Dose-schedule generation, free of any Home Assistant dependency.

This module holds the recurring-dose logic that used to live inline in
``coordinator.py``. It was extracted so the standalone web app (``standalone/``)
and the Home Assistant integration compute schedules from the *same* code
rather than from two hand-synchronised copies.

The only Home Assistant coupling in the original was
``dt_util.DEFAULT_TIME_ZONE``. That is now an explicit ``local_tz`` argument:
the integration passes Home Assistant's configured zone, the standalone app
passes the zone from ``TZ``.

Everything here is pure: no I/O, no database, no clock reads beyond the ``now``
that callers supply. That makes it directly unit-testable.
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

from .const import (
    MODE_AUTOMATIC,
    MODE_BOTH,
    compute_suggested_regimen,
    resolve_model_key,
)

# Doses are projected forward this far, and backfilled this far, so the chart
# history and the future projection cover the same window.
PROJECTION_DAYS = 90.0

# Hard ceiling on generated doses, guarding against a pathological interval.
MAX_GENERATED_DOSES = 1000

# Two automatic doses closer together than this are treated as the same dose.
DUPLICATE_TOLERANCE_SEC = 60

CYCLE_LENGTH_DAYS = 28


def parse_dose_time(dose_time: str | None) -> tuple[int, int]:
    """Parse ``"HH:MM"`` into a clamped (hour, minute).

    Falls back to 08:00 on anything unparseable, matching the original
    behaviour of silently accepting bad config rather than failing a refresh.
    """
    try:
        parts = (dose_time or "08:00").split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        hour, minute = 8, 0
    return max(0, min(23, hour)), max(0, min(59, minute))


def local_dose_anchor(ref_ts: float, hour: int, minute: int, local_tz: tzinfo) -> float:
    """UTC timestamp of the dose time-of-day on the local day containing *ref_ts*."""
    ref_dt = datetime.fromtimestamp(ref_ts, tz=local_tz)
    return ref_dt.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()


def cycle_day(now: float, local_tz: tzinfo) -> int:
    """Which day of the 28-day cycle the local day containing *now* falls on."""
    now_local = datetime.fromtimestamp(now, tz=local_tz)
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() // 86400) % CYCLE_LENGTH_DAYS


def _phase_anchor(
    now: float, phase_days: float, hour: int, minute: int, local_tz: tzinfo
) -> float:
    """Anchor timestamp for a schedule pinned to a cycle phase."""
    today_anchor = local_dose_anchor(now, hour, minute, local_tz)
    days_back = (cycle_day(now, local_tz) - int(phase_days)) % CYCLE_LENGTH_DAYS
    return today_anchor - days_back * 86400.0


def resolve_schedules(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve a config into one or more concrete dose schedules.

    An ``auto_regimen`` config may expand into several schedules (a cycle fit);
    everything else yields exactly one. Returns ``[]`` when the ester/method
    combination has no PK model.
    """
    ester = config["ester"]
    method = config["method"]

    if config.get("auto_regimen", False):
        suggested = compute_suggested_regimen(
            ester, method, config.get("target_type", "target_range")
        )
        if suggested and "schedules" in suggested:
            return list(suggested["schedules"])
        if suggested:
            return [
                {
                    "dose_mg": suggested["dose_mg"],
                    "interval_days": suggested["interval_days"],
                    "phase_days": 0.0,
                    "model_key": suggested.get("model_key", ""),
                }
            ]

    model_key = resolve_model_key(ester, method, config["interval_days"])
    if not model_key:
        return []
    return [
        {
            "dose_mg": config["dose_mg"],
            "interval_days": config["interval_days"],
            "phase_days": config.get("phase_days", 0.0),
            "model_key": model_key,
        }
    ]


def is_scheduled(config: dict[str, Any]) -> bool:
    """Whether this config generates automatic doses at all."""
    return config.get("mode", "manual") in (MODE_AUTOMATIC, MODE_BOTH)


def generate_auto_doses(
    config: dict[str, Any],
    now: float,
    local_tz: tzinfo,
    lookback_days: float = PROJECTION_DAYS,
) -> list[dict[str, Any]]:
    """Project *future* synthetic doses for a config's recurring schedule.

    These are never persisted -- they exist so the chart can draw the projected
    curve ahead of now. Past doses are handled by :func:`pending_auto_doses`.
    """
    if not is_scheduled(config):
        return []

    hour, minute = parse_dose_time(config.get("dose_time"))
    future_limit = now + lookback_days * 86400.0
    doses: list[dict[str, Any]] = []

    for sch in resolve_schedules(config):
        interval_sec = sch["interval_days"] * 86400.0
        if interval_sec <= 0:
            continue

        model_key = sch.get("model_key") or resolve_model_key(
            config["ester"], config["method"], sch["interval_days"]
        )
        if not model_key:
            continue

        phase = float(sch.get("phase_days", 0.0) or 0.0)
        if phase > 0:
            anchor = _phase_anchor(now, phase, hour, minute, local_tz)
        else:
            today = local_dose_anchor(now, hour, minute, local_tz)
            # If today's dose time has not arrived yet, step back one interval
            # so the first projected dose is today's, not next interval's.
            anchor = today - interval_sec if today > now else today

        t = anchor
        while t <= now:
            t += interval_sec

        while t <= future_limit and len(doses) < MAX_GENERATED_DOSES:
            doses.append(
                {
                    "id": None,
                    "timestamp": t,
                    "model": model_key,
                    "dose_mg": sch["dose_mg"],
                    "source": "automatic",
                }
            )
            t += interval_sec

    return doses[:MAX_GENERATED_DOSES]


def pending_auto_doses(
    config: dict[str, Any],
    now: float,
    local_tz: tzinfo,
    existing_timestamps: set[float] | None = None,
    update_interval: float = 300.0,
) -> list[dict[str, Any]]:
    """Past scheduled doses that should exist in the database but do not.

    Returns dose records for the caller to persist. Kept pure rather than
    writing directly so it can be tested without a database, and so both the
    integration and the standalone app can persist through their own layer.

    With ``backfill_doses`` the window is the full projection history; without
    it, only far enough back to catch doses missed since the last refresh.
    """
    if not is_scheduled(config):
        return []

    existing = set(existing_timestamps or ())
    hour, minute = parse_dose_time(config.get("dose_time"))

    if config.get("backfill_doses", False):
        lookback_ts = now - PROJECTION_DAYS * 86400.0
    else:
        lookback_ts = now - update_interval - 60

    pending: list[dict[str, Any]] = []

    for sch in resolve_schedules(config):
        interval_sec = sch["interval_days"] * 86400.0
        if interval_sec <= 0:
            continue

        model_key = sch.get("model_key") or resolve_model_key(
            config["ester"], config["method"], sch["interval_days"]
        )
        if not model_key:
            continue

        phase = float(sch.get("phase_days", 0.0) or 0.0)
        if phase > 0:
            anchor = _phase_anchor(now, phase, hour, minute, local_tz)
        else:
            anchor = local_dose_anchor(now, hour, minute, local_tz)

        # Walk back past the window, then step forward to the first dose inside it.
        t = anchor
        while t > lookback_ts:
            t -= interval_sec
        t += interval_sec

        while t < now and len(pending) < MAX_GENERATED_DOSES:
            if not any(abs(t - ets) < DUPLICATE_TOLERANCE_SEC for ets in existing):
                pending.append(
                    {
                        "timestamp": t,
                        "model": model_key,
                        "dose_mg": sch["dose_mg"],
                        "source": "automatic",
                    }
                )
                existing.add(t)
            t += interval_sec

    return pending
