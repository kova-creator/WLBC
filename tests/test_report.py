"""Report rendering across the data shapes that actually occur.

These exist because the merge-layer tests could not catch structural mistakes in
the HTML: a chart guarded by the wrong condition still produces valid output,
just the wrong page.
"""

import datetime as dt
import html as html_lib
import json
import re

import pytest


def chart_specs(html):
    """The parsed spec of every chart on the page.

    The rendered page also embeds the full row data, where every trend key is
    present whether or not a chart uses it — so assertions about which series a
    chart draws have to read the specs, not the payload.
    """
    return [
        json.loads(html_lib.unescape(match))
        for match in re.findall(r'data-chart="([^"]*)"', html)
    ]


def series_keys(html):
    return {series["key"] for spec in chart_specs(html) for series in spec["series"]}

from wlbc.combined.merge import add_deltas, add_trends, merge_daily, summarize
from wlbc.combined.report import build_report

START = dt.date(2026, 4, 3)


def build(body, oura=None, *, start=START, end=dt.date(2026, 8, 6), **kwargs):
    records = add_deltas(add_trends(merge_daily(body, oura or {}, start=start, end=end)))
    return build_report(records, summarize(records), **kwargs)


def daily_weights(first_day, count, start_kg=80.0, step=-0.05):
    return {
        first_day + dt.timedelta(days=i): {
            "weight_kg": start_kg + step * i,
            "body_fat_pct": 25.0,
            "fat_mass_kg": (start_kg + step * i) * 0.25,
            "lean_mass_kg": (start_kg + step * i) * 0.75,
        }
        for i in range(count)
    }


def test_no_body_data_renders_the_empty_notice_once():
    html = build({}, {START: {"sleep_score": 80}})
    assert html.count("No Renpho measurements in this range.") == 1
    assert "Where the change came from" not in html


def test_single_weigh_in_still_shows_weight_and_body_fat():
    html = build({dt.date(2026, 8, 5): {"weight_kg": 69.7, "body_fat_pct": 33.3}})
    assert "Weight (kg)" in html
    assert "Body fat (%)" in html
    # But not the empty notice — there IS data.
    assert "No Renpho measurements" not in html


def test_single_weigh_in_suppresses_change_rate_and_split():
    html = build({dt.date(2026, 8, 5): {"weight_kg": 69.7, "body_fat_pct": 33.3}})
    # A "+0.0 kg change over 126 days" tile would imply a measured no-change.
    assert "Change over range" not in html
    assert "Rate" not in html
    assert "Where the change came from" not in html
    assert "Composition of change" not in html


def test_single_weigh_in_is_not_pluralised():
    html = build({dt.date(2026, 8, 5): {"weight_kg": 69.7}})
    assert "1 weigh-in " in html or "1 weigh-in<" in html
    assert "1 weigh-ins" not in html


def test_two_weigh_ins_bring_back_change_and_split():
    body = {
        dt.date(2026, 8, 4): {"weight_kg": 70.0, "fat_mass_kg": 23.0, "lean_mass_kg": 47.0},
        dt.date(2026, 8, 5): {"weight_kg": 69.5, "fat_mass_kg": 22.6, "lean_mass_kg": 46.9},
    }
    html = build(body)
    assert "Change over range" in html
    assert "Where the change came from" in html


def test_sparse_data_uses_readings_not_a_trend_line():
    body = {START + dt.timedelta(days=20 * i): {"weight_kg": 80.0 - i} for i in range(5)}
    html = build(body)
    assert "too sparse to smooth" in html
    assert "Reading to reading" in html
    # The weight chart draws the readings themselves, not a smoothed series.
    assert "weight_kg_trend" not in series_keys(html)
    assert "weight_kg" in series_keys(html)


def test_dense_data_uses_the_trend_line():
    html = build(daily_weights(dt.date(2026, 6, 1), 60))
    assert "7-day trend" in html
    assert "weight_kg_trend" in series_keys(html)
    assert "too sparse" not in html


def test_body_charts_start_where_body_data_starts():
    # Oura runs from April; body composition only from August.
    oura = {START + dt.timedelta(days=i): {"sleep_score": 75} for i in range(126)}
    body = daily_weights(dt.date(2026, 8, 1), 6)
    html = build(body, oura)
    specs = chart_specs(html)
    body_offsets = {
        spec["from"] for spec in specs if any("weight" in s["key"] for s in spec["series"])
    }
    oura_offsets = {
        spec.get("from", 0) for spec in specs
        if any(s["key"] == "sleep_score" for s in spec["series"])
    }
    # 3 Apr to 1 Aug is 120 days, so the body charts skip that many rows.
    assert body_offsets == {120}
    # Oura keeps the full span.
    assert oura_offsets == {0}
    assert "body composition from 01 Aug 2026" in html


def test_report_is_self_contained():
    html = build(daily_weights(dt.date(2026, 7, 1), 30))
    for marker in ("<script src=", "<link rel=\"stylesheet\"", "https://cdn", "http://cdn"):
        assert marker not in html
    assert html.lstrip().startswith("<!doctype html>")


def test_table_view_is_always_present():
    html = build(daily_weights(dt.date(2026, 7, 1), 10))
    assert "Table view" in html
    assert "<table>" in html


@pytest.mark.parametrize("units,expected", [("kg", "Weight (kg)"), ("lb", "Weight (lb)")])
def test_units_reach_the_headings(units, expected):
    from wlbc.combined.merge import convert_units

    records = add_deltas(add_trends(merge_daily(daily_weights(dt.date(2026, 7, 1), 10), {})))
    records = convert_units(records, units)
    html = build_report(records, summarize(records), units=units)
    assert expected in html
