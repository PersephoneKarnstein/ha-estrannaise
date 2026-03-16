"""Sensor platform for Estrannaise HRT Monitor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    APPROXIMATION_DISCLAIMER,
    ATTR_ALL_CONFIGS,
    ATTR_AUTO_REGIMEN,
    ATTR_BLOOD_TESTS,
    ATTR_CURRENT_E2,
    ATTR_DOSE_MG,
    ATTR_DOSE_TIME,
    ATTR_DOSES,
    ATTR_INTERVAL_DAYS,
    ATTR_MENSTRUAL_CYCLE_DATA,
    ATTR_METHOD,
    ATTR_MODE,
    ATTR_MODEL,
    ATTR_PK_PARAMETERS,
    ATTR_SCALING_FACTOR,
    ATTR_SCALING_VARIANCE,
    ATTR_CYCLE_FIT_REGIMEN,
    ATTR_SUGGESTED_REGIMEN,
    ATTR_TARGET_TYPE,
    ATTR_UNITS,
    ATTR_USER_ID,
    ATTR_USERS,
    DOMAIN,
    ESTERS,
    MENSTRUAL_CYCLE_DATA,
    METHODS,
    PK_PARAMETERS,
    PATCH_WEAR_DAYS,
    SUGGESTED_INTERVALS,
    TARGET_TROUGH,
    resolve_model_key,
)
from .coordinator import EstrannaisCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Estrannaise sensor from a config entry."""
    # Subsidiary entries (auto-imported schedules) don't create sensor entities;
    # their dose schedules are aggregated by the primary entry's coordinator.
    if entry.data.get("subsidiary", False):
        return
    coordinator: EstrannaisCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EstrannaiseSensor(coordinator, entry)])


class EstrannaiseSensor(
    CoordinatorEntity[EstrannaisCoordinator], SensorEntity
):
    """Sensor reporting current estimated estradiol level."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:chart-bell-curve-cumulative"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: EstrannaisCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        ester_key = entry.data.get("ester", "")
        method_key = entry.data.get("method", "")
        ester_name = ESTERS.get(ester_key, entry.data.get("label", "HRT"))
        method_name = METHODS.get(method_key, "")
        user_id = entry.options.get("user_id", entry.data.get("user_id", "default"))
        suffix = f" ({method_name})" if method_name else ""
        user_suffix = f" [{user_id}]" if user_id != "default" else ""
        self._attr_name = f"Estrannaise {ester_name}{suffix}{user_suffix}"
        self._attr_unique_id = f"{entry.entry_id}_e2_level"
        self._entry = entry

    @property
    def native_value(self) -> float | None:
        """Return the current estimated E2 level."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("current_e2")

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        if self.coordinator.data:
            config = self.coordinator.data.get("config", {})
            return config.get("units", "pg/mL")
        return "pg/mL"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return dose data, blood tests, and PK parameters for the card."""
        if not self.coordinator.data:
            return {}

        data = self.coordinator.data
        config = data.get("config", {})

        return {
            ATTR_DOSES: data.get("doses", []),
            ATTR_BLOOD_TESTS: data.get("blood_tests", []),
            ATTR_SCALING_FACTOR: data.get("scaling_factor", 1.0),
            ATTR_SCALING_VARIANCE: data.get("scaling_variance", 0.0),
            ATTR_MODEL: resolve_model_key(
                config.get("ester", ""),
                config.get("method", "im"),
                config.get("interval_days", 7),
            ) or config.get("ester", ""),
            ATTR_METHOD: config.get("method", "im"),
            ATTR_DOSE_MG: config.get("dose_mg", 0),
            ATTR_INTERVAL_DAYS: config.get("interval_days", 0),
            ATTR_MODE: config.get("mode", "manual"),
            ATTR_UNITS: config.get("units", "pg/mL"),
            ATTR_DOSE_TIME: config.get("dose_time", "08:00"),
            ATTR_AUTO_REGIMEN: config.get("auto_regimen", False),
            ATTR_TARGET_TYPE: config.get("target_type", "target_range"),
            ATTR_SUGGESTED_REGIMEN: data.get("suggested_regimen"),
            ATTR_CYCLE_FIT_REGIMEN: data.get("cycle_fit_regimen"),
            "baseline_e2": data.get("baseline_e2", 0.0),
            "baseline_test_ts": data.get("baseline_test_ts", 0.0),
            ATTR_USER_ID: config.get("user_id", "default"),
            ATTR_USERS: data.get("users", {}),
            ATTR_PK_PARAMETERS: PK_PARAMETERS,
            ATTR_MENSTRUAL_CYCLE_DATA: MENSTRUAL_CYCLE_DATA,
            ATTR_ALL_CONFIGS: data.get("all_configs", []),
            "patch_wear_days": PATCH_WEAR_DAYS,
            "target_range": {"lower": 100, "upper": 200},
            "target_trough": TARGET_TROUGH,
            "suggested_intervals": SUGGESTED_INTERVALS,
            "esters": ESTERS,
            "methods": METHODS,
            "approximation_disclaimer": APPROXIMATION_DISCLAIMER,
        }
