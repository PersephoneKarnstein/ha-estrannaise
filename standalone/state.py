"""Compute the same state dict the Home Assistant coordinator produces.

This is the one piece that genuinely has to be reimplemented, because the
original is a ``DataUpdateCoordinator`` method. The arithmetic it performs is
delegated to the shared modules wherever possible: scaling factors come from
``database.compute_scaling_factor``, curves from ``const.compute_e2_at_time``,
and schedules from ``schedule``. Only the assembly is local.
"""

from __future__ import annotations

import math
from datetime import tzinfo
from typing import Any

from .core import const, schedule

# Matches the coordinator's baseline decay: measured pre-HRT levels are assumed
# to fade rather than persist indefinitely.
BASELINE_DECAY_PER_DAY = 0.02


async def persist_pending_doses(
    db: Any, regimens: list[dict[str, Any]], now: float, local_tz: tzinfo
) -> int:
    """Write any past scheduled doses that are missing. Returns how many."""
    written = 0
    for regimen in regimens:
        entry_id = regimen["entry_id"]
        existing = await db.get_auto_dose_timestamps(entry_id)
        for dose in schedule.pending_auto_doses(
            regimen,
            now,
            local_tz,
            existing_timestamps=existing,
            update_interval=const.DEFAULT_UPDATE_INTERVAL,
        ):
            await db.add_dose(
                config_entry_id=entry_id,
                model=dose["model"],
                dose_mg=dose["dose_mg"],
                timestamp=dose["timestamp"],
                source="automatic",
            )
            written += 1
    return written


def _enrich(regimen: dict[str, Any]) -> dict[str, Any]:
    """Attach the suggested/cycle-fit regimen when auto_regimen is on."""
    enriched = dict(regimen)
    if not regimen.get("auto_regimen", False):
        return enriched

    suggested = const.compute_suggested_regimen(
        regimen["ester"], regimen["method"], regimen.get("target_type", "target_range")
    )
    enriched["suggested_regimen"] = suggested
    enriched["cycle_fit_regimen"] = (
        suggested if suggested and "schedules" in suggested else None
    )
    return enriched


async def build_state(
    db: Any, config: dict[str, Any], now: float, local_tz: tzinfo
) -> dict[str, Any]:
    """Assemble the full state, grouped per user, mirroring the HA coordinator."""
    regimens = config["regimens"]
    units = config["units"]
    conversion = const.AVAILABLE_UNITS.get(units, {}).get("conversion_factor", 1.0)

    await persist_pending_doses(db, regimens, now, local_tz)

    # Deliberately NOT calling db.prune_stale_doses here, unlike the Home
    # Assistant coordinator.
    #
    # That function issues DELETE FROM doses for anything older than the PK
    # model's terminal elimination window, and it does not distinguish manual
    # doses from generated ones. In Home Assistant that is housekeeping: a dose
    # from a year ago contributes ~0 to the current level, so dropping it costs
    # nothing the coordinator cares about.
    #
    # Here it is destructive. This app is a personal record, and importing
    # years of history from Home Assistant is an explicitly supported workflow,
    # so silently deleting anything past the elimination window defeats the
    # purpose. build_state runs on every request, including dashboard polls, so
    # the deletion happened within seconds of startup and looked like the
    # import having failed.
    #
    # The cost of keeping everything is a few rows per week in SQLite.
    all_doses = await db.get_all_doses()
    all_blood_tests = await db.get_all_blood_tests()

    # Latest recorded automatic dose per config, so the projection continues
    # the cadence the history established instead of re-anchoring to today.
    # Manual doses are excluded deliberately: under mode "both" they are extra
    # injections layered on top of the schedule, not the schedule itself.
    latest_auto: dict[str, float] = {}
    for dose in all_doses:
        if dose.get("source") != "automatic":
            continue
        entry_id = dose["config_entry_id"]
        if dose["timestamp"] > latest_auto.get(entry_id, 0.0):
            latest_auto[entry_id] = dose["timestamp"]

    groups: dict[str, list[dict[str, Any]]] = {}
    for regimen in regimens:
        groups.setdefault(regimen.get("user_id", const.DEFAULT_USER_ID), []).append(
            regimen
        )

    users: dict[str, dict[str, Any]] = {}
    for user_id, user_regimens in groups.items():
        entry_ids = {r["entry_id"] for r in user_regimens}

        manual = [d for d in all_doses if d["config_entry_id"] in entry_ids]
        projected: list[dict[str, Any]] = []
        for regimen in user_regimens:
            projected.extend(
                schedule.generate_auto_doses(
                    regimen,
                    now,
                    local_tz,
                    last_dose_ts=latest_auto.get(regimen["entry_id"]),
                )
            )
        combined = manual + projected

        blood_tests = [
            bt for bt in all_blood_tests if bt["config_entry_id"] in entry_ids
        ]

        scaling_factor, scaling_variance = await db.compute_scaling_factor(
            next(iter(entry_ids)),
            combined,
            all_configs=user_regimens,
            blood_tests=blood_tests,
        )

        current_e2 = const.compute_e2_at_time(now, combined, scaling_factor) * conversion

        # Zero-state handling: if every off-schedule test was taken while the
        # model predicts effectively nothing, treat the most recent as a
        # measured baseline rather than evidence the model is mis-scaled.
        baseline_e2 = 0.0
        baseline_test_ts = 0.0
        candidates = [bt for bt in blood_tests if not bt.get("on_schedule")]
        if candidates and all(
            const.compute_e2_at_time(bt["timestamp"], combined) < 1.0
            for bt in candidates
        ):
            latest = max(candidates, key=lambda bt: bt["timestamp"])
            baseline_e2 = latest["level_pg_ml"]
            baseline_test_ts = latest["timestamp"]

        if baseline_e2 > 0:
            age_days = max(0.0, (now - baseline_test_ts) / 86400.0)
            scaling_factor = 1.0
            scaling_variance = 0.0
            current_e2 += (
                baseline_e2 * math.exp(-BASELINE_DECAY_PER_DAY * age_days) * conversion
            )

        users[user_id] = {
            "user_id": user_id,
            "doses": manual,
            "auto_doses": projected,
            "blood_tests": blood_tests,
            "scaling_factor": scaling_factor,
            "scaling_variance": scaling_variance,
            "current_e2": round(current_e2, 1),
            "configs": [_enrich(r) for r in user_regimens],
            "baseline_e2": round(baseline_e2, 2),
            "baseline_test_ts": baseline_test_ts,
        }

    primary_id = (
        regimens[0].get("user_id", const.DEFAULT_USER_ID)
        if regimens
        else const.DEFAULT_USER_ID
    )
    primary = users.get(primary_id, {})

    return {
        "users": users,
        "units": units,
        "doses": primary.get("doses", []),
        "auto_doses": primary.get("auto_doses", []),
        "blood_tests": primary.get("blood_tests", []),
        "scaling_factor": primary.get("scaling_factor", 1.0),
        "scaling_variance": primary.get("scaling_variance", 0.0),
        "current_e2": primary.get("current_e2", 0.0),
        "baseline_e2": primary.get("baseline_e2", 0.0),
        "baseline_test_ts": primary.get("baseline_test_ts", 0.0),
        "all_configs": [_enrich(r) for r in regimens],
        # Reference values, in pg/mL regardless of display units. Callers that
        # plot alongside converted levels must convert these too.
        "target_range": {
            "lower": const.TARGET_RANGE_LOWER,
            "upper": const.TARGET_RANGE_UPPER,
        },
        "danger_threshold": config.get("danger_threshold", const.DANGER_THRESHOLD),
        "pk_parameters": const.PK_PARAMETERS,
        "esters": const.ESTERS,
        "methods": const.METHODS,
        # Only 12 of the 24 ester/method pairs have PK parameters. The UI uses
        # this to offer just the valid ones rather than letting you build a
        # regimen that cannot resolve to a model.
        "supported_methods": {
            ester: [
                method
                for method in const.METHODS
                if const.is_combination_supported(ester, method)
            ]
            for ester in const.ESTERS
        },
        "available_units": const.AVAILABLE_UNITS,
    }
