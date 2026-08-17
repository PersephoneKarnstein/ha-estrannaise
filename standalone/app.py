"""FastAPI application: the standalone counterpart to the HA integration.

Deliberately has no authentication. It is intended to run with no LAN or bridge
presence at all -- reachable only over a private network such as a Tailscale
tailnet -- so the network layer is the access control. If you publish it more
widely than that, put an authenticating proxy in front of it.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import embed
from .config import ConfigError, load_config, save_config
from .core import const, database
from .state import build_state

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("ESTRANNAISE_DATA", "/data"))
DB_PATH = DATA_DIR / "estrannaise.db"
CONFIG_PATH = DATA_DIR / "config.json"

# Origins permitted to embed this app in an iframe (Homarr, typically).
# Space-separated. Empty means same-origin only.
FRAME_ANCESTORS = os.environ.get("ESTRANNAISE_FRAME_ANCESTORS", "").strip()

# Shared secret gating everything except /healthz and /static.
#
# Empty disables auth entirely, which is only appropriate when the app has no
# LAN presence at all (e.g. bound inside a Tailscale namespace). On a normal
# LAN, leave it set: without it, every device on the network -- including IoT
# devices and anything a guest joins with -- can read and delete this history.
#
# A token rather than Basic auth or a session cookie because this has to work
# inside a cross-origin dashboard iframe. Chrome blocks Basic auth prompts in
# cross-origin iframes, and SameSite=None cookies require HTTPS.
TOKEN = os.environ.get("ESTRANNAISE_TOKEN", "").strip()
TOKEN_COOKIE = "estrannaise_token"

# Reachable without a token: the healthcheck (so Docker can probe an
# unconfigured container) and static assets (which carry no personal data).
OPEN_PATHS = ("/healthz",)
OPEN_PREFIXES = ("/static/",)


def _supplied_token(request: Request) -> str | None:
    """Token from header, query string, or cookie, in that order.

    The header is what the served pages use. The query string exists for
    dashboard iframe URLs. The cookie makes a plain bookmark work after one
    authenticated visit.
    """
    return (
        request.headers.get("x-estrannaise-token")
        or request.query_params.get("token")
        or request.cookies.get(TOKEN_COOKIE)
    )


def _authorised(request: Request) -> bool:
    if not TOKEN:
        return True
    supplied = _supplied_token(request)
    # compare_digest to avoid leaking the token through response timing.
    return bool(supplied) and secrets.compare_digest(supplied, TOKEN)


def local_timezone() -> ZoneInfo:
    name = os.environ.get("TZ", "UTC")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


TZ = local_timezone()

_db: Any = None


def get_db() -> Any:
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    return _db


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _db
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Surface a broken config at startup rather than on the first request.
    load_config(CONFIG_PATH)
    _db = database.EstrannaisDatabase(DB_PATH)
    await _db.async_setup()
    try:
        yield
    finally:
        await _db.async_close()
        _db = None


app = FastAPI(title="Estrannaise", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Authorise the request, then restrict framing to the dashboard origin.

    No CORS middleware: the frontend is served from this same origin, so
    cross-origin access is never needed and allowing it would let any page you
    visit read your medical history.
    """
    path = request.url.path
    is_open = path in OPEN_PATHS or path.startswith(OPEN_PREFIXES)

    if not is_open and not _authorised(request):
        response = JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid token"},
        )
    else:
        response = await call_next(request)
        # Remember a token supplied by query string so a later bare visit works.
        # Lax, so it rides top-level navigation but not third-party subresources
        # -- the embeds carry the token in-page instead of relying on this.
        if TOKEN and request.query_params.get("token") and response.status_code < 400:
            response.set_cookie(
                TOKEN_COOKIE,
                TOKEN,
                httponly=True,
                samesite="lax",
                max_age=60 * 60 * 24 * 365,
            )

    ancestors = f"'self' {FRAME_ANCESTORS}".strip() if FRAME_ANCESTORS else "'self'"
    response.headers["Content-Security-Policy"] = f"frame-ancestors {ancestors}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# ── Request models ────────────────────────────────────────────────────────────


class DoseIn(BaseModel):
    entry_id: str | None = None
    model: str | None = None
    dose_mg: float = Field(gt=0)
    timestamp: float | None = None


class BloodTestIn(BaseModel):
    entry_id: str | None = None
    level_pg_ml: float = Field(ge=0)
    timestamp: float | None = None
    notes: str | None = None
    on_schedule: bool | None = None


class ConfigIn(BaseModel):
    units: str = const.DEFAULT_UNITS
    regimens: list[dict[str, Any]] = Field(default_factory=list)


def _current_config() -> dict[str, Any]:
    try:
        return load_config(CONFIG_PATH)
    except ConfigError as err:
        raise HTTPException(status_code=500, detail=str(err)) from err


def _resolve_entry(config: dict[str, Any], entry_id: str | None) -> dict[str, Any]:
    """Pick the regimen a dose or test belongs to."""
    regimens = config["regimens"]
    if not regimens:
        raise HTTPException(
            status_code=400,
            detail="No regimen configured yet. Add one before logging.",
        )
    if entry_id is None:
        return regimens[0]
    for regimen in regimens:
        if regimen["entry_id"] == entry_id:
            return regimen
    raise HTTPException(status_code=404, detail=f"Unknown entry_id: {entry_id}")


# ── API ───────────────────────────────────────────────────────────────────────


@app.get("/healthz")
async def healthz():
    return {"ok": _db is not None}


@app.get("/api/state")
async def api_state(db=Depends(get_db)):
    return await build_state(db, _current_config(), time.time(), TZ)


@app.get("/api/curve")
async def api_curve(
    days_back: float = 30.0,
    days_forward: float = 30.0,
    points: int = 240,
    db=Depends(get_db),
):
    """Sampled E2 curve for charting, in the configured units."""
    points = max(2, min(2000, points))
    now = time.time()
    state = await build_state(db, _current_config(), now, TZ)
    conversion = const.AVAILABLE_UNITS.get(state["units"], {}).get(
        "conversion_factor", 1.0
    )

    series = []
    for user_id, user in state["users"].items():
        doses = user["doses"] + user["auto_doses"]
        scaling = user["scaling_factor"]
        start = now - days_back * 86400.0
        step = (days_back + days_forward) * 86400.0 / (points - 1)
        samples = [
            {
                "t": start + i * step,
                "e2": round(
                    const.compute_e2_at_time(start + i * step, doses, scaling)
                    * conversion,
                    2,
                ),
            }
            for i in range(points)
        ]
        series.append({"user_id": user_id, "samples": samples})

    return {
        "now": now,
        "units": state["units"],
        "target_range": state["target_range"],
        "series": series,
    }


@app.get("/api/config")
async def api_get_config():
    return _current_config()


@app.post("/api/config")
async def api_set_config(body: ConfigIn, db=Depends(get_db)):
    # Reject unresolvable regimens here rather than letting them save and fail
    # later at dose-logging time with "Unknown model: None".
    for regimen in body.regimens:
        ester = regimen.get("ester")
        method = regimen.get("method")
        if not const.is_combination_supported(ester, method):
            allowed = [
                m for m in const.METHODS if const.is_combination_supported(ester, m)
            ]
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{const.ESTERS.get(ester, ester)} cannot be given by "
                    f"{const.METHODS.get(method, method)}. "
                    f"Valid methods: {', '.join(const.METHODS[m] for m in allowed) or 'none'}"
                ),
            )
    save_config(CONFIG_PATH, body.model_dump())
    # Apply backfill immediately so the chart reflects the change at once.
    config = _current_config()
    from .state import persist_pending_doses

    await persist_pending_doses(db, config["regimens"], time.time(), TZ)
    return config


@app.post("/api/doses")
async def api_log_dose(body: DoseIn, db=Depends(get_db)):
    config = _current_config()
    regimen = _resolve_entry(config, body.entry_id)

    model_key = body.model or const.resolve_model_key(
        regimen["ester"], regimen["method"], regimen["interval_days"]
    )
    if not model_key or model_key not in const.PK_PARAMETERS:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model_key!r}")

    dose_id = await db.add_dose(
        config_entry_id=regimen["entry_id"],
        model=model_key,
        dose_mg=body.dose_mg,
        timestamp=body.timestamp or time.time(),
        source="manual",
    )
    return {"ok": True, "id": dose_id, "model": model_key}


@app.delete("/api/doses/{dose_id}")
async def api_delete_dose(dose_id: int, entry_id: str | None = None, db=Depends(get_db)):
    regimen = _resolve_entry(_current_config(), entry_id)
    if not await db.delete_dose(regimen["entry_id"], dose_id):
        raise HTTPException(status_code=404, detail="Dose not found")
    return {"ok": True}


@app.post("/api/blood-tests")
async def api_log_blood_test(body: BloodTestIn, db=Depends(get_db)):
    regimen = _resolve_entry(_current_config(), body.entry_id)
    test_id = await db.add_blood_test(
        config_entry_id=regimen["entry_id"],
        level_pg_ml=body.level_pg_ml,
        timestamp=body.timestamp or time.time(),
        notes=body.notes,
        on_schedule=body.on_schedule,
    )
    return {"ok": True, "id": test_id}


@app.delete("/api/blood-tests/{test_id}")
async def api_delete_blood_test(
    test_id: int, entry_id: str | None = None, db=Depends(get_db)
):
    regimen = _resolve_entry(_current_config(), entry_id)
    if not await db.delete_blood_test(regimen["entry_id"], test_id):
        raise HTTPException(status_code=404, detail="Blood test not found")
    return {"ok": True}


@app.delete("/api/data")
async def api_clear_all(confirm: str = "", db=Depends(get_db)):
    """Irreversibly delete all doses and blood tests.

    Requires ``?confirm=DELETE`` so a stray request cannot wipe the history.
    """
    if confirm != "DELETE":
        raise HTTPException(
            status_code=400, detail="Refusing to clear data without ?confirm=DELETE"
        )
    await db.clear_all_data()
    return {"ok": True}


# ── Homarr embeds ─────────────────────────────────────────────────────────────


# Each embed is served only to an authorised request, so handing the page its
# own token is safe -- and it is the only mechanism that survives a
# cross-origin iframe, where cookies are not sent.
@app.get("/embed/plot", response_class=HTMLResponse)
async def embed_plot(theme: str = "dark"):
    return HTMLResponse(embed.render_plot(theme=theme, token=TOKEN))


@app.get("/embed/buttons", response_class=HTMLResponse)
async def embed_buttons(theme: str = "dark"):
    return HTMLResponse(embed.render_buttons(theme=theme, token=TOKEN))


@app.get("/embed/level", response_class=HTMLResponse)
async def embed_level(theme: str = "dark"):
    return HTMLResponse(embed.render_level(theme=theme, token=TOKEN))


# ── Frontend ──────────────────────────────────────────────────────────────────

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _with_token(html: str) -> str:
    """Hand the page its token so its fetches can authenticate."""
    snippet = f"<script>window.ESTRANNAISE_TOKEN={json.dumps(TOKEN)};</script>"
    return html.replace("</head>", f"{snippet}\n</head>", 1)


@app.get("/", response_class=HTMLResponse)
async def index():
    page = STATIC_DIR / "index.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Frontend not built")
    return HTMLResponse(_with_token(page.read_text(encoding="utf-8")))
