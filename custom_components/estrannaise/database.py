"""SQLite database for Estrannaise HRT dose and blood test storage."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from pathlib import Path
from typing import Any

import aiosqlite

from .const import PK_PARAMETERS, PATCH_WEAR_DAYS, terminal_elimination_days

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 2

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS doses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_entry_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    model TEXT NOT NULL,
    dose_mg REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS blood_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_entry_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    level_pg_ml REAL NOT NULL,
    notes TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_doses_entry_ts
    ON doses(config_entry_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_blood_tests_entry_ts
    ON blood_tests(config_entry_id, timestamp);
"""


class EstrannaisDatabase:
    """Async SQLite database wrapper for estrannaise data."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def async_setup(self) -> None:
        """Open the database and create tables if needed."""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        # WAL mode allows concurrent reads during writes
        await self._db.execute("PRAGMA journal_mode = WAL")
        # Wait up to 5s for locks instead of failing immediately
        await self._db.execute("PRAGMA busy_timeout = 5000")
        await self._db.executescript(CREATE_TABLES)
        await self._db.commit()

        # Schema migration: add on_schedule column (v2)
        cursor = await self._db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        db_version = row[0] if row else 0
        if db_version < 2:
            try:
                await self._db.execute(
                    "ALTER TABLE blood_tests ADD COLUMN on_schedule INTEGER"
                )
            except Exception as exc:  # noqa: BLE001
                # "duplicate column name" means column already exists — safe to skip
                if "duplicate column" not in str(exc).lower():
                    _LOGGER.warning("Schema migration failed: %s", exc)
                    raise
            await self._db.execute("PRAGMA user_version = 2")
            await self._db.commit()
            _LOGGER.info("Estrannaise database migrated to schema v2")

        _LOGGER.debug("Estrannaise database initialized at %s", self._db_path)

    async def async_close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ── Doses ────────────────────────────────────────────────────────────────

    async def add_dose(
        self,
        config_entry_id: str,
        model: str,
        dose_mg: float,
        timestamp: float | None = None,
        source: str = "manual",
    ) -> int:
        """Record a dose. Returns the new row ID."""
        now = time.time()
        ts = timestamp if timestamp is not None else now
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        async with self._write_lock:
            cursor = await self._db.execute(
                "INSERT INTO doses (config_entry_id, timestamp, model, dose_mg, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (config_entry_id, ts, model, dose_mg, source, now),
            )
            await self._db.commit()
            row_id = cursor.lastrowid
        return row_id  # type: ignore[return-value]

    async def get_doses(
        self,
        config_entry_id: str,
        since_timestamp: float | None = None,
    ) -> list[dict[str, Any]]:
        """Get dose records for a config entry, optionally filtered by time."""
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        if since_timestamp is not None:
            cursor = await self._db.execute(
                "SELECT id, config_entry_id, timestamp, model, dose_mg, source "
                "FROM doses WHERE config_entry_id = ? AND timestamp >= ? "
                "ORDER BY timestamp ASC",
                (config_entry_id, since_timestamp),
            )
        else:
            cursor = await self._db.execute(
                "SELECT id, config_entry_id, timestamp, model, dose_mg, source "
                "FROM doses WHERE config_entry_id = ? "
                "ORDER BY timestamp ASC",
                (config_entry_id,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_all_doses(
        self,
        since_timestamp: float | None = None,
    ) -> list[dict[str, Any]]:
        """Get dose records across all config entries."""
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        if since_timestamp is not None:
            cursor = await self._db.execute(
                "SELECT id, config_entry_id, timestamp, model, dose_mg, source "
                "FROM doses WHERE timestamp >= ? "
                "ORDER BY timestamp ASC",
                (since_timestamp,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT id, config_entry_id, timestamp, model, dose_mg, source "
                "FROM doses ORDER BY timestamp ASC",
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_dose(self, config_entry_id: str, dose_id: int) -> bool:
        """Delete a dose by ID. Returns True if a row was deleted."""
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        async with self._write_lock:
            cursor = await self._db.execute(
                "DELETE FROM doses WHERE id = ? AND config_entry_id = ?",
                (dose_id, config_entry_id),
            )
            await self._db.commit()
        return cursor.rowcount > 0

    # ── Blood tests ──────────────────────────────────────────────────────────

    async def add_blood_test(
        self,
        config_entry_id: str,
        level_pg_ml: float,
        timestamp: float | None = None,
        notes: str | None = None,
        on_schedule: bool | None = None,
    ) -> int:
        """Record a blood test result. Returns the new row ID."""
        now = time.time()
        ts = timestamp if timestamp is not None else now
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        on_sched_int = (
            int(on_schedule) if on_schedule is not None else None
        )
        async with self._write_lock:
            cursor = await self._db.execute(
                "INSERT INTO blood_tests "
                "(config_entry_id, timestamp, level_pg_ml, notes, created_at, on_schedule) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (config_entry_id, ts, level_pg_ml, notes, now, on_sched_int),
            )
            await self._db.commit()
            row_id = cursor.lastrowid
        return row_id  # type: ignore[return-value]

    async def get_blood_tests(
        self, config_entry_id: str
    ) -> list[dict[str, Any]]:
        """Get all blood test records for a config entry."""
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        cursor = await self._db.execute(
            "SELECT id, config_entry_id, timestamp, level_pg_ml, notes, on_schedule "
            "FROM blood_tests WHERE config_entry_id = ? "
            "ORDER BY timestamp ASC",
            (config_entry_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_all_blood_tests(self) -> list[dict[str, Any]]:
        """Get all blood test records across all config entries."""
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        cursor = await self._db.execute(
            "SELECT id, config_entry_id, timestamp, level_pg_ml, notes, on_schedule "
            "FROM blood_tests ORDER BY timestamp ASC",
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_blood_test(
        self, config_entry_id: str, test_id: int
    ) -> bool:
        """Delete a blood test by ID. Returns True if a row was deleted."""
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        async with self._write_lock:
            cursor = await self._db.execute(
                "DELETE FROM blood_tests WHERE id = ? AND config_entry_id = ?",
                (test_id, config_entry_id),
            )
            await self._db.commit()
        return cursor.rowcount > 0

    # ── Clear all data ────────────────────────────────────────────────────────

    async def clear_all_data(self) -> None:
        """Delete all doses and blood tests from the database."""
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        async with self._write_lock:
            await self._db.execute("DELETE FROM doses")
            await self._db.execute("DELETE FROM blood_tests")
            await self._db.commit()
        _LOGGER.info("All estrannaise dose and blood test data cleared")

    # ── Scaling factor ───────────────────────────────────────────────────────

    async def compute_scaling_factor(
        self,
        config_entry_id: str,
        all_doses: list[dict[str, Any]],
        all_configs: list[dict[str, Any]] | None = None,
        decay_lambda: float = 0.02,
        blood_tests: list[dict[str, Any]] | None = None,
    ) -> tuple[float, float]:
        """Compute exponentially-weighted scaling factor from blood tests.

        For each blood test, compares measured level to predicted level from
        the PK model at that timestamp. Recent tests are weighted more heavily.

        For tests marked on_schedule=True where predicted E2 is negligible
        (no dose records that far back), virtual steady-state doses are
        generated from all_configs to produce a meaningful prediction.

        If *blood_tests* is provided, uses those directly instead of
        fetching all tests from the database (for per-user computation).

        decay_lambda: exponential decay rate for weighting (per day).
        Returns (factor, variance) where factor is clamped to [0.0, 2.0].
        Returns (1.0, 0.0) if no usable tests.
        """
        from .const import compute_e2_at_time, compute_steady_state_e2_at_time

        tests = blood_tests if blood_tests is not None else await self.get_all_blood_tests()
        if not tests:
            return (1.0, 0.0)

        now = time.time()
        weighted_sum = 0.0
        weight_total = 0.0
        ratios_and_weights: list[tuple[float, float]] = []

        for test in tests:
            predicted = compute_e2_at_time(
                test["timestamp"], all_doses, scaling_factor=1.0
            )
            if predicted < 1.0:
                # Try virtual steady-state for on_schedule tests
                on_schedule = test.get("on_schedule")
                if on_schedule and all_configs:
                    predicted = compute_steady_state_e2_at_time(
                        test["timestamp"], all_configs
                    )
                if predicted < 1.0:
                    continue

            ratio = test["level_pg_ml"] / predicted
            age_days = (now - test["timestamp"]) / 86400.0
            weight = math.exp(-decay_lambda * age_days)

            weighted_sum += ratio * weight
            weight_total += weight
            ratios_and_weights.append((ratio, weight))

        if weight_total <= 0:
            return (1.0, 0.0)

        factor = weighted_sum / weight_total

        # Compute weighted variance
        var_sum = 0.0
        for ratio, weight in ratios_and_weights:
            var_sum += weight * (ratio - factor) ** 2
        variance = var_sum / weight_total

        return (max(0.0, min(2.0, factor)), variance)

    # ── Auto dose tracking ─────────────────────────────────────────────────

    async def get_auto_dose_timestamps(
        self, config_entry_id: str
    ) -> set[float]:
        """Return timestamps of all automatic doses for an entry."""
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        cursor = await self._db.execute(
            "SELECT timestamp FROM doses "
            "WHERE config_entry_id = ? AND source = 'automatic' "
            "ORDER BY timestamp ASC",
            (config_entry_id,),
        )
        rows = await cursor.fetchall()
        return {row["timestamp"] for row in rows}

    # ── Stale dose pruning ───────────────────────────────────────────────────

    async def prune_stale_doses(
        self, config_entry_id: str, min_retention_days: float = 0.0
    ) -> int:
        """Remove doses whose contribution has decayed to ~1% of peak.

        When *min_retention_days* is set (e.g. for backfill entries), doses
        are kept for at least that many days regardless of the PK model.
        Returns the number of rows deleted.
        """
        if self._db is None:
            raise RuntimeError("Estrannaise database is not initialized")
        now = time.time()
        total_deleted = 0

        async with self._write_lock:
            for model, _params in PK_PARAMETERS.items():
                max_age_days = max(
                    terminal_elimination_days(model), min_retention_days
                )
                cutoff_ts = now - (max_age_days * 86400.0)
                cursor = await self._db.execute(
                    "DELETE FROM doses WHERE config_entry_id = ? "
                    "AND model = ? AND timestamp < ?",
                    (config_entry_id, model, cutoff_ts),
                )
                total_deleted += cursor.rowcount

            if total_deleted > 0:
                await self._db.commit()
                _LOGGER.debug("Pruned %d stale doses for %s", total_deleted, config_entry_id)

        return total_deleted
