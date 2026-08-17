"""Tests for the extracted, HA-free dose scheduling logic."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from standalone.core import schedule  # noqa: E402

TZ = ZoneInfo("America/Vancouver")

# A fixed instant so tests never depend on the wall clock:
# 2026-06-15 12:00:00 local (Vancouver, PDT).
NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=TZ).timestamp()

WEEKLY = {
    "ester": "EEn",
    "method": "im",
    "dose_mg": 4.0,
    "interval_days": 7.0,
    "mode": "automatic",
    "dose_time": "08:00",
    "auto_regimen": False,
    "phase_days": 0.0,
    "backfill_doses": False,
}


def cfg(**overrides):
    return {**WEEKLY, **overrides}


class TestParseDoseTime:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("08:00", (8, 0)),
            ("23:59", (23, 59)),
            ("7", (7, 0)),
            ("00:00", (0, 0)),
        ],
    )
    def test_valid(self, value, expected):
        assert schedule.parse_dose_time(value) == expected

    @pytest.mark.parametrize("value", ["", None, "abc", "not:valid", ":"])
    def test_falls_back_to_eight(self, value):
        assert schedule.parse_dose_time(value) == (8, 0)

    def test_clamps_out_of_range(self):
        assert schedule.parse_dose_time("99:99") == (23, 59)


class TestIsScheduled:
    @pytest.mark.parametrize("mode,expected", [
        ("manual", False), ("automatic", True), ("both", True),
    ])
    def test_modes(self, mode, expected):
        assert schedule.is_scheduled(cfg(mode=mode)) is expected

    def test_missing_mode_defaults_manual(self):
        assert schedule.is_scheduled({"ester": "EEn", "method": "im"}) is False


class TestLocalDoseAnchor:
    def test_anchors_to_local_time_of_day(self):
        ts = schedule.local_dose_anchor(NOW, 8, 0, TZ)
        assert datetime.fromtimestamp(ts, tz=TZ).hour == 8
        assert datetime.fromtimestamp(ts, tz=TZ).minute == 0

    def test_stays_on_same_local_day(self):
        ts = schedule.local_dose_anchor(NOW, 8, 0, TZ)
        assert datetime.fromtimestamp(ts, tz=TZ).date() == datetime.fromtimestamp(
            NOW, tz=TZ
        ).date()


class TestGenerateAutoDoses:
    def test_manual_mode_generates_nothing(self):
        assert schedule.generate_auto_doses(cfg(mode="manual"), NOW, TZ) == []

    def test_zero_interval_generates_nothing(self):
        assert schedule.generate_auto_doses(cfg(interval_days=0), NOW, TZ) == []

    def test_all_doses_are_in_the_future(self):
        doses = schedule.generate_auto_doses(cfg(), NOW, TZ)
        assert doses, "expected projected doses"
        assert all(d["timestamp"] > NOW for d in doses)

    def test_spacing_matches_interval(self):
        doses = schedule.generate_auto_doses(cfg(), NOW, TZ)
        gaps = [
            doses[i + 1]["timestamp"] - doses[i]["timestamp"]
            for i in range(len(doses) - 1)
        ]
        assert all(abs(g - 7 * 86400.0) < 1.0 for g in gaps)

    def test_first_dose_within_one_interval(self):
        doses = schedule.generate_auto_doses(cfg(), NOW, TZ)
        assert doses[0]["timestamp"] - NOW <= 7 * 86400.0

    def test_respects_projection_window(self):
        doses = schedule.generate_auto_doses(cfg(), NOW, TZ, lookback_days=14.0)
        assert all(d["timestamp"] <= NOW + 14 * 86400.0 for d in doses)
        assert len(doses) == 2

    def test_marked_automatic_and_unsaved(self):
        for d in schedule.generate_auto_doses(cfg(), NOW, TZ):
            assert d["source"] == "automatic"
            assert d["id"] is None

    def test_unsupported_combination_generates_nothing(self):
        assert schedule.generate_auto_doses(
            cfg(ester="nonexistent", method="im"), NOW, TZ
        ) == []


class TestPendingAutoDoses:
    def test_manual_mode_pends_nothing(self):
        assert schedule.pending_auto_doses(cfg(mode="manual"), NOW, TZ) == []

    def test_all_pending_are_in_the_past(self):
        pending = schedule.pending_auto_doses(cfg(backfill_doses=True), NOW, TZ)
        assert pending
        assert all(d["timestamp"] < NOW for d in pending)

    def test_backfill_covers_the_projection_window(self):
        pending = schedule.pending_auto_doses(cfg(backfill_doses=True), NOW, TZ)
        # 90 days at 7-day intervals -> 12 or 13 depending on anchor alignment.
        assert 12 <= len(pending) <= 14
        oldest = min(d["timestamp"] for d in pending)
        assert oldest >= NOW - 91 * 86400.0

    def test_without_backfill_only_catches_recent(self):
        pending = schedule.pending_auto_doses(cfg(backfill_doses=False), NOW, TZ)
        assert len(pending) <= 1

    def test_existing_timestamps_are_not_duplicated(self):
        first = schedule.pending_auto_doses(cfg(backfill_doses=True), NOW, TZ)
        existing = {d["timestamp"] for d in first}
        second = schedule.pending_auto_doses(
            cfg(backfill_doses=True), NOW, TZ, existing_timestamps=existing
        )
        assert second == []

    def test_dedup_tolerates_small_clock_drift(self):
        first = schedule.pending_auto_doses(cfg(backfill_doses=True), NOW, TZ)
        # Shift every known timestamp by 30s -- still the same dose.
        drifted = {d["timestamp"] + 30 for d in first}
        second = schedule.pending_auto_doses(
            cfg(backfill_doses=True), NOW, TZ, existing_timestamps=drifted
        )
        assert second == []

    def test_pending_carries_no_id(self):
        for d in schedule.pending_auto_doses(cfg(backfill_doses=True), NOW, TZ):
            assert "id" not in d
            assert d["source"] == "automatic"


class TestResolveSchedules:
    def test_plain_config_yields_one_schedule(self):
        schedules = schedule.resolve_schedules(cfg())
        assert len(schedules) == 1
        assert schedules[0]["interval_days"] == 7.0
        assert schedules[0]["model_key"]

    def test_unsupported_combination_yields_none(self):
        assert schedule.resolve_schedules(cfg(ester="nope", method="im")) == []


class TestTimezoneHandling:
    def test_different_zones_anchor_differently(self):
        vancouver = schedule.generate_auto_doses(cfg(), NOW, TZ)
        tokyo = schedule.generate_auto_doses(cfg(), NOW, ZoneInfo("Asia/Tokyo"))
        assert vancouver[0]["timestamp"] != tokyo[0]["timestamp"]

    def test_dose_lands_at_configured_local_hour(self):
        doses = schedule.generate_auto_doses(cfg(dose_time="21:30"), NOW, TZ)
        first = datetime.fromtimestamp(doses[0]["timestamp"], tz=TZ)
        assert (first.hour, first.minute) == (21, 30)
