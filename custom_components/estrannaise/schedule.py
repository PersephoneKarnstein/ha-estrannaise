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

from datetime import datetime, timedelta, tzinfo
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


def _make_stepper(
    interval_days: float, hour: int, minute: int, local_tz: tzinfo
):
    """Return ``step(ts, n=1)``, advancing *n* intervals from *ts*.

    Whole-day intervals step by local calendar days and are re-pinned to the
    dose time, so a schedule stays at 22:00 local across a DST transition
    rather than sliding to 21:00 and desynchronising from the stored history.
    Fractional intervals fall back to fixed seconds, where a wall-clock time of
    day is not meaningful anyway.
    """
    if float(interval_days).is_integer():
        whole = int(interval_days)

        def step(ts: float, n: int = 1) -> float:
            local = datetime.fromtimestamp(ts, tz=local_tz) + timedelta(days=whole * n)
            return local.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            ).timestamp()

    else:
        seconds = float(interval_days) * 86400.0

        def step(ts: float, n: int = 1) -> float:
            return ts + seconds * n

    return step


def _resolve_anchor(
    sch: dict[str, Any],
    now: float,
    hour: int,
    minute: int,
    local_tz: tzinfo,
    last_dose_ts: float | None,
) -> float:
    """The reference point a schedule's dose lattice is built from.

    Precedence matters, and this is the fix for a real defect. Anchoring to
    "today" means the cadence is re-derived from the current date on every
    run, so a config whose phase is unset silently migrates onto whatever
    weekday the app happened to be restarted on -- and, because the lattice
    then lands one day off the stored history, backfills a fresh dose every
    single day. Anchoring to the last recorded dose makes the schedule follow
    the history instead of the calendar.
    """
    phase = float(sch.get("phase_days", 0.0) or 0.0)
    if phase > 0:
        # Cycle fits pin themselves to a day within the 28-day cycle. That is
        # already history-independent and stable, so leave it alone.
        return _phase_anchor(now, phase, hour, minute, local_tz)
    if last_dose_ts is not None:
        return local_dose_anchor(last_dose_ts, hour, minute, local_tz)
    # No history yet: a brand-new config starts from today.
    return local_dose_anchor(now, hour, minute, local_tz)


def _first_after(
    anchor: float, bound: float, step, interval_days: float
) -> float:
    """Smallest point on the schedule lattice strictly after *bound*.

    Works whether the anchor sits before or after the bound, so one helper
    serves both the future projection (bound = now) and the backfill window
    (bound = the start of the lookback).
    """
    interval_sec = float(interval_days) * 86400.0
    t = anchor

    # Coarse jump first, so an anchor years in the past does not cost one
    # iteration per interval.
    if t <= bound and interval_sec > 0:
        jumps = int((bound - t) // interval_sec)
        if jumps:
            t = step(t, jumps)

    guard = 0
    while t <= bound and guard < MAX_GENERATED_DOSES:
        t = step(t)
        guard += 1

    # Anchor may have started past the bound; walk back to the first one that
    # still clears it.
    guard = 0
    while guard < MAX_GENERATED_DOSES:
        previous = step(t, -1)
        if previous <= bound:
            break
        t = previous
        guard += 1

    return t


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
    last_dose_ts: float | None = None,
) -> list[dict[str, Any]]:
    """Project *future* synthetic doses for a config's recurring schedule.

    These are never persisted -- they exist so the chart can draw the projected
    curve ahead of now. Past doses are handled by :func:`pending_auto_doses`.

    *last_dose_ts* is the timestamp of the most recent automatic dose already
    recorded for this config. Supplying it continues the cadence the history
    actually established; omitting it starts the cadence from today, which is
    only correct for a config with no history at all.
    """
    if not is_scheduled(config):
        return []

    hour, minute = parse_dose_time(config.get("dose_time"))
    future_limit = now + lookback_days * 86400.0
    schedules = resolve_schedules(config)
    # One recorded dose cannot be attributed to a particular schedule of a
    # multi-schedule cycle fit. Those set phase_days, so they anchor on phase.
    history = last_dose_ts if len(schedules) == 1 else None
    doses: list[dict[str, Any]] = []

    for sch in schedules:
        interval_days = sch["interval_days"]
        if interval_days <= 0:
            continue

        model_key = sch.get("model_key") or resolve_model_key(
            config["ester"], config["method"], interval_days
        )
        if not model_key:
            continue

        step = _make_stepper(interval_days, hour, minute, local_tz)
        anchor = _resolve_anchor(sch, now, hour, minute, local_tz, history)
        t = _first_after(anchor, now, step, interval_days)

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
            t = step(t)

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

    The cadence continues from the most recent timestamp in
    *existing_timestamps* rather than from today. Without that, a config with
    no ``phase_days`` re-anchors to the current date on every call and writes a
    fresh dose every day, one day off the history it already has.
    """
    if not is_scheduled(config):
        return []

    existing = set(existing_timestamps or ())
    hour, minute = parse_dose_time(config.get("dose_time"))

    if config.get("backfill_doses", False):
        lookback_ts = now - PROJECTION_DAYS * 86400.0
    else:
        lookback_ts = now - update_interval - 60

    schedules = resolve_schedules(config)
    history = max(existing) if existing and len(schedules) == 1 else None
    pending: list[dict[str, Any]] = []

    for sch in schedules:
        interval_days = sch["interval_days"]
        if interval_days <= 0:
            continue

        model_key = sch.get("model_key") or resolve_model_key(
            config["ester"], config["method"], interval_days
        )
        if not model_key:
            continue

        step = _make_stepper(interval_days, hour, minute, local_tz)
        anchor = _resolve_anchor(sch, now, hour, minute, local_tz, history)
        t = _first_after(anchor, lookback_ts, step, interval_days)

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
            t = step(t)

    return pending
