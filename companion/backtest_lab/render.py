"""Render the strategy-comparison report as one self-contained HTML file.

Design follows the dataviz method: categorical palette in fixed slot order
(validated for color-vision deficiency in both light and dark modes), one axis
per chart, thin marks, unified hover tooltips, legend + direct labels for
series identity, recessive grid, theme-aware (prefers-color-scheme + manual
toggle). Plotly JS is inlined so the file works offline on the VPS.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Categorical slots (fixed order — never cycled). Light/dark are the same hues
# stepped for each surface. First four slots validate for all-pairs charts.
SERIES_LIGHT = ["#2a78d6", "#008300", "#e87ba4", "#eda100",
                "#1baf7a", "#eb6834", "#4a3aa7", "#e34948"]
SERIES_DARK = ["#3987e5", "#008300", "#d55181", "#c98500",
               "#199e70", "#d95926", "#9085e9", "#e66767"]

THEME = {
    "light": {
        "surface": "#fcfcfb", "page": "#f9f9f7", "ink": "#0b0b0b",
        "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
        "axis": "#c3c2b7", "series": SERIES_LIGHT,
    },
    "dark": {
        "surface": "#1a1a19", "page": "#0d0d0d", "ink": "#ffffff",
        "ink2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
        "axis": "#383835", "series": SERIES_DARK,
    },
}


def get_plotly_js() -> str | None:
    try:
        from plotly.offline import get_plotlyjs
        return get_plotlyjs()
    except ImportError:
        return None


def _metrics_table(analyses: list[dict], winners: dict[str, str]) -> str:
    names = [a["name"] for a in analyses]
    head = "".join(f"<th>{n}</th>" for n in names)
    rows = []
    for metric in analyses[0]["metrics"].keys():
        cells = []
        for a in analyses:
            value = a["metrics"].get(metric)
            shown = "–" if value is None else value
            if winners.get(metric) == a["name"]:
                cells.append(f'<td class="win">{shown} ✓</td>')
            else:
                cells.append(f"<td>{shown}</td>")
        rows.append(f'<tr><th scope="row">{metric}</th>{"".join(cells)}</tr>')
    return (f'<table class="metrics"><thead><tr><th>Metric</th>{head}</tr>'
            f'</thead><tbody>{"".join(rows)}</tbody></table>')


def render_html(analyses: list[dict], winners: dict[str, str],
                run_label: str = "", include_plotly: bool = True) -> str:
    payload = {
        "strategies": analyses,
        "winners": winners,
        "run_label": run_label,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "theme": THEME,
    }
    payload_js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    plotly_js = ""
    if include_plotly:
        bundle = get_plotly_js()
        plotly_js = (f"<script>{bundle}</script>" if bundle else
                     "<!-- plotly not installed: charts disabled -->")

    meta_bits = [a["meta"]["timerange"] for a in analyses[:1]]
    subtitle = f"{run_label + ' · ' if run_label else ''}{meta_bits[0] if meta_bits else ''}"

    table_html = _metrics_table(analyses, winners)

    return HTML_TEMPLATE \
        .replace("__PLOTLY__", plotly_js) \
        .replace("__PAYLOAD__", payload_js) \
        .replace("__SUBTITLE__", subtitle) \
        .replace("__TABLE__", table_html)


def write_report(analyses: list[dict], winners: dict[str, str],
                 out_dir: Path, run_label: str = "",
                 include_plotly: bool = True) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_html(analyses, winners, run_label, include_plotly)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"compare_{stamp}.html"
    path.write_text(html, encoding="utf-8")
    (out_dir / "latest.html").write_text(html, encoding="utf-8")
    return path


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy comparison — backtest lab</title>
__PLOTLY__
<style>
  :root { color-scheme: light dark; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0; padding: 24px;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page); color: var(--ink);
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
    --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7; --win:#006300;
    --ring:rgba(11,11,11,0.10);
  }
  body.dark {
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --axis:#383835; --win:#0ca30c;
    --ring:rgba(255,255,255,0.10);
  }
  header { display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
           margin-bottom: 4px; }
  h1 { font-size: 20px; margin: 0; }
  .sub { color: var(--ink2); font-size: 13px; }
  #themeToggle {
    margin-left:auto; border:1px solid var(--ring); background:var(--surface);
    color:var(--ink2); border-radius:8px; padding:6px 12px; cursor:pointer;
    font: inherit; font-size: 13px;
  }
  .card {
    background: var(--surface); border: 1px solid var(--ring);
    border-radius: 12px; padding: 16px; margin-top: 16px;
    overflow-x: auto;
  }
  .card h2 { font-size: 14px; margin: 0 0 4px; }
  .card .hint { color: var(--muted); font-size: 12px; margin: 0 0 8px; }
  .chart { width: 100%; min-height: 340px; }
  table.metrics { border-collapse: collapse; width: 100%; font-size: 13px; }
  table.metrics th, table.metrics td {
    text-align: right; padding: 7px 12px;
    border-bottom: 1px solid var(--grid);
    font-variant-numeric: tabular-nums;
  }
  table.metrics thead th { color: var(--ink2); font-weight: 600; }
  table.metrics tbody th { text-align: left; color: var(--ink2);
                           font-weight: 500; }
  table.metrics td.win { font-weight: 700; color: var(--win); }
  footer { color: var(--muted); font-size: 12px; margin-top: 16px; }
</style>
</head>
<body>
<header>
  <h1>Strategy comparison</h1>
  <span class="sub">__SUBTITLE__</span>
  <button id="themeToggle" type="button">◐ Theme</button>
</header>

<div class="card">
  <h2>Cumulative profit</h2>
  <p class="hint">% of starting balance, after fees — higher is better</p>
  <div id="equity" class="chart"></div>
</div>

<div class="card">
  <h2>Drawdown</h2>
  <p class="hint">% below the account's running peak — shallower is better</p>
  <div id="drawdown" class="chart"></div>
</div>

<div class="card">
  <h2>Monthly returns</h2>
  <p class="hint">% of starting balance per calendar month</p>
  <div id="monthly" class="chart"></div>
</div>

<div class="card">
  <h2>Individual trades</h2>
  <p class="hint">each dot is one closed trade — hold time vs. profit</p>
  <div id="trades" class="chart"></div>
</div>

<div class="card">
  <h2>Metrics</h2>
  <p class="hint">✓ marks the better value per row</p>
  __TABLE__
</div>

<footer id="footer"></footer>

<script>
const DATA = __PAYLOAD__;

function mode() {
  if (document.body.classList.contains('dark')) return 'dark';
  if (document.body.classList.contains('light')) return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark' : 'light';
}

function baseLayout(t) {
  return {
    paper_bgcolor: t.surface, plot_bgcolor: t.surface,
    font: {family: 'system-ui, -apple-system, "Segoe UI", sans-serif',
           size: 12, color: t.ink2},
    margin: {l: 56, r: 110, t: 8, b: 44},
    xaxis: {gridcolor: t.grid, linecolor: t.axis, zerolinecolor: t.axis,
            tickcolor: t.axis},
    yaxis: {gridcolor: t.grid, linecolor: t.axis, zerolinecolor: t.axis,
            tickcolor: t.axis},
    legend: {orientation: 'h', y: 1.12, font: {color: t.ink2}},
    hoverlabel: {bgcolor: t.surface, bordercolor: t.grid,
                 font: {color: t.ink}},
  };
}

function draw() {
  if (typeof Plotly === 'undefined') return;
  const m = mode();
  const t = DATA.theme[m];
  document.body.classList.toggle('dark', m === 'dark');
  const S = DATA.strategies;
  const color = i => t.series[i % t.series.length];
  const config = {responsive: true, displaylogo: false,
                  modeBarButtonsToRemove: ['lasso2d', 'select2d']};

  // Cumulative profit — 2px lines, unified hover, direct label at line end.
  const eqTraces = S.map((s, i) => ({
    type: 'scatter', mode: 'lines', name: s.name,
    x: s.equity.x, y: s.equity.y,
    line: {color: color(i), width: 2},
    hovertemplate: '%{y:.2f}%<extra>' + s.name + '</extra>',
  }));
  const eqNotes = S.map((s, i) => ({
    x: s.equity.x[s.equity.x.length - 1], y: s.equity.y[s.equity.y.length - 1],
    text: s.name, showarrow: false, xanchor: 'left', xshift: 6,
    font: {color: color(i), size: 12},
  })).filter(a => a.x !== undefined);
  Plotly.react('equity', eqTraces, Object.assign(baseLayout(t), {
    hovermode: 'x unified',
    yaxis: Object.assign(baseLayout(t).yaxis, {ticksuffix: '%'}),
    annotations: eqNotes,
  }), config);

  // Drawdown — same identity colors, zero baseline emphasised.
  const ddTraces = S.map((s, i) => ({
    type: 'scatter', mode: 'lines', name: s.name,
    x: s.drawdown.x, y: s.drawdown.y,
    line: {color: color(i), width: 2},
    hovertemplate: '%{y:.2f}%<extra>' + s.name + '</extra>',
  }));
  Plotly.react('drawdown', ddTraces, Object.assign(baseLayout(t), {
    hovermode: 'x unified',
    yaxis: Object.assign(baseLayout(t).yaxis,
                         {ticksuffix: '%', rangemode: 'tozero'}),
  }), config);

  // Monthly returns — grouped bars, rounded data-ends, 2px gap via bargap.
  const months = [...new Set(S.flatMap(s => Object.keys(s.monthly)))].sort();
  const moTraces = S.map((s, i) => ({
    type: 'bar', name: s.name,
    x: months, y: months.map(mo => s.monthly[mo] ?? 0),
    marker: {color: color(i)},
    hovertemplate: '%{y:.2f}%<extra>' + s.name + '</extra>',
  }));
  Plotly.react('monthly', moTraces, Object.assign(baseLayout(t), {
    barmode: 'group', bargap: 0.25, bargroupgap: 0.12, barcornerradius: 4,
    yaxis: Object.assign(baseLayout(t).yaxis, {ticksuffix: '%'}),
    margin: {l: 56, r: 24, t: 8, b: 44},
  }), config);

  // Trade scatter — >=8px markers with a 2px surface ring.
  const trTraces = S.map((s, i) => ({
    type: 'scatter', mode: 'markers', name: s.name,
    x: s.scatter.map(p => p.duration_h),
    y: s.scatter.map(p => p.profit_pct),
    text: s.scatter.map(p => p.pair + ' · ' + p.exit_reason),
    marker: {color: color(i), size: 9,
             line: {color: t.surface, width: 2}},
    hovertemplate: '%{text}<br>%{x:.1f}h · %{y:.2f}%<extra>' + s.name
                   + '</extra>',
  }));
  Plotly.react('trades', trTraces, Object.assign(baseLayout(t), {
    hovermode: 'closest',
    xaxis: Object.assign(baseLayout(t).xaxis,
                         {title: {text: 'hold time (hours)'}}),
    yaxis: Object.assign(baseLayout(t).yaxis,
                         {ticksuffix: '%', zeroline: true}),
    margin: {l: 56, r: 24, t: 8, b: 48},
  }), config);

  document.getElementById('footer').textContent =
    'Generated ' + DATA.generated +
    ' · fees included in every number · past performance does not predict ' +
    'future results.';
}

document.getElementById('themeToggle').addEventListener('click', () => {
  const next = mode() === 'dark' ? 'light' : 'dark';
  document.body.classList.remove('dark', 'light');
  document.body.classList.add(next);
  draw();
});
window.matchMedia('(prefers-color-scheme: dark)')
  .addEventListener('change', draw);
draw();
</script>
</body>
</html>
"""
