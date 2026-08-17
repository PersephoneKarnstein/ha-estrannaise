"""Small self-contained pages for embedding in a dashboard's iFrame widget.

Homarr's own "Custom Widgets" cannot help here: their JSX templates strip
``iframe``, ``script``, ``form`` and all event handlers, so a plot or a working
button has to be an iframe pointing at pages like these.

Each page is deliberately standalone -- no build step, no framework -- and
transparent-backgrounded so it sits flush inside a dashboard tile.
"""

from __future__ import annotations

import json


def _js_string(value: str) -> str:
    """Embed a Python string as a JS literal, safely escaped."""
    return json.dumps(value)


_BASE_CSS = """
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; height: 100%; background: transparent;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: var(--fg);
  }
  body.light { --fg: #1a1b1e; --muted: #6b7280; --accent: #7048e8;
               --btn: rgba(0,0,0,.06); --btn-hover: rgba(0,0,0,.12); }
  body.dark  { --fg: #e6e6e6; --muted: #9aa0a6; --accent: #9775fa;
               --btn: rgba(255,255,255,.08); --btn-hover: rgba(255,255,255,.16); }
  .wrap { height: 100%; display: flex; flex-direction: column;
          align-items: center; justify-content: center; gap: .5rem; padding: .5rem; }
  .muted { color: var(--muted); font-size: .75rem; }
  .err { color: #ff6b6b; font-size: .75rem; text-align: center; padding: .5rem; }
"""

_BUTTON_CSS = """
  button {
    font: inherit; color: var(--fg); background: var(--btn);
    border: 1px solid transparent; border-radius: .5rem;
    padding: .55rem .8rem; cursor: pointer; width: 100%;
    transition: background .15s ease;
  }
  button:hover:not(:disabled) { background: var(--btn-hover); }
  button:disabled { opacity: .5; cursor: default; }
  .row { display: flex; gap: .4rem; width: 100%; }
  .stack { display: flex; flex-direction: column; gap: .4rem;
           width: 100%; max-width: 22rem; }
  .status { min-height: 1rem; font-size: .72rem; text-align: center; }
  .ok { color: #51cf66; }
"""


# Every embed fetches through this helper so the shared token travels as a
# header. A cookie would not work: inside a cross-origin dashboard iframe the
# browser treats these as third-party requests and withholds SameSite cookies.
_FETCH_HELPER = """
const TOKEN = window.__ESTRANNAISE_TOKEN__ || '';
async function api(path) {
  const headers = TOKEN ? {'X-Estrannaise-Token': TOKEN} : {};
  const r = await fetch(path, {cache: 'no-store', headers});
  if (r.status === 401) throw new Error('Not authorised - check the token in the tile URL');
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
async function post(path, payload) {
  const headers = {'Content-Type': 'application/json'};
  if (TOKEN) headers['X-Estrannaise-Token'] = TOKEN;
  const r = await fetch(path, {method: 'POST', headers, body: JSON.stringify(payload)});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
  return d;
}
"""


def _page(
    title: str,
    theme: str,
    css: str,
    body: str,
    script: str,
    head: str = "",
    token: str = "",
) -> str:
    safe_theme = "light" if theme == "light" else "dark"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{head}
<style>{_BASE_CSS}{css}</style>
</head>
<body class="{safe_theme}">
{body}
<script>window.__ESTRANNAISE_TOKEN__ = {_js_string(token)};</script>
<script>{_FETCH_HELPER}{script}</script>
</body>
</html>"""


def render_level(theme: str = "dark", token: str = "") -> str:
    """Current E2 level as a single large figure."""
    body = """
<div class="wrap">
  <div id="value" style="font-size:2.4rem;font-weight:600;line-height:1">--</div>
  <div id="units" class="muted"></div>
  <div id="err" class="err" hidden></div>
</div>"""
    script = """
async function refresh() {
  try {
    const s = await api('/api/state');
    document.getElementById('value').textContent = s.current_e2;
    document.getElementById('units').textContent = s.units;
    document.getElementById('err').hidden = true;
  } catch (e) {
    const el = document.getElementById('err');
    el.textContent = e.message;
    el.hidden = false;
  }
}
refresh();
setInterval(refresh, 60000);
"""
    return _page("E2 level", theme, "", body, script, token=token)


def render_plot(theme: str = "dark", token: str = "") -> str:
    """Estradiol curve over the recent past and near future."""
    head = '<script src="/static/plotly.min.js"></script>'
    body = """
<div class="wrap" style="padding:0">
  <div id="chart" style="width:100%;height:100%"></div>
  <div id="err" class="err" hidden></div>
</div>"""
    script = """
const isLight = document.body.classList.contains('light');
const fg = isLight ? '#1a1b1e' : '#e6e6e6';
const grid = isLight ? 'rgba(0,0,0,.08)' : 'rgba(255,255,255,.08)';

async function draw() {
  try {
    const d = await api('/api/curve?days_back=21&days_forward=14&points=200');

    const traces = d.series.map(s => ({
      x: s.samples.map(p => new Date(p.t * 1000)),
      y: s.samples.map(p => p.e2),
      type: 'scatter', mode: 'lines', name: s.user_id,
      line: {width: 2, shape: 'spline'},
      hovertemplate: '%{y:.0f} ' + d.units + '<extra></extra>'
    }));

    const shapes = [{
      type: 'rect', xref: 'paper', yref: 'y', x0: 0, x1: 1,
      y0: d.target_range.lower, y1: d.target_range.upper,
      fillcolor: 'rgba(151,117,250,.13)', line: {width: 0}, layer: 'below'
    }, {
      type: 'line', xref: 'x', yref: 'paper',
      x0: new Date(d.now * 1000), x1: new Date(d.now * 1000), y0: 0, y1: 1,
      line: {color: fg, width: 1, dash: 'dot'}
    }];

    Plotly.react('chart', traces, {
      margin: {l: 38, r: 8, t: 8, b: 28},
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: {color: fg, size: 10},
      xaxis: {gridcolor: grid, zeroline: false},
      yaxis: {gridcolor: grid, zeroline: false, title: {text: d.units, font: {size: 9}}},
      showlegend: d.series.length > 1,
      legend: {orientation: 'h', y: 1.12, font: {size: 9}}
    }, {displayModeBar: false, responsive: true});

    document.getElementById('err').hidden = true;
  } catch (e) {
    const el = document.getElementById('err');
    el.textContent = 'Chart unavailable: ' + e.message;
    el.hidden = false;
  }
}
draw();
setInterval(draw, 300000);
"""
    return _page("E2 curve", theme, "", body, script, head=head, token=token)


def render_buttons(theme: str = "dark", token: str = "") -> str:
    """Log-a-dose and log-a-blood-test controls."""
    body = """
<div class="wrap">
  <div class="stack">
    <select id="regimen" style="display:none"></select>
    <button id="dose">Log dose</button>
    <div class="row">
      <input id="level" type="number" min="0" step="1" placeholder="pg/mL"
             style="flex:1;min-width:0;font:inherit;color:var(--fg);
                    background:var(--btn);border:1px solid transparent;
                    border-radius:.5rem;padding:.55rem .6rem">
      <button id="test" style="flex:0 0 auto;width:auto">Log test</button>
    </div>
    <div id="status" class="status muted">&nbsp;</div>
  </div>
</div>"""
    script = """
const $ = id => document.getElementById(id);
let regimens = [];

function say(msg, ok) {
  const el = $('status');
  el.textContent = msg;
  el.className = 'status ' + (ok ? 'ok' : 'muted');
  if (ok) setTimeout(() => { el.textContent = '\\u00a0'; el.className = 'status muted'; }, 4000);
}

async function init() {
  try {
    const cfg = await api('/api/config');
    regimens = cfg.regimens || [];
    if (regimens.length > 1) {
      const sel = $('regimen');
      sel.style.display = '';
      sel.innerHTML = regimens.map(x =>
        `<option value="${x.entry_id}">${x.user_id} - ${x.ester} ${x.method} ${x.dose_mg}mg</option>`
      ).join('');
    }
    if (!regimens.length) {
      say('No regimen configured', false);
      $('dose').disabled = true; $('test').disabled = true;
    } else {
      $('dose').textContent = 'Log dose (' + regimens[0].dose_mg + ' mg)';
    }
  } catch (e) {
    say(e.message, false);
    $('dose').disabled = true; $('test').disabled = true;
  }
}

function entryId() {
  const sel = $('regimen');
  return sel.style.display === 'none' ? (regimens[0] || {}).entry_id : sel.value;
}

async function submit(url, payload, label) {
  try {
    await post(url, payload);
    say(label + ' logged', true);
  } catch (e) { say(e.message, false); }
}

$('dose').onclick = () => {
  const id = entryId();
  const reg = regimens.find(x => x.entry_id === id) || regimens[0];
  if (!reg) return;
  submit('/api/doses', {entry_id: id, dose_mg: reg.dose_mg}, 'Dose');
};

$('test').onclick = () => {
  const v = parseFloat($('level').value);
  if (!isFinite(v) || v < 0) { say('Enter a level first', false); return; }
  submit('/api/blood-tests', {entry_id: entryId(), level_pg_ml: v, on_schedule: true}, 'Test');
  $('level').value = '';
};

init();
"""
    return _page("Log", theme, _BUTTON_CSS, body, script, token=token)
