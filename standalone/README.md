# Estrannaise standalone

A self-hosted web app that runs the same estradiol pharmacokinetic model as the Home Assistant integration, without Home Assistant.

## Why this exists

The integration needs Home Assistant to provide config entries, a coordinator, and Lovelace.
This package supplies those three things itself so the model can run in a plain container.

It is not a copy.
`const.py`, `database.py` and `schedule.py` are imported directly from `custom_components/estrannaise/`, so the pharmacokinetic parameters, the scaling-factor calibration and the dose scheduling have exactly one implementation.
Changing a PK parameter changes both entrypoints at once.

`standalone/core.py` performs that import.
It loads the three modules into a synthetic package rather than importing `custom_components.estrannaise`, whose `__init__.py` pulls in Home Assistant.

## What is reimplemented

Only the parts that are genuinely Home Assistant shaped.

| Home Assistant | Standalone |
|---|---|
| Config entries | `config.py`, a JSON file |
| `DataUpdateCoordinator._async_update_data` | `state.py` |
| Lovelace cards | `static/index.html` and `embed.py` |

`schedule.py` was extracted from `coordinator.py` during this work.
The coordinator now delegates to it, so both entrypoints generate doses from one function.
The only Home Assistant coupling in that logic was `dt_util.DEFAULT_TIME_ZONE`, which is now an explicit `local_tz` argument.

## Running it

Build from the repository root, not from this directory.
The image needs `custom_components/` in the build context.

```bash
docker build -f standalone/Dockerfile -t estrannaise .
docker run -d --name estrannaise -p 8099:8099 -v estrannaise-data:/data \
  -e TZ=America/Vancouver estrannaise
```

Open `http://localhost:8099`, set a regimen, and log a dose.

### Environment

| Variable | Default | Purpose |
|---|---|---|
| `TZ` | `UTC` | Anchors dose time-of-day. Wrong value shifts every scheduled dose. |
| `ESTRANNAISE_DATA` | `/data` | SQLite database and `config.json`. |
| `ESTRANNAISE_CORE` | bundled | Directory holding `const.py`. Set by the image. |
| `ESTRANNAISE_FRAME_ANCESTORS` | empty | Origins allowed to iframe `/embed/*`. Space-separated. |
| `ESTRANNAISE_TOKEN` | empty | Shared secret gating the API and embeds. Empty disables auth. |

## Security posture

Set `ESTRANNAISE_TOKEN` unless the app has no LAN presence at all.
Leaving it empty is only reasonable when the network already isolates the service, for instance inside a Tailscale namespace.
On an ordinary LAN, every device on the network can otherwise read and delete your history.

The token is accepted as an `X-Estrannaise-Token` header, a `?token=` query parameter, or a cookie, and is compared with `secrets.compare_digest`.
`/healthz` and `/static` stay open so the Docker healthcheck works and so pages can load Plotly.

A shared token rather than Basic auth or a session cookie, because this has to work inside a cross-origin dashboard iframe.
Chrome blocks Basic auth prompts in cross-origin iframes outright, and a `SameSite=None` cookie requires HTTPS that a LAN deployment does not have.
Served pages receive the token inline, so their own fetches authenticate without depending on cookies that a third-party context would withhold.

The trade-off is that an embed URL carries the token in the query string, where it lands in the dashboard's saved config and in browser history.

Three further choices.

There is no CORS middleware.
The frontend is same-origin, so cross-origin access is never needed, and permitting it would let any page you visit read your dose and lab history.

`DELETE /api/data` requires `?confirm=DELETE`.
It is irreversible.

The container runs as UID 1000, not root.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | Full computed state, grouped per user |
| GET | `/api/curve` | Sampled curve for charting |
| GET, POST | `/api/config` | Regimens and units |
| POST, DELETE | `/api/doses`, `/api/doses/{id}` | Dose log |
| POST, DELETE | `/api/blood-tests`, `/api/blood-tests/{id}` | Lab results |
| DELETE | `/api/data?confirm=DELETE` | Erase everything |
| GET | `/healthz` | Liveness |

## Dashboard embeds

Three pages are built for iframe widgets in dashboards such as Homarr.

| Path | Shows |
|---|---|
| `/embed/level` | Current level as one large figure |
| `/embed/plot` | Curve over the recent past and near future |
| `/embed/buttons` | Log a dose, log a blood test |

All accept `?theme=light`.
All render transparent so they sit flush in a tile.

Set `ESTRANNAISE_FRAME_ANCESTORS` to the origin you load the dashboard from, including scheme and port.
Without it the browser refuses to render the tile.

When `ESTRANNAISE_TOKEN` is set, append `?token=<token>` to each embed URL.
The page then carries the token to its own API calls, so the tile works without a cookie.

Note that an iframe loads in your browser, not on the dashboard server.
Your browser must be able to reach this app directly, so use an address every viewing device can resolve.

## Tests

```bash
uv venv && uv pip install -r standalone/requirements.txt httpx pytest
.venv/bin/python -m pytest tests/ -q
```

`tests/test_schedule.py` covers the extracted scheduling logic against a fixed clock.
`tests/test_app.py` exercises the API against a real temporary SQLite database.

## Medical caveat

This models a population average.
Individual absorption varies enormously.
Treat the projection as a prompt to get bloodwork, never as a substitute for it.
