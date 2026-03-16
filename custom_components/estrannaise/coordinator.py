"""DataUpdateCoordinator for Estrannaise HRT Monitor."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    AVAILABLE_UNITS,
    CONF_AUTO_REGIMEN,
    CONF_BACKFILL_DOSES,
    CONF_DOSE_MG,
    CONF_DOSE_TIME,
    CONF_ENABLE_CALENDAR,
    CONF_ESTER,
    CONF_INTERVAL_DAYS,
    CONF_METHOD,
    CONF_MODE,
    CONF_PHASE_DAYS,
    CONF_TARGET_TYPE,
    CONF_UNITS,
    CONF_USER_ID,
    DEFAULT_AUTO_REGIMEN,
    DEFAULT_BACKFILL_DOSES,
    DEFAULT_DOSE_MG,
    DEFAULT_DOSE_TIME,
    DEFAULT_ENABLE_CALENDAR,
    DEFAULT_ESTER,
    DEFAULT_INTERVAL_DAYS,
    DEFAULT_METHOD,
    DEFAULT_MODE,
    DEFAULT_PHASE_DAYS,
    DEFAULT_TARGET_TYPE,
    DEFAULT_UNITS,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_USER_ID,
    DOMAIN,
    MODE_AUTOMATIC,
    MODE_BOTH,
    PK_PARAMETERS,
    compute_e2_at_time,
    compute_suggested_regimen,
    resolve_model_key,
    terminal_elimination_days,
)
from .database import EstrannaisDatabase

_LOGGER = logging.getLogger(__name__)


class EstrannaisCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage estrannaise data from SQLite."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        database: EstrannaisDatabase,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )
        self.config_entry = entry
        self.database = database

    def _get_config(self) -> dict[str, Any]:
        """Get merged config from entry data + options."""
        data = self.config_entry.data
        opts = self.config_entry.options
        return {
            "ester": opts.get(CONF_ESTER, data.get(CONF_ESTER, DEFAULT_ESTER)),
            "method": opts.get(CONF_METHOD, data.get(CONF_METHOD, DEFAULT_METHOD)),
            "dose_mg": opts.get(CONF_DOSE_MG, data.get(CONF_DOSE_MG, DEFAULT_DOSE_MG)),
            "interval_days": opts.get(
                CONF_INTERVAL_DAYS,
                data.get(CONF_INTERVAL_DAYS, DEFAULT_INTERVAL_DAYS),
            ),
            "mode": opts.get(CONF_MODE, data.get(CONF_MODE, DEFAULT_MODE)),
            "units": opts.get(CONF_UNITS, data.get(CONF_UNITS, DEFAULT_UNITS)),
            "enable_calendar": opts.get(
                CONF_ENABLE_CALENDAR,
                data.get(CONF_ENABLE_CALENDAR, DEFAULT_ENABLE_CALENDAR),
            ),
            "dose_time": opts.get(
                CONF_DOSE_TIME,
                data.get(CONF_DOSE_TIME, DEFAULT_DOSE_TIME),
            ),
            "auto_regimen": opts.get(
                CONF_AUTO_REGIMEN,
                data.get(CONF_AUTO_REGIMEN, DEFAULT_AUTO_REGIMEN),
            ),
            "target_type": opts.get(
                CONF_TARGET_TYPE,
                data.get(CONF_TARGET_TYPE, DEFAULT_TARGET_TYPE),
            ),
            "phase_days": opts.get(
                CONF_PHASE_DAYS,
                data.get(CONF_PHASE_DAYS, DEFAULT_PHASE_DAYS),
            ),
            "backfill_doses": opts.get(
                CONF_BACKFILL_DOSES,
                data.get(CONF_BACKFILL_DOSES, DEFAULT_BACKFILL_DOSES),
            ),
            "user_id": opts.get(
                CONF_USER_ID,
                data.get(CONF_USER_ID, DEFAULT_USER_ID),
            ),
        }

    def _get_all_entry_configs(self) -> list[dict[str, Any]]:
        """Get configs from all estrannaise entries."""
        configs = []
        domain_data = self.hass.data.get(DOMAIN, {})
        for key, val in list(domain_data.items()):
            if isinstance(val, EstrannaisCoordinator):
                cfg = val._get_config()
                cfg["entry_id"] = val.config_entry.entry_id
                configs.append(cfg)
        return configs

    @staticmethod
    def _generate_auto_doses_for_config(
        config: dict[str, Any], now: float, lookback_days: float = 90.0
    ) -> list[dict[str, Any]]:
        """Generate synthetic dose records for a config's recurring schedule."""
        from datetime import datetime, timezone
        from homeassistant.util import dt as dt_util

        mode = config["mode"]
        if mode not in (MODE_AUTOMATIC, MODE_BOTH):
            return []

        ester = config["ester"]
        method = config["method"]
        dose_mg = config["dose_mg"]
        interval_days = config["interval_days"]
        if interval_days <= 0:
            return []

        # Align to time-of-day (in HA's configured local timezone)
        dose_time = config.get("dose_time", "08:00")
        try:
            parts = dose_time.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            hour, minute = 8, 0
        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))

        local_tz = dt_util.DEFAULT_TIME_ZONE

        def _local_dose_anchor(ref_ts: float) -> float:
            """Get the UTC timestamp of today's dose time in the user's timezone."""
            ref_dt = datetime.fromtimestamp(ref_ts, tz=local_tz)
            local_dose = ref_dt.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return local_dose.timestamp()

        # If auto_regimen is enabled, use suggested regimen values
        cycle_fit = None
        if config.get("auto_regimen", False):
            target_type = config.get("target_type", "target_range")
            suggested = compute_suggested_regimen(ester, method, target_type)
            if suggested:
                if "schedules" in suggested:
                    cycle_fit = suggested
                else:
                    dose_mg = suggested["dose_mg"]
                    interval_days = suggested["interval_days"]

        doses: list[dict[str, Any]] = []
        future_limit = now + lookback_days * 86400.0

        if cycle_fit:
            # Multi-schedule cycle fit: generate future doses per schedule
            today_anchor = _local_dose_anchor(now)
            # Use local-time day for cycle phase calculation
            now_local = datetime.fromtimestamp(now, tz=local_tz)
            epoch_day_local = int(now_local.replace(
                hour=0, minute=0, second=0, microsecond=0
            ).timestamp() // 86400)
            cycle_day_now = epoch_day_local % 28

            for sch in cycle_fit["schedules"]:
                sch_dose = sch["dose_mg"]
                sch_interval = sch["interval_days"]
                if sch_interval <= 0:
                    continue
                sch_phase = int(sch["phase_days"])
                sch_model = sch["model_key"]
                sch_interval_sec = sch_interval * 86400.0

                # Anchor to most recent cycle day matching the phase
                days_back = (cycle_day_now - sch_phase) % 28
                anchor_ts = today_anchor - days_back * 86400.0

                # Step forward to next future dose
                t = anchor_ts
                while t <= now:
                    t += sch_interval_sec

                while t <= future_limit:
                    doses.append(
                        {
                            "id": None,
                            "timestamp": t,
                            "model": sch_model,
                            "dose_mg": sch_dose,
                            "source": "automatic",
                        }
                    )
                    t += sch_interval_sec
        else:
            # Single schedule
            interval_sec = interval_days * 86400.0
            model_key = resolve_model_key(ester, method, interval_days)
            if not model_key:
                return []

            phase_days = config.get("phase_days", 0.0)

            if phase_days and phase_days > 0:
                # Phase-based anchoring (from cycle fit discrete entry)
                today_anchor = _local_dose_anchor(now)
                now_local = datetime.fromtimestamp(now, tz=local_tz)
                epoch_day_local = int(now_local.replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).timestamp() // 86400)
                cycle_day_now = epoch_day_local % 28
                days_back = (cycle_day_now - int(phase_days)) % 28
                anchor_ts = today_anchor - days_back * 86400.0

                t = anchor_ts
                while t <= now:
                    t += interval_sec
                while t <= future_limit:
                    doses.append(
                        {
                            "id": None,
                            "timestamp": t,
                            "model": model_key,
                            "dose_mg": dose_mg,
                            "source": "automatic",
                        }
                    )
                    t += interval_sec
            else:
                # Standard anchoring (today's dose time)
                today_dose_ts = _local_dose_anchor(now)
                if today_dose_ts > now:
                    anchor = today_dose_ts - interval_sec
                else:
                    anchor = today_dose_ts

                t = anchor + interval_sec
                while t <= future_limit:
                    doses.append(
                        {
                            "id": None,
                            "timestamp": t,
                            "model": model_key,
                            "dose_mg": dose_mg,
                            "source": "automatic",
                        }
                    )
                    t += interval_sec

        return doses[:1000]

    async def _persist_auto_doses(
        self, config: dict[str, Any], now: float
    ) -> None:
        """Write past automatic doses to the database.

        Computes which scheduled doses should have occurred between the
        pharmacokinetic lookback window and *now*, checks which are already
        persisted, and inserts the missing ones.
        """
        from datetime import datetime
        from homeassistant.util import dt as dt_util

        mode = config.get("mode", "manual")
        if mode not in (MODE_AUTOMATIC, MODE_BOTH):
            return

        entry_id = self.config_entry.entry_id
        ester = config["ester"]
        method = config["method"]

        # Parse dose time-of-day (in HA's configured local timezone)
        dose_time_str = config.get("dose_time", "08:00")
        try:
            parts = dose_time_str.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            hour, minute = 8, 0
        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))

        local_tz = dt_util.DEFAULT_TIME_ZONE

        # Resolve schedule(s)
        schedules: list[dict[str, Any]] = []
        if config.get("auto_regimen", False):
            target_type = config.get("target_type", "target_range")
            suggested = compute_suggested_regimen(ester, method, target_type)
            if suggested and "schedules" in suggested:
                schedules = suggested["schedules"]
            elif suggested:
                schedules = [{
                    "dose_mg": suggested["dose_mg"],
                    "interval_days": suggested["interval_days"],
                    "phase_days": 0.0,
                    "model_key": suggested.get("model_key", ""),
                }]

        if not schedules:
            dose_mg = config["dose_mg"]
            interval_days = config["interval_days"]
            model_key = resolve_model_key(ester, method, interval_days)
            if not model_key:
                return
            schedules = [{
                "dose_mg": dose_mg,
                "interval_days": interval_days,
                "phase_days": config.get("phase_days", 0.0),
                "model_key": model_key,
            }]

        # Fetch existing automatic dose timestamps to avoid duplicates
        existing_ts = await self.database.get_auto_dose_timestamps(entry_id)

        for sch in schedules:
            sch_dose = sch["dose_mg"]
            sch_interval = sch["interval_days"]
            sch_phase = float(sch.get("phase_days", 0.0))
            sch_model = sch.get("model_key", "")
            if not sch_model:
                sch_model = resolve_model_key(ester, method, sch_interval)
            if not sch_model:
                continue

            interval_sec = sch_interval * 86400.0
            if interval_sec <= 0:
                continue

            if config.get("backfill_doses", False):
                # Backfill: fill the full chart history (90 days, matching
                # the future projection window)
                lookback_ts = now - 90.0 * 86400.0
            else:
                # No backfill: only catch doses since the last refresh
                lookback_ts = now - DEFAULT_UPDATE_INTERVAL - 60

            # Compute anchor timestamp (in user's local timezone)
            now_local = datetime.fromtimestamp(now, tz=local_tz)
            today_dose = now_local.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            today_dose_ts = today_dose.timestamp()

            if sch_phase > 0:
                epoch_day_local = int(now_local.replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).timestamp() // 86400)
                cycle_day_now = epoch_day_local % 28
                days_back = (cycle_day_now - int(sch_phase)) % 28
                anchor_ts = today_dose_ts - days_back * 86400.0
            else:
                anchor_ts = today_dose_ts

            # Walk back to find earliest dose within lookback window
            t = anchor_ts
            while t > lookback_ts:
                t -= interval_sec
            t += interval_sec  # First dose within window

            # Persist past doses that don't already exist
            while t < now:
                # Check within 60s tolerance to avoid duplicates
                if not any(abs(t - ets) < 60 for ets in existing_ts):
                    await self.database.add_dose(
                        config_entry_id=entry_id,
                        model=sch_model,
                        dose_mg=sch_dose,
                        timestamp=t,
                        source="automatic",
                    )
                    existing_ts.add(t)
                t += interval_sec

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from SQLite and compute per-user state."""
        import math

        entry_id = self.config_entry.entry_id
        config = self._get_config()
        now = time.time()

        # Persist any past automatic doses that haven't been recorded yet
        await self._persist_auto_doses(config, now)

        # Prune old doses for this entry (keep 90 days when backfill enabled)
        retention = 90.0 if config.get("backfill_doses", False) else 0.0
        await self.database.prune_stale_doses(entry_id, retention)

        # Get ALL doses and blood tests from database (cross-entry)
        all_manual_doses = await self.database.get_all_doses()
        all_blood_tests = await self.database.get_all_blood_tests()
        all_configs = self._get_all_entry_configs()

        # Unit conversion
        units = config["units"]
        cf = AVAILABLE_UNITS.get(units, {}).get("conversion_factor", 1.0)

        # Group configs by user_id
        user_groups: dict[str, list[dict[str, Any]]] = {}
        for cfg in all_configs:
            uid = cfg.get("user_id", DEFAULT_USER_ID)
            user_groups.setdefault(uid, []).append(cfg)

        # Compute per-user data
        users_data: dict[str, dict[str, Any]] = {}
        for uid, user_configs in user_groups.items():
            user_entry_ids = {cfg["entry_id"] for cfg in user_configs}

            # Filter manual doses belonging to this user's entries
            user_manual_doses = [
                d for d in all_manual_doses
                if d["config_entry_id"] in user_entry_ids
            ]

            # Generate auto doses for this user's configs only
            user_auto_doses: list[dict[str, Any]] = []
            for ucfg in user_configs:
                user_auto_doses.extend(
                    self._generate_auto_doses_for_config(ucfg, now)
                )

            user_combined = user_manual_doses + user_auto_doses

            # Filter blood tests for this user
            user_blood_tests = [
                bt for bt in all_blood_tests
                if bt["config_entry_id"] in user_entry_ids
            ]

            # Compute scaling factor for this user
            scaling_factor, scaling_variance = (
                await self.database.compute_scaling_factor(
                    entry_id,
                    user_combined,
                    all_configs=user_configs,
                    blood_tests=user_blood_tests,
                )
            )

            # Compute current E2 for this user
            user_e2 = compute_e2_at_time(
                now, user_combined, scaling_factor
            ) * cf

            # Blood test baseline (zero-state handling) per user
            baseline_e2 = 0.0
            baseline_test_ts = 0.0
            baseline_candidates = [
                bt for bt in user_blood_tests
                if not bt.get("on_schedule")
            ]
            if baseline_candidates:
                all_negligible = all(
                    compute_e2_at_time(
                        bt["timestamp"], user_combined
                    ) < 1.0
                    for bt in baseline_candidates
                )
                if all_negligible:
                    latest = max(
                        baseline_candidates,
                        key=lambda t: t["timestamp"],
                    )
                    baseline_e2 = latest["level_pg_ml"]
                    baseline_test_ts = latest["timestamp"]

            if baseline_e2 > 0:
                age_days = (now - baseline_test_ts) / 86400.0
                baseline_decayed = baseline_e2 * math.exp(
                    -0.02 * max(0, age_days)
                )
                scaling_factor = 1.0
                scaling_variance = 0.0
                user_e2 += baseline_decayed * cf

            # Compute per-config suggested regimen (for auto_regimen configs)
            enriched_configs = []
            for ucfg in user_configs:
                cfg_copy = dict(ucfg)
                if ucfg.get("auto_regimen", False):
                    sr = compute_suggested_regimen(
                        ucfg["ester"],
                        ucfg["method"],
                        ucfg.get("target_type", "target_range"),
                    )
                    if sr and "schedules" in sr:
                        cfg_copy["suggested_regimen"] = sr
                        cfg_copy["cycle_fit_regimen"] = sr
                    elif sr:
                        cfg_copy["suggested_regimen"] = sr
                        cfg_copy["cycle_fit_regimen"] = None
                    else:
                        cfg_copy["suggested_regimen"] = None
                        cfg_copy["cycle_fit_regimen"] = None
                enriched_configs.append(cfg_copy)

            users_data[uid] = {
                "user_id": uid,
                "doses": user_manual_doses,
                "auto_doses": user_auto_doses,
                "blood_tests": user_blood_tests,
                "scaling_factor": scaling_factor,
                "scaling_variance": scaling_variance,
                "current_e2": round(user_e2, 1),
                "configs": enriched_configs,
                "baseline_e2": round(baseline_e2, 2),
                "baseline_test_ts": baseline_test_ts,
            }

        # This entry's user data (for sensor state)
        my_user_id = config.get("user_id", DEFAULT_USER_ID)
        my_data = users_data.get(my_user_id, {})
        if not my_data:
            _LOGGER.warning(
                "User ID '%s' (entry %s) not found in computed user groups; "
                "sensor will report empty data",
                my_user_id,
                entry_id,
            )

        # Compute suggested regimen if auto_regimen is enabled
        suggested_regimen = None
        cycle_fit_regimen = None
        if config.get("auto_regimen", False):
            suggested_regimen = compute_suggested_regimen(
                config["ester"],
                config["method"],
                config.get("target_type", "target_range"),
            )
            if suggested_regimen and "schedules" in suggested_regimen:
                cycle_fit_regimen = suggested_regimen

        return {
            # Per-user data for the card
            "users": users_data,
            # Flat fields for sensor state (this entry's user)
            "doses": my_data.get("doses", []),
            "auto_doses": my_data.get("auto_doses", []),
            "blood_tests": my_data.get("blood_tests", []),
            "scaling_factor": my_data.get("scaling_factor", 1.0),
            "scaling_variance": my_data.get("scaling_variance", 0.0),
            "current_e2": my_data.get("current_e2", 0.0),
            "config": config,
            "all_configs": all_configs,
            "suggested_regimen": suggested_regimen,
            "cycle_fit_regimen": cycle_fit_regimen,
            "baseline_e2": my_data.get("baseline_e2", 0.0),
            "baseline_test_ts": my_data.get("baseline_test_ts", 0.0),
        }
