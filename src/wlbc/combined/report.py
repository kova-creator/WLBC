"""Render a self-contained HTML body-composition report.

No external assets: the CSS, the JS, and the data all live in the one file, so
it opens from disk and keeps working offline.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from typing import Sequence

from ..goals import Plan, evaluate
from .merge import DailyRecord, Summary

# Slots 1-3 of the reference palette, at their documented hexes. That subset is
# recorded as clearing the all-pairs CVD and normal-vision floors in both modes.
_CSS = """
:root {
  color-scheme: light;
  --surface-1: #fcfcfb;
  --page: #f9f9f7;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --text-muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11, 11, 11, 0.10);
  --series-1: #2a78d6;
  --series-2: #eb6834;
  --series-3: #1baf7a;
  --good: #006300;
  --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface-1: #1a1a19;
    --page: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255, 255, 255, 0.10);
    --series-1: #3987e5;
    --series-2: #d95926;
    --series-3: #199e70;
    --good: #0ca30c;
    --critical: #d03b3b;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19;
  --page: #0d0d0d;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --text-muted: #898781;
  --grid: #2c2c2a;
  --axis: #383835;
  --border: rgba(255, 255, 255, 0.10);
  --series-1: #3987e5;
  --series-2: #d95926;
  --series-3: #199e70;
  --good: #0ca30c;
  --critical: #d03b3b;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 32px 20px 64px;
  background: var(--page);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px;
  line-height: 1.5;
}
.wrap { max-width: 1040px; margin: 0 auto; }
header { margin-bottom: 28px; }
h1 { font-size: 1.5rem; font-weight: 600; margin: 0 0 4px; letter-spacing: -0.01em; }
.subhead { color: var(--text-secondary); font-size: 0.9rem; margin: 0; }

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 28px;
}
.tile {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
}
.tile .label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.tile .value { font-size: 2rem; font-weight: 600; letter-spacing: -0.02em; }
.tile .unit { font-size: 0.95rem; font-weight: 400; color: var(--text-secondary); margin-left: 3px; }
.tile .note { font-size: 0.8rem; color: var(--text-secondary); margin-top: 4px; }
.delta-down { color: var(--good); }
.delta-up { color: var(--critical); }

.card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px 20px 12px;
  margin-bottom: 20px;
}
.card h2 { font-size: 1rem; font-weight: 600; margin: 0 0 2px; }
.card .caption { font-size: 0.82rem; color: var(--text-secondary); margin: 0 0 12px; }
.chart { width: 100%; position: relative; }
.chart svg { display: block; width: 100%; overflow: visible; }

/* Chart ink is driven by CSS, never baked into the SVG by JS — so a theme
   change (OS or toggle) recolors every mark without a re-render. */
.grid { stroke: var(--grid); stroke-width: 1; }
.axis-line { stroke: var(--axis); stroke-width: 1; }
.tick-label { fill: var(--text-muted); font-size: 11px; }
.tick-label.y { font-variant-numeric: tabular-nums; }
.mark-line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.mark-dot { stroke: var(--surface-1); stroke-width: 2; opacity: 0.55; }
.end-label { fill: var(--text-secondary); font-size: 11px; font-weight: 600; }

.legend { display: flex; flex-wrap: wrap; gap: 16px; margin: 0 0 10px; padding: 0; list-style: none; }
.legend li { display: flex; align-items: center; gap: 7px; font-size: 0.82rem; color: var(--text-secondary); }
.swatch { width: 11px; height: 11px; border-radius: 3px; flex: none; }
.swatch.line { height: 3px; border-radius: 2px; width: 16px; }

.small-multiples { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; }
.small-multiples .panel h3 { font-size: 0.85rem; font-weight: 600; margin: 0 0 2px; }
.small-multiples .panel .caption { font-size: 0.78rem; margin-bottom: 8px; }

.tooltip {
  position: absolute;
  pointer-events: none;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 0.8rem;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.13);
  opacity: 0;
  transition: opacity 0.1s;
  z-index: 5;
  white-space: nowrap;
}
.tooltip .tt-day { color: var(--text-muted); margin-bottom: 4px; font-size: 0.75rem; }
.tooltip .tt-row { display: flex; align-items: center; gap: 6px; }
.tooltip .tt-val { font-variant-numeric: tabular-nums; margin-left: auto; padding-left: 12px; }

details.table-view { margin-top: 8px; }
details.table-view summary {
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--text-secondary);
  padding: 6px 0;
}
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.82rem; margin-top: 8px; }
th, td { text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.05em; }

.empty { color: var(--text-secondary); font-size: 0.88rem; padding: 20px 0; }
footer { color: var(--text-muted); font-size: 0.78rem; margin-top: 28px; }
"""

_JS = r"""
const DATA = window.__WLBC__;
const PAD = { top: 12, right: 16, bottom: 26, left: 46 };

function fmt(value, digits) {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}
function shortDay(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}`;
}

/* Nice round axis ticks that bracket the data.
   The step ladder includes 2.5 so a range like 45 does not jump to a step of 20
   and drag the axis floor all the way to zero, flattening the series. */
function ticks(min, max, count) {
  if (!isFinite(min) || !isFinite(max)) return { lo: 0, hi: 1, values: [0, 1] };
  if (min === max) { min -= 1; max += 1; }
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2.5 ? 5 : norm >= 2 ? 2.5 : norm >= 1.5 ? 2 : 1.5) * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const values = [];
  for (let v = lo; v <= hi + step / 2; v += step) values.push(+(Math.round(v / step) * step).toFixed(6));
  return { lo, hi, values };
}

function el(tag, attrs, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const key in attrs) node.setAttribute(key, attrs[key]);
  if (text !== undefined) node.textContent = text;
  return node;
}

/**
 * One line/dot chart on a single y-axis.
 * spec: { series: [{key, label, color, type: "line"|"dot", digits}], height, unit }
 */
function renderChart(container, spec) {
  const width = container.clientWidth || 640;
  const height = spec.height || 240;
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;

  container.innerHTML = "";
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": spec.ariaLabel || "" });

  // A chart may cover a sub-range of the report: body composition can start
  // later than Oura, and padding it with empty leading days would shrink the
  // real data into a sliver at the right edge.
  const rows = DATA.rows.slice(spec.from ?? 0, (spec.to ?? DATA.rows.length - 1) + 1);
  const allValues = [];
  for (const s of spec.series) {
    for (const row of rows) {
      const v = row[s.key];
      if (v !== null && v !== undefined) allValues.push(v);
    }
  }
  if (!allValues.length) {
    container.innerHTML = '<p class="empty">No data in this range.</p>';
    return;
  }

  const scale = ticks(Math.min(...allValues), Math.max(...allValues), 4);
  const x = (i) => PAD.left + (rows.length <= 1 ? plotW / 2 : (i / (rows.length - 1)) * plotW);
  const y = (v) => PAD.top + plotH - ((v - scale.lo) / (scale.hi - scale.lo)) * plotH;

  // Gridlines and y ticks — solid hairlines, one shade off the surface.
  for (const value of scale.values) {
    const yy = y(value);
    svg.appendChild(el("line", { class: "grid", x1: PAD.left, x2: PAD.left + plotW, y1: yy, y2: yy }));
    svg.appendChild(el("text", {
      class: "tick-label y", x: PAD.left - 8, y: yy + 4, "text-anchor": "end",
    }, String(+value.toFixed(2))));
  }
  svg.appendChild(el("line", {
    class: "axis-line",
    x1: PAD.left, x2: PAD.left + plotW, y1: PAD.top + plotH, y2: PAD.top + plotH,
  }));

  // On a change-from-baseline chart, zero is the reference the eye needs.
  if (spec.zeroLine && scale.lo < 0 && scale.hi > 0) {
    svg.appendChild(el("line", {
      class: "axis-line", x1: PAD.left, x2: PAD.left + plotW, y1: y(0), y2: y(0),
    }));
  }

  // x labels: first, middle, last only — enough to orient without collisions.
  const marks = rows.length > 2 ? [0, Math.floor((rows.length - 1) / 2), rows.length - 1] : rows.map((_, i) => i);
  for (const i of new Set(marks)) {
    svg.appendChild(el("text", {
      class: "tick-label", x: x(i), y: height - 8,
      "text-anchor": i === 0 ? "start" : i === rows.length - 1 ? "end" : "middle",
    }, shortDay(rows[i].day)));
  }

  for (const s of spec.series) {
    if (s.type === "dot") {
      for (let i = 0; i < rows.length; i++) {
        const v = rows[i][s.key];
        if (v === null || v === undefined) continue;
        // 2px surface ring keeps overlapping raw points readable against the trend line.
        svg.appendChild(el("circle", {
          class: "mark-dot", cx: x(i), cy: y(v), r: 4, style: `fill:var(${s.color})`,
        }));
      }
      continue;
    }
    // Break the path across gaps rather than bridging them.
    let run = [];
    const flush = () => {
      if (run.length > 1) {
        svg.appendChild(el("path", {
          class: "mark-line",
          d: "M" + run.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("L"),
          style: `stroke:var(${s.color})`,
        }));
      } else if (run.length === 1) {
        svg.appendChild(el("circle", {
          cx: run[0][0], cy: run[0][1], r: 3, style: `fill:var(${s.color})`,
        }));
      }
      run = [];
    };
    for (let i = 0; i < rows.length; i++) {
      const v = rows[i][s.key];
      if (v === null || v === undefined) { flush(); continue; }
      run.push([x(i), y(v)]);
    }
    flush();

    // Direct-label the endpoint only.
    if (s.label && spec.labelEnd !== false) {
      for (let i = rows.length - 1; i >= 0; i--) {
        const v = rows[i][s.key];
        if (v === null || v === undefined) continue;
        svg.appendChild(el("text", {
          class: "end-label", x: Math.min(x(i) + 6, width - 2), y: y(v) - 8, "text-anchor": "end",
        }, fmt(v, s.digits ?? 1)));
        break;
      }
    }
  }

  const crosshair = el("line", {
    class: "axis-line", y1: PAD.top, y2: PAD.top + plotH, opacity: 0,
  });
  svg.appendChild(crosshair);
  container.appendChild(svg);

  const tooltip = document.createElement("div");
  tooltip.className = "tooltip";
  container.appendChild(tooltip);

  // Full-plot hit area: no need to land on a mark.
  const move = (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * width;
    let index = Math.round(((px - PAD.left) / plotW) * (rows.length - 1));
    index = Math.max(0, Math.min(rows.length - 1, index));
    const row = rows[index];
    const shown = spec.series.filter((s) => row[s.key] !== null && row[s.key] !== undefined);
    if (!shown.length) { tooltip.style.opacity = 0; crosshair.setAttribute("opacity", 0); return; }

    crosshair.setAttribute("x1", x(index));
    crosshair.setAttribute("x2", x(index));
    crosshair.setAttribute("opacity", 1);
    tooltip.innerHTML =
      `<div class="tt-day">${row.day}</div>` +
      shown.map((s) =>
        `<div class="tt-row"><span class="swatch" style="background:var(${s.color})"></span>` +
        `<span>${s.label}</span><span class="tt-val">${fmt(row[s.key], s.digits ?? 1)}${spec.unit ? " " + spec.unit : ""}</span></div>`
      ).join("");
    tooltip.style.opacity = 1;
    const left = (x(index) / width) * container.clientWidth;
    tooltip.style.left = Math.min(Math.max(left + 12, 0), container.clientWidth - tooltip.offsetWidth - 4) + "px";
    tooltip.style.top = PAD.top + "px";
  };
  svg.addEventListener("mousemove", move);
  svg.addEventListener("mouseleave", () => {
    tooltip.style.opacity = 0;
    crosshair.setAttribute("opacity", 0);
  });
}

function renderAll() {
  for (const node of document.querySelectorAll("[data-chart]")) {
    renderChart(node, JSON.parse(node.dataset.chart));
  }
}

renderAll();
// Only layout needs a re-render; theme is handled entirely by CSS variables.
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(renderAll, 120);
});
"""


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _tile(label: str, value: str, unit: str = "", note: str = "", tone: str = "") -> str:
    cls = f" {tone}" if tone else ""
    unit_html = f'<span class="unit">{html.escape(unit)}</span>' if unit else ""
    note_html = f'<div class="note">{html.escape(note)}</div>' if note else ""
    return (
        '<div class="tile">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="value{cls}">{html.escape(value)}{unit_html}</div>'
        f"{note_html}</div>"
    )


def _legend(entries: Sequence[tuple[str, str, str]]) -> str:
    """entries: (label, css-var, "line"|"dot")."""
    items = "".join(
        f'<li><span class="swatch {kind}" style="background:var({color})"></span>{html.escape(label)}</li>'
        for label, color, kind in entries
    )
    return f'<ul class="legend">{items}</ul>'


def _chart_card(title: str, caption: str, spec: dict, legend: Sequence = ()) -> str:
    legend_html = _legend(legend) if len(legend) >= 2 else ""
    spec_json = html.escape(json.dumps(spec), quote=True)
    return (
        '<section class="card">'
        f"<h2>{html.escape(title)}</h2>"
        f'<p class="caption">{html.escape(caption)}</p>'
        f"{legend_html}"
        f'<div class="chart" data-chart="{spec_json}"></div>'
        "</section>"
    )


def _table(records: Sequence[DailyRecord], mass_unit: str) -> str:
    columns = [
        ("Day", lambda r: r.day.isoformat(), None),
        (f"Weight ({mass_unit})", lambda r: r.weight_kg, 1),
        (f"Trend ({mass_unit})", lambda r: r.trend.get("weight_kg"), 2),
        ("Body fat (%)", lambda r: r.body_fat_pct, 1),
        (f"Fat ({mass_unit})", lambda r: r.fat_mass_kg, 1),
        (f"Lean ({mass_unit})", lambda r: r.lean_mass_kg, 1),
        ("Sleep", lambda r: r.sleep_score, 0),
        ("Readiness", lambda r: r.readiness_score, 0),
        ("Steps", lambda r: r.steps, 0),
    ]
    head = "".join(f"<th>{html.escape(name)}</th>" for name, _, _ in columns)

    body_rows = []
    for record in records:
        # Only rows with something to show; a filled calendar gap is noise in a table.
        if not any(getter(record) is not None for _, getter, digits in columns if digits is not None):
            continue
        cells = []
        for _, getter, digits in columns:
            value = getter(record)
            if digits is None:
                cells.append(f"<td>{html.escape(str(value))}</td>")
            elif value is None:
                cells.append('<td class="muted">—</td>')
            else:
                cells.append(f"<td>{value:.{digits}f}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    return (
        '<details class="table-view"><summary>Table view (every value, no color needed)</summary>'
        f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table></div></details>"
    )


def build_report(
    records: Sequence[DailyRecord],
    summary: Summary,
    *,
    units: str = "kg",
    window_days: int = 7,
    title: str = "Body composition",
    generated: dt.datetime | None = None,
    plan: Plan | None = None,
) -> str:
    """Render the whole report to an HTML string.

    ``plan`` must already be in ``units`` — the caller converts, so the target
    line and the measured line can never end up on different scales.
    """
    mass_unit = "kg" if units == "kg" else "lb"
    generated = generated or dt.datetime.now()

    rows = [record.to_dict() for record in records]
    if plan is not None:
        for row, record in zip(rows, records):
            row["target_weight"] = plan.target_weight(record.day)
            row["target_steps"] = plan.target_steps(record.day)
    payload = {"rows": rows, "unit": mass_unit}

    # summary was computed on the already-converted records, so its rate is in
    # display units despite the field name.
    progress = evaluate(plan, records, summary.kg_per_week) if plan is not None else None

    span = (
        f"{summary.start_day:%d %b %Y} – {summary.end_day:%d %b %Y}"
        if summary.start_day and summary.end_day
        else "no data"
    )
    weigh_in_count = _plural(summary.weigh_ins, "weigh-in")
    subhead = f"{span} · {weigh_in_count} over {_plural(summary.days_covered, 'day')}"
    # A single reading is a snapshot, not a trajectory: change, rate, and the
    # fat/lean split all require two points to mean anything.
    comparable = summary.weigh_ins >= 2

    # Where body composition actually starts. Oura keeps the full span; the
    # body-comp charts begin here so a late start is not squeezed to the margin.
    body_from = next(
        (index for index, record in enumerate(records) if record.has_body_comp), 0
    )
    body_span = max(1, len(records) - body_from)

    if has_body := any(record.has_body_comp for record in records):
        body_first_day = records[body_from].day
        if body_from > 0:
            subhead = (
                f"Oura {span} · body composition from {body_first_day:%d %b %Y} "
                f"({weigh_in_count} over {_plural(body_span, 'day')})"
            )

    # Smoothing only earns its place when there is enough to smooth. Below
    # roughly one weigh-in every three days the trailing mean is mostly holding
    # a single reading, so the charts show the readings themselves instead.
    # Measured over the body-comp span, not the Oura span — otherwise a long
    # Oura history would make daily weigh-ins look sparse.
    dense = summary.weigh_ins >= max(3, body_span / 3)
    weight_line = "weight_kg_trend" if dense else "weight_kg"
    fat_pct_line = "body_fat_pct_trend" if dense else "body_fat_pct"
    line_label = f"{window_days}-day trend" if dense else "Reading to reading"

    # -- tiles -----------------------------------------------------------
    tiles = []
    if summary.last_weight_kg is not None:
        tiles.append(
            _tile(
                f"Weight ({window_days}-day trend)" if dense else "Weight (latest)",
                f"{summary.last_weight_kg:.1f}",
                mass_unit,
                weigh_in_count,
            )
        )
    if summary.change_kg is not None and comparable:
        tone = "delta-down" if summary.change_kg < 0 else "delta-up" if summary.change_kg > 0 else ""
        tiles.append(
            _tile(
                "Change over range",
                f"{summary.change_kg:+.1f}",
                mass_unit,
                f"over {_plural(summary.days_covered, 'day')}",
                tone,
            )
        )
    if summary.kg_per_week is not None and comparable:
        tone = "delta-down" if summary.kg_per_week < 0 else "delta-up" if summary.kg_per_week > 0 else ""
        tiles.append(
            _tile("Rate", f"{summary.kg_per_week:+.2f}", f"{mass_unit}/wk", "least-squares fit", tone)
        )
    if progress is not None and progress.delta is not None:
        # Colour follows the verdict, not the raw sign: being 0.1 lb over target
        # on day zero is noise, and painting it red would contradict the
        # "on track" label sitting directly beneath it.
        if progress.status == "on track":
            tone = ""
        else:
            tone = "delta-down" if progress.delta < 0 else "delta-up"
        tiles.append(
            _tile(
                "vs target",
                f"{progress.delta:+.1f}",
                mass_unit,
                f"{progress.status} · target {progress.target:.1f} {mass_unit}",
                tone,
            )
        )
    if progress is not None and progress.remaining is not None:
        tiles.append(
            _tile(
                "To goal",
                f"{abs(progress.remaining):.1f}",
                mass_unit,
                f"goal {plan.goal_weight:.0f} {mass_unit} by {plan.end_date:%d %b %Y}",
            )
        )

    if summary.last_body_fat_pct is not None:
        note = (
            f"{summary.body_fat_change_pct:+.1f} pts over range"
            if summary.body_fat_change_pct is not None and comparable
            else ""
        )
        tiles.append(_tile("Body fat", f"{summary.last_body_fat_pct:.1f}", "%", note))
    if summary.fat_change_kg is not None and summary.lean_change_kg is not None and comparable:
        tiles.append(
            _tile(
                "Composition of change",
                f"{summary.fat_change_kg:+.1f}",
                mass_unit,
                f"fat · {summary.lean_change_kg:+.1f} {mass_unit} lean",
            )
        )

    # -- charts ----------------------------------------------------------
    cards = []

    if has_body:
        if dense:
            weight_caption = (
                f"Each weigh-in as a dot, with the {window_days}-day trailing mean over it. "
                "Day-to-day scale weight moves on water and food; the line is the signal."
            )
        elif not comparable:
            weight_caption = (
                "A single weigh-in — a starting point, not a trend. Weigh in again and this "
                f"becomes a line; after about one reading every three days it becomes a "
                f"{window_days}-day trend."
            )
        else:
            weight_caption = (
                f"{weigh_in_count} over {_plural(body_span, 'day')} is too sparse to smooth — a "
                f"{window_days}-day mean would just hold each reading flat for a week and then "
                "step. These are the actual readings, connected. Weigh in more often and this "
                "becomes a trend line."
            )
        weight_series = [
            {"key": "weight_kg", "label": "Weigh-in", "color": "--series-1", "type": "dot", "digits": 1},
            {"key": weight_line, "label": line_label, "color": "--series-1", "type": "line", "digits": 2 if dense else 1},
        ]
        weight_legend = [("Weigh-in", "--series-1", "dot"), (line_label, "--series-1", "line")]
        if plan is not None:
            weight_series.append(
                {"key": "target_weight", "label": "Target", "color": "--series-3", "type": "line", "digits": 1}
            )
            weight_legend.append(("Target", "--series-3", "line"))
            weight_caption += (
                f" The target line runs from {plan.start_weight:.1f} to "
                f"{plan.goal_weight:.1f} {mass_unit} by {plan.end_date:%d %b %Y}; "
                "below it is ahead of plan."
            )

        cards.append(
            _chart_card(
                f"Weight ({mass_unit})",
                weight_caption,
                {
                    "series": weight_series,
                    "height": 260,
                    "unit": mass_unit,
                    "from": body_from,
                    "ariaLabel": "Weight over time against the plan target",
                },
                legend=weight_legend,
            )
        )
    # The fat/lean split needs two points to have a shape at all; with one
    # reading it would be a flat line pinned at zero, which says nothing.
    if has_body and comparable:
        cards.append(
            _chart_card(
                f"Where the change came from ({mass_unit} since {body_first_day:%d %b})",
                "Fat and lean mass sit tens of kilos apart, so plotting them raw would flatten both "
                "into straight lines. Indexed to zero at the start of the range they share an axis "
                "honestly: the gap between the two lines is the split of your weight change.",
                {
                    "series": [
                        {"key": "fat_mass_kg_delta", "label": "Fat mass", "color": "--series-2", "type": "line", "digits": 2},
                        {"key": "lean_mass_kg_delta", "label": "Lean mass", "color": "--series-3", "type": "line", "digits": 2},
                    ],
                    "height": 240,
                    "unit": mass_unit,
                    "zeroLine": True,
                    "from": body_from,
                    "ariaLabel": "Change in fat mass and lean mass since the start of the range",
                },
                legend=[("Fat mass", "--series-2", "line"), ("Lean mass", "--series-3", "line")],
            )
        )

    if has_body:
        cards.append(
            _chart_card(
                "Body fat (%)",
                "Percentage rather than mass — moves when fat and lean mass move differently.",
                {
                    "series": [
                        {"key": "body_fat_pct", "label": "Body fat", "color": "--series-2", "type": "dot", "digits": 1},
                        {"key": fat_pct_line, "label": line_label, "color": "--series-2", "type": "line", "digits": 2 if dense else 1},
                    ],
                    "height": 220,
                    "unit": "%",
                    "from": body_from,
                    "ariaLabel": "Body fat percentage over time",
                },
                legend=[("Reading", "--series-2", "dot"), (line_label, "--series-2", "line")],
            )
        )

    if not has_body:
        cards.append(
            '<section class="card"><p class="empty">No Renpho measurements in this range.'
            "</p></section>"
        )

    # Oura context: separate panels, each with its own axis. Never a shared scale.
    oura_panels = [
        ("sleep_score", "Sleep score", "Oura nightly sleep score.", 0),
        ("resting_hr", "Resting heart rate (bpm)", "Lowest heart rate during sleep.", 0),
        ("steps", "Steps", "Daily step count from Oura.", 0),
    ]
    available = [
        panel for panel in oura_panels
        if any(getattr(record, panel[0]) is not None for record in records)
    ]
    if available:
        panels_html = []
        for key, label, caption, digits in available:
            series = [{"key": key, "label": label, "color": "--series-1", "type": "line", "digits": digits}]
            legend = ()
            # Steps are the one Oura metric the plan sets a target for, and
            # both are step counts, so they share an axis honestly.
            if key == "steps" and plan is not None:
                series.append(
                    {"key": "target_steps", "label": "Target", "color": "--series-3", "type": "line", "digits": 0}
                )
                legend = [("Actual", "--series-1", "line"), ("Target", "--series-3", "line")]
                caption = (
                    f"Daily steps against the plan's ramp: {plan.steps.baseline:,} to "
                    f"{plan.steps.goal:,}, rising {plan.steps.increment:,} every "
                    f"{plan.steps.every_weeks} weeks."
                )
            spec = json.dumps({
                "series": series,
                "height": 150,
                "ariaLabel": label,
            })
            panels_html.append(
                '<div class="panel">'
                f"<h3>{html.escape(label)}</h3>"
                f'<p class="caption">{html.escape(caption)}</p>'
                f"{_legend(legend) if legend else ''}"
                f'<div class="chart" data-chart="{html.escape(spec, quote=True)}"></div>'
                "</div>"
            )
        cards.append(
            '<section class="card"><h2>Oura context</h2>'
            '<p class="caption">Separate panels with their own axes — these measure different things '
            "and do not belong on a shared scale.</p>"
            f'<div class="small-multiples">{"".join(panels_html)}</div></section>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — WLBC</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{html.escape(title)}</h1>
  <p class="subhead">{html.escape(subhead)}</p>
</header>
<div class="tiles">{"".join(tiles)}</div>
{"".join(cards)}
<section class="card">{_table(records, mass_unit)}</section>
<footer>Generated {generated:%d %b %Y %H:%M} by WLBC · Renpho body composition + Oura daily metrics</footer>
</div>
<script>window.__WLBC__ = {json.dumps(payload)};</script>
<script>{_JS}</script>
</body>
</html>
"""
