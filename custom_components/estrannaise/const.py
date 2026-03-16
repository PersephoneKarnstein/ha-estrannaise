"""Constants for the Estrannaise HRT Monitor integration."""

from __future__ import annotations

import math

DOMAIN = "estrannaise"

PLATFORMS = ["sensor", "calendar", "button"]

# ── Config keys ──────────────────────────────────────────────────────────────

CONF_ESTER = "ester"
CONF_METHOD = "method"
CONF_DOSE_MG = "dose_mg"
CONF_INTERVAL_DAYS = "interval_days"
CONF_MODE = "mode"
CONF_UNITS = "units"
CONF_ENABLE_CALENDAR = "enable_calendar"
CONF_DOSE_TIME = "dose_time"
CONF_AUTO_REGIMEN = "auto_regimen"
CONF_TARGET_TYPE = "target_type"
CONF_PHASE_DAYS = "phase_days"
CONF_BACKFILL_DOSES = "backfill_doses"
CONF_USER_ID = "user_id"

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_ESTER = "EEn"
DEFAULT_METHOD = "im"
DEFAULT_DOSE_MG = 4.0
DEFAULT_INTERVAL_DAYS = 7.0
DEFAULT_MODE = "manual"
DEFAULT_UNITS = "pg/mL"
DEFAULT_ENABLE_CALENDAR = False
DEFAULT_DOSE_TIME = "08:00"
DEFAULT_AUTO_REGIMEN = False
DEFAULT_TARGET_TYPE = "target_range"
DEFAULT_PHASE_DAYS = 0.0
DEFAULT_BACKFILL_DOSES = False
DEFAULT_USER_ID = "default"
DEFAULT_UPDATE_INTERVAL = 300  # 5 minutes

# ── Dosing modes ─────────────────────────────────────────────────────────────

MODE_AUTOMATIC = "automatic"
MODE_MANUAL = "manual"
MODE_BOTH = "both"

MODES = [MODE_AUTOMATIC, MODE_MANUAL, MODE_BOTH]

# ── Attribute names ──────────────────────────────────────────────────────────

ATTR_DOSES = "doses"
ATTR_BLOOD_TESTS = "blood_tests"
ATTR_SCALING_FACTOR = "scaling_factor"
ATTR_SCALING_VARIANCE = "scaling_variance"
ATTR_MODEL = "model"
ATTR_METHOD = "method"
ATTR_DOSE_MG = "dose_mg"
ATTR_INTERVAL_DAYS = "interval_days"
ATTR_MODE = "mode"
ATTR_UNITS = "units"
ATTR_PK_PARAMETERS = "pk_parameters"
ATTR_MENSTRUAL_CYCLE_DATA = "menstrual_cycle_data"
ATTR_CURRENT_E2 = "current_e2"
ATTR_ALL_CONFIGS = "all_configs"
ATTR_DOSE_TIME = "dose_time"
ATTR_AUTO_REGIMEN = "auto_regimen"
ATTR_TARGET_TYPE = "target_type"
ATTR_SUGGESTED_REGIMEN = "suggested_regimen"
ATTR_CYCLE_FIT_REGIMEN = "cycle_fit_regimen"
ATTR_USER_ID = "user_id"
ATTR_USERS = "users"

# ── Target range (WPATH SOC 8 / Endocrine Society) ──────────────────────────

TARGET_RANGE_LOWER = 100  # pg/mL
TARGET_RANGE_UPPER = 200  # pg/mL

# ── Unit conversions ─────────────────────────────────────────────────────────

AVAILABLE_UNITS = {
    "pg/mL": {"conversion_factor": 1.0, "precision": 0},
    "pmol/L": {"conversion_factor": 3.6713, "precision": 0},
}

# ── Estradiol esters ─────────────────────────────────────────────────────────

ESTERS: dict[str, str] = {
    "E": "Estradiol",
    "EB": "Estradiol Benzoate",
    "EV": "Estradiol Valerate",
    "EEn": "Estradiol Enanthate",
    "EC": "Estradiol Cypionate",
    "EUn": "Estradiol Undecylate",
}

# ── Dosing methods ───────────────────────────────────────────────────────────

METHODS: dict[str, str] = {
    "im": "Intramuscular",
    "subq": "Subcutaneous",
    "patch": "Transdermal Patch",
    "oral": "Oral (micronized Estradiol)",
}

# ── Ester + method → internal PK model key ───────────────────────────────────

ESTER_METHOD_TO_MODEL: dict[tuple[str, str], str] = {
    ("EB", "im"): "EB im",
    ("EV", "im"): "EV im",
    ("EEn", "im"): "EEn im",
    ("EC", "im"): "EC im",
    ("EUn", "im"): "EUn im",
    # SubQ maps to IM params for most esters (research shows nearly identical PK);
    # EUn SubQ has its own community-derived model
    ("EB", "subq"): "EB im",
    ("EV", "subq"): "EV im",
    ("EEn", "subq"): "EEn im",
    ("EC", "subq"): "EC im",
    ("EUn", "subq"): "EUn casubq",
    ("E", "patch"): "patch",
    # Oral micronized estradiol — uses 3-compartment model with k1 very large
    # to approximate the Bateman (1-compartment absorption-elimination) curve
    ("E", "oral"): "E oral",
}

# ── PK Parameters [d, k1, k2, k3] ───────────────────────────────────────────
# From estrannaise.js (src/modeldata.js)
# Three-compartment model parameters estimated via Bayesian inference (Esterlabe.jl)

PK_PARAMETERS: dict[str, list[float]] = {
    "EB im": [1893.1, 0.67, 61.5, 4.34],
    "EV im": [478.0, 0.236, 4.85, 1.24],
    "EEn im": [191.4, 0.119, 0.601, 0.402],
    "EC im": [246.0, 0.0825, 3.57, 0.669],
    "EUn im": [471.5, 0.01729, 6.528, 2.285],
    "EUn casubq": [16.15, 0.046, 0.022, 0.101],
    "patch tw": [16.792, 0.283, 5.592, 4.3],
    "patch ow": [59.481, 0.107, 7.842, 5.193],
    # Oral micronized estradiol: k1=100 (instant pass-through), k2=8.88 (absorption),
    # k3=1.032 (apparent elimination t1/2≈16h). Calibrated to Cavg≈50 pg/mL per mg/day.
    "E oral": [51.5, 100.0, 8.88, 1.032],
}

# Patch wear durations (days)
PATCH_WEAR_DAYS: dict[str, float] = {
    "patch tw": 3.5,
    "patch ow": 7.0,
}

# ── Approximation disclaimer ─────────────────────────────────────────────────

APPROXIMATION_DISCLAIMER = (
    "Estimated levels are pharmacokinetic APPROXIMATIONS based on population"
    " models, not actual blood serum measurements. Individual absorption,"
    " metabolism, and other factors can cause significant variation."
    " Always confirm with blood tests."
)

# ── Recommended intervals per PK model (from pghrt.diy) ─────────────────────

SUGGESTED_INTERVALS: dict[str, list[float]] = {
    "EB im": [2.0, 3.0],
    "EV im": [3.5, 5.0, 7.0],
    "EEn im": [7.0, 10.0],
    "EC im": [7.0],
    "EUn im": [14.0, 28.0],
    "EUn casubq": [14.0, 28.0],
    "patch tw": [3.5],
    "patch ow": [7.0],
    "E oral": [1.0],
}

# SubQ esters (except EUn) map to IM model keys, so SUGGESTED_INTERVALS
# is looked up via the resolved model key (e.g., "EV im" for EV subq).

# Target trough levels (pg/mL) for auto-regimen
TARGET_TROUGH: dict[str, float] = {
    "target_range": 200.0,      # WPATH/Endocrine Society target range midpoint trough
    "menstrual_range": 100.0,   # approximate mean of menstrual cycle E2
}

# ── Ester/method helpers ─────────────────────────────────────────────────────


def resolve_model_key(
    ester: str, method: str, interval_days: float = 7.0
) -> str | None:
    """Resolve ester + method to internal PK model key.

    For patches, selects twice-weekly or once-weekly model based on interval.
    Returns None if the combination is not recognized.
    """
    key = ESTER_METHOD_TO_MODEL.get((ester, method))
    if key == "patch":
        return "patch tw" if interval_days <= 5.0 else "patch ow"
    return key


def is_combination_supported(ester: str, method: str) -> bool:
    """Check if an ester+method combination has PK parameters available."""
    key = ESTER_METHOD_TO_MODEL.get((ester, method))
    if key is None:
        return False
    if key == "patch":
        return True  # both patch tw/ow are in PK_PARAMETERS
    return key in PK_PARAMETERS


def get_dose_units(method: str) -> str:
    """Return dose unit string for a dosing method."""
    return "mcg/day" if method == "patch" else "mg"


def compute_suggested_regimen(
    ester: str, method: str, target_type: str = "target_range"
) -> dict[str, Any] | None:
    """Compute a suggested regimen for the given ester+method and target.

    Returns dict with 'dose_mg', 'interval_days', 'model_key', or None if
    the combination is not supported.
    """
    from typing import Any

    # For menstrual range, use multi-schedule cycle fitting
    if target_type == "menstrual_range":
        return compute_cycle_fit_regimen(ester, method)

    target_trough = TARGET_TROUGH.get(target_type, 200.0)

    # Try the first recommended interval for this ester+method
    model_key = ESTER_METHOD_TO_MODEL.get((ester, method))
    if model_key is None:
        return None
    if model_key == "patch":
        # Default to twice-weekly for patch
        model_key = "patch tw"

    params = PK_PARAMETERS.get(model_key)
    if not params:
        return None

    intervals = SUGGESTED_INTERVALS.get(model_key, [7.0])

    # Use the first (most recommended) valid interval
    d, k1, k2, k3 = params
    for interval in intervals:
        # Check ≤ 4 doses per week constraint
        if 7.0 / interval > 4.0:
            continue

        # Compute steady-state trough per mg dose
        trough_per_mg = 0.0
        for n in range(1, 60):
            t = n * interval
            if model_key in PATCH_WEAR_DAYS:
                w = PATCH_WEAR_DAYS[model_key]
                trough_per_mg += e2_patch_3c(t, 1.0, d, k1, k2, k3, w)
            else:
                trough_per_mg += e2_curve_3c(t, 1.0, d, k1, k2, k3)

        if trough_per_mg <= 0:
            continue

        dose = target_trough / trough_per_mg
        if model_key in PATCH_WEAR_DAYS:
            # dose is in mcg/day (PK model units); convert to mg/day
            dose /= 1000.0
            dose = round(dose / 0.025) * 0.025  # 25 mcg/day steps
            dose = max(0.025, min(0.4, dose))
        else:
            dose = round(dose * 2) / 2  # 0.5 mg increments
            dose = max(0.5, min(20.0, dose))

        return {
            "dose_mg": dose,
            "interval_days": interval,
            "model_key": model_key,
        }

    return None


# ── Menstrual cycle reference data (28-day, pg/mL) ──────────────────────────
# From estrannaise.js (src/modeldata.js)
# Mean + 5th/95th percentile estradiol levels across cycle

MENSTRUAL_CYCLE_DATA: dict[str, list[float]] = {
    "t": [
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
        15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
    ],
    "E2": [
        37.99, 40.59, 37.49, 34.99, 35.49, 39.54, 41.99, 44.34, 53.43,
        58.58, 71.43, 98.92, 132.31, 177.35, 255.88, 182.80, 85.23,
        70.98, 87.97, 109.92, 122.77, 132.56, 150.30, 133.81, 137.16,
        134.96, 92.73, 85.68, 46.34, 41.19,
    ],
    "E2p5": [
        15.68, 17.99, 20.48, 21.63, 22.60, 23.86, 25.44, 30.64, 33.96,
        42.95, 51.88, 50.79, 65.79, 91.89, 137.25, 131.30, 43.55,
        42.12, 56.83, 73.49, 79.70, 72.75, 79.46, 76.79, 76.05,
        80.22, 57.26, 47.62, 27.77, 25.60,
    ],
    "E2p95": [
        52.97, 51.12, 51.58, 54.74, 53.59, 57.08, 61.20, 60.16, 72.79,
        85.36, 94.46, 133.70, 218.89, 314.28, 413.41, 388.28, 140.11,
        108.52, 135.06, 181.42, 191.73, 196.05, 189.45, 195.64, 208.23,
        219.75, 174.38, 148.77, 135.58, 188.92,
    ],
}


# ── PK helper (Python-side, for sensor state) ───────────────────────────────

def terminal_elimination_days(model: str, nb_half_lives: float = 5.0) -> float:
    """Estimate when a dose's contribution drops to ~1% of peak (in days)."""
    params = PK_PARAMETERS.get(model)
    if not params:
        return 30.0  # fallback
    _d, k1, k2, k3 = params
    if k1 <= 0 or k2 <= 0 or k3 <= 0:
        return 30.0  # fallback for degenerate parameters
    return nb_half_lives * math.log(2) * (1.0 / k1 + 1.0 / k2 + 1.0 / k3)


def e2_curve_3c(
    t: float, dose: float, d: float, k1: float, k2: float, k3: float
) -> float:
    """Three-compartment PK model for a single injection dose.

    Returns estimated estradiol level (pg/mL) at time t (days) after
    administering dose (mg). Parameters d, k1, k2, k3 are model-specific.
    """
    if t < 0:
        return 0.0
    if dose <= 0 or d <= 0:
        return 0.0

    try:
        if k1 == k2 and k2 == k3:
            return dose * d * k1 * k1 * t * t * math.exp(-k1 * t) / 2.0
        if k1 == k2 and k2 != k3:
            return (
                dose * d * k1 * k1
                * (math.exp(-k3 * t) - math.exp(-k1 * t) * (1 + (k1 - k3) * t))
                / (k1 - k3) / (k1 - k3)
            )
        if k1 != k2 and k1 == k3:
            return (
                dose * d * k1 * k2
                * (math.exp(-k2 * t) - math.exp(-k1 * t) * (1 + (k1 - k2) * t))
                / (k1 - k2) / (k1 - k2)
            )
        if k1 != k2 and k2 == k3:
            return (
                dose * d * k1 * k2
                * (math.exp(-k1 * t) - math.exp(-k2 * t) * (1 - (k1 - k2) * t))
                / (k1 - k2) / (k1 - k2)
            )
        # General case: all rates distinct
        return dose * d * k1 * k2 * (
            math.exp(-k1 * t) / (k1 - k2) / (k1 - k3)
            - math.exp(-k2 * t) / (k1 - k2) / (k2 - k3)
            + math.exp(-k3 * t) / (k1 - k3) / (k2 - k3)
        )
    except (OverflowError, ZeroDivisionError):
        return 0.0


def _es_single_dose_3c(
    t: float, dose: float, d: float, k1: float, k2: float
) -> float:
    """Secondary compartment level for patch removal calculation."""
    if t < 0:
        return 0.0
    if dose <= 0 or d <= 0:
        return 0.0
    if k1 == k2:
        return dose * d * k1 * t * math.exp(-k1 * t)
    return dose * d * k1 / (k1 - k2) * (math.exp(-k2 * t) - math.exp(-k1 * t))


def e2_patch_3c(
    t: float, dose: float, d: float, k1: float, k2: float, k3: float, w: float
) -> float:
    """Three-compartment PK model for a transdermal patch.

    w = wear duration in days (3.5 for twice-weekly, 7.0 for once-weekly).
    """
    if t < 0:
        return 0.0
    if t <= w:
        return e2_curve_3c(t, dose, d, k1, k2, k3)
    # After patch removal: use residual compartment levels as initial conditions
    es_w = _es_single_dose_3c(w, dose, d, k1, k2)
    e2_w = e2_curve_3c(w, dose, d, k1, k2, k3)
    t_after = t - w
    # Decay from secondary compartment
    ret = 0.0
    if es_w > 0:
        if k2 == k3:
            ret += es_w * k2 * t_after * math.exp(-k2 * t_after)
        else:
            ret += es_w * k2 / (k2 - k3) * (
                math.exp(-k3 * t_after) - math.exp(-k2 * t_after)
            )
    # Decay from tertiary compartment
    if e2_w > 0:
        ret += e2_w * math.exp(-k3 * t_after)
    return ret


def compute_e2_at_time(
    t_now: float,
    doses: list[dict],
    scaling_factor: float = 1.0,
) -> float:
    """Compute estimated E2 level at time t_now from all dose contributions.

    t_now: Unix timestamp (seconds).
    doses: list of dicts with 'timestamp', 'model', 'dose_mg' keys.
    Returns E2 in pg/mL.
    """
    total = 0.0
    for dose_rec in doses:
        model = dose_rec.get("model", "")
        params = PK_PARAMETERS.get(model)
        if not params:
            continue
        d, k1, k2, k3 = params
        dose_mg = dose_rec.get("dose_mg", 0.0)
        # Patch PK parameters are calibrated for mcg/day input;
        # stored dose_mg is in mg/day, so convert (×1000)
        if model in PATCH_WEAR_DAYS:
            dose_mg *= 1000.0
        t_days = (t_now - dose_rec["timestamp"]) / 86400.0
        if model in PATCH_WEAR_DAYS:
            w = PATCH_WEAR_DAYS[model]
            total += e2_patch_3c(t_days, dose_mg, d, k1, k2, k3, w)
        else:
            total += e2_curve_3c(t_days, dose_mg, d, k1, k2, k3)
    return total * scaling_factor


def compute_steady_state_e2_at_time(
    t_target: float,
    all_configs: list[dict],
    n_virtual_intervals: int = 20,
) -> float:
    """Compute predicted E2 at t_target assuming steady-state dosing.

    Generates virtual doses from each config's schedule around t_target
    and returns the summed PK prediction. Useful for blood tests that
    predate recorded dose history.
    """
    virtual_doses: list[dict] = []
    for cfg in all_configs:
        ester = cfg.get("ester", "")
        method = cfg.get("method", "")
        interval_days = cfg.get("interval_days", 7.0)
        dose_mg = cfg.get("dose_mg", 0.0)
        dose_time_str = cfg.get("dose_time", "00:00")
        model_key = resolve_model_key(ester, method, interval_days)
        if not model_key or model_key not in PK_PARAMETERS:
            continue
        if dose_mg <= 0 or interval_days <= 0:
            continue

        interval_s = interval_days * 86400.0

        # Parse dose_time to seconds-from-midnight
        try:
            h, m = map(int, dose_time_str.split(":"))
        except (ValueError, AttributeError):
            h, m = 0, 0
        dose_offset = h * 3600 + m * 60

        # Find the nearest aligned dose time on or before t_target:
        # Start from midnight of t_target's day + dose_offset, then step
        # by interval until we pass t_target, then back up one step.
        import datetime as _dt
        try:
            from homeassistant.util import dt as dt_util
            local_tz = dt_util.DEFAULT_TIME_ZONE
        except ImportError:
            local_tz = _dt.timezone.utc

        dt_target = _dt.datetime.fromtimestamp(t_target, tz=local_tz)
        dose_at_target_day = dt_target.replace(
            hour=h, minute=m, second=0, microsecond=0
        )
        anchor = dose_at_target_day.timestamp()
        if anchor > t_target:
            anchor -= 86400  # use previous day's dose time

        # Align: find the dose time closest to (but <= t_target) in the cycle
        # Walk forward from a far-past anchor to avoid modular arithmetic issues
        far_past = anchor - n_virtual_intervals * interval_s
        t = far_past
        last_before = far_past
        while t <= t_target:
            last_before = t
            t += interval_s
        anchor = last_before

        # Generate n_virtual_intervals doses ending at anchor
        for i in range(n_virtual_intervals):
            dose_ts = anchor - i * interval_s
            virtual_doses.append({
                "timestamp": dose_ts,
                "model": model_key,
                "dose_mg": dose_mg,
            })

    if not virtual_doses:
        return 0.0
    return compute_e2_at_time(t_target, virtual_doses, scaling_factor=1.0)


# ── Cycle-fitting algorithm (menstrual range auto-regimen) ──────────────────


def _ss_unit_3c(
    t_mod: float, T: float, d: float, k1: float, k2: float, k3: float
) -> float:
    """Steady-state E2 from 1 mg injection repeated every T days.

    Uses the geometric series of the 3-compartment model (general case,
    all rate constants distinct).  Returns E2 (pg/mL) at time *t_mod*
    within the dosing interval [0, T).
    """
    if T <= 0 or d <= 0:
        return 0.0
    try:

        def _geom(k: float, t: float) -> float:
            return math.exp(-k * t) / (1.0 - math.exp(-k * T))

        val = d * k1 * k2 * (
            _geom(k1, t_mod) / (k1 - k2) / (k1 - k3)
            - _geom(k2, t_mod) / (k1 - k2) / (k2 - k3)
            + _geom(k3, t_mod) / (k1 - k3) / (k2 - k3)
        )
        return max(0.0, val)
    except (OverflowError, ZeroDivisionError, ValueError):
        return 0.0


def _compute_basis_vector(
    interval: float,
    phase: float,
    d: float,
    k1: float,
    k2: float,
    k3: float,
    n_days: int = 28,
) -> list[float]:
    """Steady-state E2 per cycle day from a 1 mg schedule.

    *interval*: dosing interval (days).
    *phase*: cycle day when a dose is administered (0-indexed).
    Returns an *n_days*-element list.
    """
    return [
        _ss_unit_3c((day - phase) % interval, interval, d, k1, k2, k3)
        for day in range(n_days)
    ]


def _gauss_solve(
    A: list[list[float]], b: list[float]
) -> list[float] | None:
    """Solve Ax = b via Gaussian elimination with partial pivoting."""
    n = len(b)
    if n == 0:
        return []
    M = [row[:] + [bi] for row, bi in zip(A, b)]

    for col in range(n):
        max_val = abs(M[col][col])
        max_row = col
        for row in range(col + 1, n):
            if abs(M[row][col]) > max_val:
                max_val = abs(M[row][col])
                max_row = row
        if max_val < 1e-14:
            return None
        if max_row != col:
            M[col], M[max_row] = M[max_row], M[col]
        for row in range(col + 1, n):
            factor = M[row][col] / M[col][col]
            for j in range(col, n + 1):
                M[row][j] -= factor * M[col][j]

    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        if abs(M[i][i]) < 1e-14:
            return None
        x[i] = M[i][n]
        for j in range(i + 1, n):
            x[i] -= M[i][j] * x[j]
        x[i] /= M[i][i]
    return x


def _nnls(
    columns: list[list[float]], b: list[float]
) -> list[float]:
    """Non-negative least squares (Lawson-Hanson active set).

    *columns*: list of column vectors (each len *n*).
    *b*: target vector (len *n*).
    Returns x (len k, all >= 0) minimising ||Ax - b||².
    """
    n = len(b)
    k = len(columns)
    if k == 0:
        return []

    x = [0.0] * k
    free = [False] * k

    for _outer in range(3 * k + 1):
        # Residual r = b - Ax
        r = list(b)
        for j in range(k):
            if x[j] != 0.0:
                for i in range(n):
                    r[i] -= columns[j][i] * x[j]

        # Gradient w = Aᵀ r
        w = [sum(columns[j][i] * r[i] for i in range(n)) for j in range(k)]

        best_j, best_w = -1, 1e-10
        for j in range(k):
            if not free[j] and w[j] > best_w:
                best_w = w[j]
                best_j = j
        if best_j < 0:
            break
        free[best_j] = True

        # Inner loop: solve LS on free set, enforce non-negativity
        for _inner in range(3 * k + 1):
            free_idx = [j for j in range(k) if free[j]]
            nf = len(free_idx)

            AtA = [[0.0] * nf for _ in range(nf)]
            Atb_vec = [0.0] * nf
            for ii in range(nf):
                ci = free_idx[ii]
                for jj in range(nf):
                    cj = free_idx[jj]
                    AtA[ii][jj] = sum(
                        columns[ci][i] * columns[cj][i] for i in range(n)
                    )
                Atb_vec[ii] = sum(columns[ci][i] * b[i] for i in range(n))

            s_free = _gauss_solve(AtA, Atb_vec)
            if s_free is None:
                break

            if all(v >= 0 for v in s_free):
                for ii, j in enumerate(free_idx):
                    x[j] = s_free[ii]
                break

            alpha = 1.0
            for ii, j in enumerate(free_idx):
                if s_free[ii] <= 0 and x[j] > 0:
                    alpha = min(alpha, x[j] / (x[j] - s_free[ii]))

            for ii, j in enumerate(free_idx):
                x[j] += alpha * (s_free[ii] - x[j])
                if x[j] <= 1e-12:
                    free[j] = False
                    x[j] = 0.0

    return x


def compute_cycle_fit_regimen(
    ester: str, method: str, max_schedules: int = 4
) -> dict | None:
    """Compute a multi-schedule regimen approximating the menstrual cycle.

    Uses greedy forward selection with NNLS to find up to *max_schedules*
    dose schedules (same ester/method, varying dose/interval/phase) that
    minimise the MSE between predicted steady-state E2 and the reference
    menstrual-cycle E2 curve.

    Returns ``{"schedules": [...], "residual_rms": float,
    "cycle_fit_curve": [float, ...]}`` or *None*.
    """
    model_key = ESTER_METHOD_TO_MODEL.get((ester, method))
    if model_key is None:
        return None
    if model_key == "patch":
        model_key = "patch tw"

    params = PK_PARAMETERS.get(model_key)
    if not params:
        return None

    d, k1, k2, k3 = params
    n_days = 28
    target = MENSTRUAL_CYCLE_DATA["E2"][:n_days]

    # ── Build candidate (interval, phase) pool ──
    interval_set: set[float] = set()
    for intv in SUGGESTED_INTERVALS.get(model_key, [7.0]):
        interval_set.add(intv)
    for intv in (3.5, 4.0, 5.0, 7.0, 9.0, 10.0, 14.0, 28.0):
        interval_set.add(intv)

    candidates: list[tuple[float, float, list[float]]] = []
    for intv in sorted(interval_set):
        if intv < 2.0 or intv > 28.0:
            continue
        n_phases = max(1, int(math.ceil(intv)))
        for phase in range(n_phases):
            bv = _compute_basis_vector(intv, float(phase), d, k1, k2, k3, n_days)
            candidates.append((intv, float(phase), bv))

    # ── Greedy forward selection ──
    selected: list[int] = []
    baseline_mse = sum(v**2 for v in target) / n_days
    prev_mse = baseline_mse

    for step in range(max_schedules):
        best_ci = -1
        best_mse = prev_mse
        for ci, (_intv, _phase, bv) in enumerate(candidates):
            if ci in selected:
                continue
            A_cols = [candidates[si][2] for si in selected] + [bv]
            x = _nnls(A_cols, target)
            fitted = [0.0] * n_days
            for j, xj in enumerate(x):
                for i in range(n_days):
                    fitted[i] += xj * A_cols[j][i]
            mse = (
                sum((target[i] - fitted[i]) ** 2 for i in range(n_days)) / n_days
            )
            if mse < best_mse:
                best_mse = mse
                best_ci = ci

        if best_ci < 0:
            break
        if step > 0 and prev_mse > 0 and (prev_mse - best_mse) / prev_mse < 0.01:
            break
        selected.append(best_ci)
        prev_mse = best_mse

    if not selected:
        return None

    # ── Final NNLS with all selected columns ──
    A_cols = [candidates[si][2] for si in selected]
    final_x = _nnls(A_cols, target)

    # ── Build schedules, round doses ──
    schedules = []
    for si, dose_raw in zip(selected, final_x):
        if dose_raw < 0.25:
            continue
        intv, phase, _ = candidates[si]
        if model_key in PATCH_WEAR_DAYS:
            # dose_raw in mcg/day (PK units); convert to mg/day
            dose_mg = dose_raw / 1000.0
            dose_mg = round(dose_mg / 0.025) * 0.025
            dose_mg = max(0.025, min(0.4, dose_mg))
        else:
            dose_mg = round(dose_raw * 2.0) / 2.0
            dose_mg = max(0.5, min(20.0, dose_mg))
        schedules.append(
            {
                "dose_mg": dose_mg,
                "interval_days": intv,
                "phase_days": phase,
                "model_key": model_key,
            }
        )

    if not schedules:
        return None

    # ── Fitted curve with rounded doses ──
    curve = [0.0] * n_days
    for sch in schedules:
        bv = _compute_basis_vector(
            sch["interval_days"], sch["phase_days"], d, k1, k2, k3, n_days
        )
        for i in range(n_days):
            curve[i] += sch["dose_mg"] * bv[i]

    rms = math.sqrt(
        sum((target[i] - curve[i]) ** 2 for i in range(n_days)) / n_days
    )

    return {
        "schedules": schedules,
        "residual_rms": round(rms, 2),
        "cycle_fit_curve": [round(v, 1) for v in curve],
    }
