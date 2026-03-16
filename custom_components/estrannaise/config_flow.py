"""Config flow for Estrannaise HRT Monitor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
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
    DEFAULT_USER_ID,
    DOMAIN,
    ESTERS,
    METHODS,
    MODE_AUTOMATIC,
    MODE_BOTH,
    MODE_MANUAL,
    compute_suggested_regimen,
    get_dose_units,
    is_combination_supported,
)


class EstrannaisConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Estrannaise."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._schedules: list[dict[str, Any]] = []
        self._setup_mode: str = "manual"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Choose setup mode."""
        if user_input is not None:
            setup_mode = user_input.get("setup_mode", "manual")
            self._setup_mode = setup_mode
            if setup_mode == "guided":
                return await self.async_step_guided_method()
            elif setup_mode == "auto":
                return await self.async_step_ester()
            else:
                self._data[CONF_AUTO_REGIMEN] = False
                return await self.async_step_ester()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("setup_mode", default="manual"): vol.In(
                        {
                            "manual": "Manual setup",
                            "guided": "Guided setup (recommended for beginners)",
                            "auto": "Auto-generate (beta)",
                        }
                    ),
                }
            ),
        )

    async def async_step_ester(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ester selection (manual and auto paths)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_method()

        return self.async_show_form(
            step_id="ester",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ESTER, default=DEFAULT_ESTER): vol.In(
                        ESTERS
                    ),
                }
            ),
        )

    async def async_step_method(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Method selection (filtered by chosen ester)."""
        errors: dict[str, str] = {}
        ester = self._data.get(CONF_ESTER, DEFAULT_ESTER)

        if user_input is not None:
            method = user_input.get(CONF_METHOD, DEFAULT_METHOD)

            if not is_combination_supported(ester, method):
                from .const import ESTER_METHOD_TO_MODEL
                if (ester, method) in ESTER_METHOD_TO_MODEL:
                    errors["base"] = "not_yet_supported"
                else:
                    errors["base"] = "invalid_combination"
            else:
                self._data.update(user_input)
                if self._setup_mode == "auto":
                    return await self.async_step_auto_target()
                return await self.async_step_regimen()

        # Only show methods that are valid for the selected ester
        available_methods = {
            k: v for k, v in METHODS.items()
            if is_combination_supported(ester, k)
        }
        default_method = (
            DEFAULT_METHOD if DEFAULT_METHOD in available_methods
            else next(iter(available_methods))
        )

        return self.async_show_form(
            step_id="method",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_METHOD, default=default_method
                    ): vol.In(available_methods),
                }
            ),
            errors=errors,
        )

    async def async_step_auto_target(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2a (auto path): Choose target range."""
        errors: dict[str, str] = {}

        if user_input is not None:
            target_type = user_input.get(CONF_TARGET_TYPE, DEFAULT_TARGET_TYPE)
            self._data[CONF_TARGET_TYPE] = target_type
            self._data[CONF_DOSE_TIME] = DEFAULT_DOSE_TIME

            ester = self._data.get(CONF_ESTER, DEFAULT_ESTER)
            method = self._data.get(CONF_METHOD, DEFAULT_METHOD)

            # Compute the regimen at config flow time
            suggested = compute_suggested_regimen(ester, method, target_type)

            if suggested and "schedules" in suggested:
                # Multi-schedule cycle fit → discrete entries
                self._schedules = suggested["schedules"]
                return await self.async_step_confirm_schedules()
            elif suggested:
                # Single schedule (target_range) → one concrete entry
                self._schedules = [{
                    "dose_mg": suggested["dose_mg"],
                    "interval_days": suggested["interval_days"],
                    "phase_days": 0.0,
                    "model_key": suggested.get("model_key", ""),
                }]
                return await self.async_step_settings()
            else:
                errors["base"] = "invalid_combination"

        return self.async_show_form(
            step_id="auto_target",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TARGET_TYPE, default=DEFAULT_TARGET_TYPE
                    ): vol.In(
                        {
                            "target_range": "Target range (trough ~200 pg/mL)",
                            "menstrual_range": "Menstrual range (avg ~100 pg/mL)",
                        }
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_confirm_schedules(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2b (auto path): Confirm computed schedules."""
        if user_input is not None:
            return await self.async_step_settings()

        ester = self._data.get(CONF_ESTER, DEFAULT_ESTER)
        ester_name = ESTERS.get(ester, "HRT")
        method = self._data.get(CONF_METHOD, DEFAULT_METHOD)
        method_name = METHODS.get(method, "")

        lines = []
        for i, sch in enumerate(self._schedules, 1):
            lines.append(
                f"{i}. {sch['dose_mg']}mg every {sch['interval_days']}d "
                f"(cycle day {int(sch['phase_days'])})"
            )

        return self.async_show_form(
            step_id="confirm_schedules",
            data_schema=vol.Schema({}),
            description_placeholders={
                "ester": ester_name,
                "method": method_name,
                "schedules": ", ".join(lines),
                "count": str(len(self._schedules)),
            },
        )

    async def async_step_regimen(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2b (manual path): Dose, interval, and tracking mode."""
        if user_input is not None:
            self._data.update(user_input)
            self._data[CONF_TARGET_TYPE] = DEFAULT_TARGET_TYPE
            return await self.async_step_settings()

        method = self._data.get(CONF_METHOD, DEFAULT_METHOD)
        dose_unit = get_dose_units(method)

        return self.async_show_form(
            step_id="regimen",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DOSE_MG, default=DEFAULT_DOSE_MG
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=500)),
                    vol.Required(
                        CONF_INTERVAL_DAYS, default=DEFAULT_INTERVAL_DAYS
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=90)),
                    vol.Required(CONF_MODE, default=DEFAULT_MODE): vol.In(
                        {
                            MODE_MANUAL: "Manual (log each dose)",
                            MODE_AUTOMATIC: "Automatic (recurring schedule)",
                            MODE_BOTH: "Both (recurring + manual extras)",
                        }
                    ),
                    vol.Required(
                        CONF_DOSE_TIME, default=DEFAULT_DOSE_TIME
                    ): str,
                    vol.Optional(
                        CONF_PHASE_DAYS, default=DEFAULT_PHASE_DAYS
                    ): vol.All(
                        vol.Coerce(float), vol.Range(min=0, max=27)
                    ),
                }
            ),
            description_placeholders={"dose_unit": dose_unit},
        )

    # ── Guided beginner setup flow ────────────────────────────────────────

    async def async_step_guided_method(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: How do you take estrogen?"""
        if user_input is not None:
            choice = user_input["guided_method"]
            self._data["_guided_method"] = choice
            if choice == "pills":
                self._data[CONF_ESTER] = "E"
                self._data[CONF_METHOD] = "oral"
                return await self.async_step_guided_pill_dose()
            elif choice == "patches":
                self._data[CONF_ESTER] = "E"
                self._data[CONF_METHOD] = "patch"
                return await self.async_step_guided_patch_strength()
            else:  # injections
                return await self.async_step_guided_injection_ester()

        return self.async_show_form(
            step_id="guided_method",
            data_schema=vol.Schema(
                {
                    vol.Required("guided_method"): vol.In(
                        {
                            "pills": "Pills / tablets",
                            "patches": "Patches",
                            "injections": "Injections",
                        }
                    ),
                }
            ),
        )

    # ── Pills path ──

    async def async_step_guided_pill_dose(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: How many mg per pill?"""
        if user_input is not None:
            self._data["_pill_mg"] = user_input["pill_mg"]
            return await self.async_step_guided_pill_count()

        return self.async_show_form(
            step_id="guided_pill_dose",
            data_schema=vol.Schema(
                {
                    vol.Required("pill_mg", default=2.0): vol.All(
                        vol.Coerce(float), vol.Range(min=0.25, max=8)
                    ),
                }
            ),
        )

    async def async_step_guided_pill_count(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: How many pills at a time?"""
        if user_input is not None:
            count = int(user_input["pill_count"])
            self._data[CONF_DOSE_MG] = self._data["_pill_mg"] * count
            return await self.async_step_guided_schedule()

        return self.async_show_form(
            step_id="guided_pill_count",
            data_schema=vol.Schema(
                {
                    vol.Required("pill_count", default=1): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=10)
                    ),
                }
            ),
        )

    # ── Injections path ──

    async def async_step_guided_injection_ester(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: What type of estrogen do you inject?"""
        if user_input is not None:
            self._data[CONF_ESTER] = user_input["injection_ester"]
            return await self.async_step_guided_injection_route()

        return self.async_show_form(
            step_id="guided_injection_ester",
            data_schema=vol.Schema(
                {
                    vol.Required("injection_ester", default="EV"): vol.In(
                        {
                            "EV": "Estradiol Valerate",
                            "EC": "Estradiol Cypionate (Depo-Estradiol)",
                            "EEn": "Estradiol Enanthate",
                            "EB": "Estradiol Benzoate",
                            "EUn": "Estradiol Undecylate",
                        }
                    ),
                }
            ),
        )

    async def async_step_guided_injection_route(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: IM or SubQ?"""
        if user_input is not None:
            self._data[CONF_METHOD] = user_input["injection_route"]
            return await self.async_step_guided_injection_strength()

        return self.async_show_form(
            step_id="guided_injection_route",
            data_schema=vol.Schema(
                {
                    vol.Required("injection_route", default="im"): vol.In(
                        {
                            "im": "Intramuscular (IM)",
                            "subq": "Subcutaneous (SubQ)",
                        }
                    ),
                }
            ),
        )

    async def async_step_guided_injection_strength(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: Injection concentration (mg per mL)."""
        if user_input is not None:
            self._data["_concentration_mg"] = user_input["concentration_mg"]
            self._data["_concentration_ml"] = user_input["concentration_ml"]
            return await self.async_step_guided_injection_volume()

        return self.async_show_form(
            step_id="guided_injection_strength",
            data_schema=vol.Schema(
                {
                    vol.Required("concentration_mg", default=5.0): vol.All(
                        vol.Coerce(float), vol.Range(min=1, max=100)
                    ),
                    vol.Required("concentration_ml", default=1.0): vol.All(
                        vol.Coerce(float), vol.Range(min=0.1, max=10)
                    ),
                }
            ),
        )

    async def async_step_guided_injection_volume(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: How many mL per injection?"""
        if user_input is not None:
            volume = user_input["injection_volume"]
            conc_mg = self._data["_concentration_mg"]
            conc_ml = self._data["_concentration_ml"]
            self._data[CONF_DOSE_MG] = (conc_mg / conc_ml) * volume
            return await self.async_step_guided_schedule()

        return self.async_show_form(
            step_id="guided_injection_volume",
            data_schema=vol.Schema(
                {
                    vol.Required("injection_volume", default=0.5): vol.All(
                        vol.Coerce(float), vol.Range(min=0.05, max=5)
                    ),
                }
            ),
        )

    # ── Patches path ──

    async def async_step_guided_patch_strength(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: Patch delivery rate."""
        if user_input is not None:
            self._data["_patch_strength"] = user_input["patch_strength"]
            return await self.async_step_guided_patch_count()

        return self.async_show_form(
            step_id="guided_patch_strength",
            data_schema=vol.Schema(
                {
                    vol.Required("patch_strength", default="0.05"): vol.In(
                        {
                            "0.025": "0.025 mg/day (25 mcg/day)",
                            "0.0375": "0.0375 mg/day (37.5 mcg/day)",
                            "0.05": "0.05 mg/day (50 mcg/day)",
                            "0.06": "0.06 mg/day (60 mcg/day)",
                            "0.075": "0.075 mg/day (75 mcg/day)",
                            "0.1": "0.1 mg/day (100 mcg/day)",
                        }
                    ),
                }
            ),
        )

    async def async_step_guided_patch_count(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: How many patches at a time?"""
        if user_input is not None:
            count = int(user_input["patch_count"])
            strength = float(self._data["_patch_strength"])
            self._data[CONF_DOSE_MG] = strength * count
            return await self.async_step_guided_patch_schedule()

        return self.async_show_form(
            step_id="guided_patch_count",
            data_schema=vol.Schema(
                {
                    vol.Required("patch_count", default=1): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=6)
                    ),
                }
            ),
        )

    async def async_step_guided_patch_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: How often do you change patches?"""
        if user_input is not None:
            if user_input["patch_schedule"] == "twice_weekly":
                self._data[CONF_INTERVAL_DAYS] = 3.5
            else:
                self._data[CONF_INTERVAL_DAYS] = 7.0
            return await self.async_step_guided_dose_time()

        return self.async_show_form(
            step_id="guided_patch_schedule",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "patch_schedule", default="twice_weekly"
                    ): vol.In(
                        {
                            "twice_weekly": "Twice a week (every 3-4 days)",
                            "once_weekly": "Once a week (every 7 days)",
                        }
                    ),
                }
            ),
        )

    # ── Common ending steps ──

    async def async_step_guided_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: How often do you dose? (pills & injections)"""
        if user_input is not None:
            self._data[CONF_INTERVAL_DAYS] = user_input["interval_days"]
            if self._data[CONF_INTERVAL_DAYS] <= 1.0:
                # Daily dosing: skip time/offset steps, use defaults
                self._data[CONF_DOSE_TIME] = DEFAULT_DOSE_TIME
                self._data[CONF_PHASE_DAYS] = DEFAULT_PHASE_DAYS
                return await self.async_step_guided_backfill()
            return await self.async_step_guided_dose_time()

        method = self._data.get(CONF_METHOD, DEFAULT_METHOD)
        default_interval = 1.0 if method == "oral" else 7.0

        return self.async_show_form(
            step_id="guided_schedule",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "interval_days", default=default_interval
                    ): vol.All(
                        vol.Coerce(float), vol.Range(min=0.5, max=90)
                    ),
                }
            ),
        )

    async def async_step_guided_dose_time(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: What time of day do you dose?"""
        if user_input is not None:
            self._data[CONF_DOSE_TIME] = user_input.get(
                "dose_time", DEFAULT_DOSE_TIME
            )
            return await self.async_step_guided_days_until()

        return self.async_show_form(
            step_id="guided_dose_time",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "dose_time", default=DEFAULT_DOSE_TIME
                    ): str,
                }
            ),
        )

    async def async_step_guided_days_until(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: How many days until your next dose?"""
        if user_input is not None:
            from datetime import datetime, timedelta

            days_until = int(user_input.get("days_until", 0))
            if days_until > 0:
                next_date = datetime.now() + timedelta(days=days_until)
                epoch_day = int(next_date.timestamp() / 86400)
                phase = float(epoch_day % 28)
                self._data[CONF_PHASE_DAYS] = phase if phase > 0 else 0.0
            else:
                self._data[CONF_PHASE_DAYS] = DEFAULT_PHASE_DAYS
            return await self.async_step_guided_backfill()

        return self.async_show_form(
            step_id="guided_days_until",
            data_schema=vol.Schema(
                {
                    vol.Required("days_until", default=0): vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=90)
                    ),
                }
            ),
        )

    async def async_step_guided_backfill(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Guided: Have you been on this schedule for a while?"""
        if user_input is not None:
            self._data[CONF_BACKFILL_DOSES] = user_input.get(
                "been_on_schedule", False
            )
            self._data[CONF_MODE] = MODE_AUTOMATIC
            self._data[CONF_AUTO_REGIMEN] = False
            self._data[CONF_TARGET_TYPE] = DEFAULT_TARGET_TYPE
            # Clean up temporary guided flow keys
            for key in list(self._data.keys()):
                if key.startswith("_"):
                    del self._data[key]
            return await self.async_step_settings()

        guided = self._data.get("_guided_method", "pills")
        if guided == "pills":
            action = "taking pills on"
        elif guided == "patches":
            action = "wearing patches on"
        else:
            action = "injecting on"

        return self.async_show_form(
            step_id="guided_backfill",
            data_schema=vol.Schema(
                {
                    vol.Required("been_on_schedule", default=True): bool,
                }
            ),
            description_placeholders={"action": action},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: Units and calendar integration."""
        if user_input is not None:
            self._data.update(user_input)
            ester = self._data.get(CONF_ESTER, DEFAULT_ESTER)
            ester_name = ESTERS.get(ester, "HRT")
            method = self._data.get(CONF_METHOD, DEFAULT_METHOD)
            method_name = METHODS.get(method, "")
            units = user_input.get(CONF_UNITS, DEFAULT_UNITS)
            enable_cal = user_input.get(
                CONF_ENABLE_CALENDAR, DEFAULT_ENABLE_CALENDAR
            )

            if self._schedules:
                # Auto-generated: create discrete entries per schedule
                first = self._schedules[0]
                backfill = self._data.get(
                    CONF_BACKFILL_DOSES, DEFAULT_BACKFILL_DOSES
                )
                user_id = self._data.get(
                    CONF_USER_ID, DEFAULT_USER_ID
                )
                first_data = {
                    CONF_ESTER: ester,
                    CONF_METHOD: method,
                    CONF_DOSE_MG: first["dose_mg"],
                    CONF_INTERVAL_DAYS: first["interval_days"],
                    CONF_PHASE_DAYS: first["phase_days"],
                    CONF_MODE: MODE_AUTOMATIC,
                    CONF_DOSE_TIME: self._data.get(
                        CONF_DOSE_TIME, DEFAULT_DOSE_TIME
                    ),
                    CONF_AUTO_REGIMEN: False,
                    CONF_TARGET_TYPE: self._data.get(
                        CONF_TARGET_TYPE, DEFAULT_TARGET_TYPE
                    ),
                    CONF_UNITS: units,
                    CONF_ENABLE_CALENDAR: enable_cal,
                    CONF_BACKFILL_DOSES: backfill,
                    CONF_USER_ID: user_id,
                }
                title = (
                    f"{ester_name} {first['dose_mg']}mg"
                    f"/{first['interval_days']}d ({method_name})"
                )

                # Spawn import flows for remaining schedules
                for sch in self._schedules[1:]:
                    import_data = {
                        CONF_ESTER: ester,
                        CONF_METHOD: method,
                        CONF_DOSE_MG: sch["dose_mg"],
                        CONF_INTERVAL_DAYS: sch["interval_days"],
                        CONF_PHASE_DAYS: sch["phase_days"],
                        CONF_MODE: MODE_AUTOMATIC,
                        CONF_DOSE_TIME: self._data.get(
                            CONF_DOSE_TIME, DEFAULT_DOSE_TIME
                        ),
                        CONF_AUTO_REGIMEN: False,
                        CONF_TARGET_TYPE: self._data.get(
                            CONF_TARGET_TYPE, DEFAULT_TARGET_TYPE
                        ),
                        CONF_UNITS: units,
                        CONF_ENABLE_CALENDAR: enable_cal,
                        CONF_BACKFILL_DOSES: backfill,
                        CONF_USER_ID: user_id,
                        "subsidiary": True,
                    }
                    self.hass.async_create_task(
                        self.hass.config_entries.flow.async_init(
                            DOMAIN,
                            context={
                                "source": config_entries.SOURCE_IMPORT,
                            },
                            data=import_data,
                        )
                    )

                return self.async_create_entry(title=title, data=first_data)

            # Manual path: single entry
            dose = self._data.get(CONF_DOSE_MG, DEFAULT_DOSE_MG)
            interval = self._data.get(
                CONF_INTERVAL_DAYS, DEFAULT_INTERVAL_DAYS
            )
            title = f"{ester_name} {dose}mg/{interval}d ({method_name})"
            return self.async_create_entry(title=title, data=self._data)

        schema_fields: dict = {
            vol.Required(
                CONF_USER_ID, default=DEFAULT_USER_ID
            ): vol.All(str, vol.Length(min=1, max=64)),
            vol.Required(CONF_UNITS, default=DEFAULT_UNITS): vol.In(
                {"pg/mL": "pg/mL", "pmol/L": "pmol/L"}
            ),
            vol.Required(
                CONF_ENABLE_CALENDAR, default=DEFAULT_ENABLE_CALENDAR
            ): bool,
        }
        # Only show backfill if not already answered (e.g. guided flow)
        if CONF_BACKFILL_DOSES not in self._data:
            schema_fields[vol.Required(
                CONF_BACKFILL_DOSES, default=DEFAULT_BACKFILL_DOSES
            )] = bool

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(schema_fields),
        )

    async def async_step_import(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle import of additional auto-generated schedules."""
        if user_input is None:
            return self.async_abort(reason="unknown")

        ester_name = ESTERS.get(
            user_input.get(CONF_ESTER, DEFAULT_ESTER), "HRT"
        )
        method_name = METHODS.get(
            user_input.get(CONF_METHOD, DEFAULT_METHOD), ""
        )
        dose = user_input.get(CONF_DOSE_MG, DEFAULT_DOSE_MG)
        interval = user_input.get(CONF_INTERVAL_DAYS, DEFAULT_INTERVAL_DAYS)
        title = f"{ester_name} {dose}mg/{interval}d ({method_name})"

        return self.async_create_entry(title=title, data=user_input)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EstrannaisOptionsFlow:
        """Get the options flow handler."""
        return EstrannaisOptionsFlow()


class EstrannaisOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Estrannaise."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ester = user_input.get(CONF_ESTER, DEFAULT_ESTER)
            method = user_input.get(CONF_METHOD, DEFAULT_METHOD)

            if not is_combination_supported(ester, method):
                from .const import ESTER_METHOD_TO_MODEL
                if method == "oral" and ester != "E":
                    errors["base"] = "oral_estradiol_only"
                elif (ester, method) in ESTER_METHOD_TO_MODEL:
                    errors["base"] = "not_yet_supported"
                else:
                    errors["base"] = "invalid_combination"
            else:
                # Auto-update entry title from new settings
                ester_name = ESTERS.get(
                    user_input.get(CONF_ESTER, DEFAULT_ESTER), "HRT"
                )
                method_name = METHODS.get(
                    user_input.get(CONF_METHOD, DEFAULT_METHOD), ""
                )
                dose = user_input.get(CONF_DOSE_MG, DEFAULT_DOSE_MG)
                interval = user_input.get(
                    CONF_INTERVAL_DAYS, DEFAULT_INTERVAL_DAYS
                )
                title = f"{ester_name} {dose}mg/{interval}d ({method_name})"
                self.hass.config_entries.async_update_entry(
                    self.config_entry, title=title
                )
                return self.async_create_entry(data=user_input)

        # Merge options over data so saved changes are reflected
        data = {**self.config_entry.data, **self.config_entry.options}

        method = data.get(CONF_METHOD, DEFAULT_METHOD)
        dose_unit = get_dose_units(method)

        # Only show methods valid for the current ester
        current_ester = data.get(CONF_ESTER, DEFAULT_ESTER)
        available_methods = {
            k: v for k, v in METHODS.items()
            if is_combination_supported(current_ester, k)
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USER_ID,
                        default=data.get(CONF_USER_ID, DEFAULT_USER_ID),
                    ): vol.All(str, vol.Length(min=1, max=64)),
                    vol.Required(
                        CONF_ESTER,
                        default=data.get(CONF_ESTER, DEFAULT_ESTER),
                    ): vol.In(ESTERS),
                    vol.Required(
                        CONF_METHOD,
                        default=data.get(CONF_METHOD, DEFAULT_METHOD),
                    ): vol.In(available_methods),
                    vol.Required(
                        CONF_DOSE_MG,
                        default=data.get(CONF_DOSE_MG, DEFAULT_DOSE_MG),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=500)),
                    vol.Required(
                        CONF_INTERVAL_DAYS,
                        default=data.get(CONF_INTERVAL_DAYS, DEFAULT_INTERVAL_DAYS),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=90)),
                    vol.Required(
                        CONF_MODE,
                        default=data.get(CONF_MODE, DEFAULT_MODE),
                    ): vol.In(
                        {
                            MODE_MANUAL: "Manual (log each dose)",
                            MODE_AUTOMATIC: "Automatic (recurring schedule)",
                            MODE_BOTH: "Both (recurring + manual extras)",
                        }
                    ),
                    vol.Required(
                        CONF_DOSE_TIME,
                        default=data.get(CONF_DOSE_TIME, DEFAULT_DOSE_TIME),
                    ): str,
                    vol.Optional(
                        CONF_PHASE_DAYS,
                        default=data.get(CONF_PHASE_DAYS, DEFAULT_PHASE_DAYS),
                    ): vol.All(
                        vol.Coerce(float), vol.Range(min=0, max=27)
                    ),
                    vol.Required(
                        CONF_UNITS,
                        default=data.get(CONF_UNITS, DEFAULT_UNITS),
                    ): vol.In({"pg/mL": "pg/mL", "pmol/L": "pmol/L"}),
                    vol.Required(
                        CONF_ENABLE_CALENDAR,
                        default=data.get(CONF_ENABLE_CALENDAR, DEFAULT_ENABLE_CALENDAR),
                    ): bool,
                    vol.Required(
                        CONF_BACKFILL_DOSES,
                        default=data.get(CONF_BACKFILL_DOSES, DEFAULT_BACKFILL_DOSES),
                    ): bool,
                }
            ),
            description_placeholders={"dose_unit": dose_unit},
            errors=errors,
        )
