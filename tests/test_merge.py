import datetime as dt

import pytest

from wlbc.combined.merge import (
    DailyRecord,
    add_deltas,
    add_trends,
    convert_units,
    merge_daily,
    oura_by_day,
    renpho_by_day,
    summarize,
)


def measurement(day, weight, *, fat=20.0, hour=7, sinew=None):
    epoch = int(dt.datetime(day.year, day.month, day.day, hour).timestamp())
    record = {
        "timeStamp": epoch,
        "localCreatedAt": f"{day.isoformat()} {hour:02d}:00:00",
        "weight": weight,
        "bodyfat": fat,
        "bmi": 22.5,
        "water": 0,  # Renpho's "not measured" sentinel.
    }
    if sinew is not None:
        record["sinew"] = sinew
    return record


D1 = dt.date(2026, 7, 1)
D2 = dt.date(2026, 7, 2)


def test_zero_is_treated_as_missing_not_a_value():
    by_day = renpho_by_day([measurement(D1, 80.0)])
    assert by_day[D1]["water_pct"] is None
    assert by_day[D1]["weight_kg"] == 80.0


def test_derives_fat_and_lean_mass():
    by_day = renpho_by_day([measurement(D1, 80.0, fat=25.0)])
    assert by_day[D1]["fat_mass_kg"] == pytest.approx(20.0)
    assert by_day[D1]["lean_mass_kg"] == pytest.approx(60.0)


def test_prefers_reported_lean_mass_over_derived():
    by_day = renpho_by_day([measurement(D1, 80.0, fat=25.0, sinew=58.5)])
    assert by_day[D1]["lean_mass_kg"] == pytest.approx(58.5)


def test_pick_first_takes_the_morning_weigh_in():
    same_day = [
        measurement(D1, 81.5, hour=19),
        measurement(D1, 80.0, hour=7),
    ]
    assert renpho_by_day(same_day, pick="first")[D1]["weight_kg"] == 80.0
    assert renpho_by_day(same_day, pick="last")[D1]["weight_kg"] == 81.5
    assert renpho_by_day(same_day, pick="mean")[D1]["weight_kg"] == pytest.approx(80.75)


def test_local_date_wins_over_epoch_conversion():
    # A late-evening weigh-in must not drift to the next day via UTC.
    record = {"timeStamp": 0, "localCreatedAt": "2026-07-01 23:30:00", "weight": 80.0}
    assert list(renpho_by_day([record])) == [D1]


def test_merge_fills_calendar_gaps():
    body = {D1: {"weight_kg": 80.0}, dt.date(2026, 7, 5): {"weight_kg": 79.0}}
    records = merge_daily(body, {})
    assert [r.day for r in records] == [D1 + dt.timedelta(days=i) for i in range(5)]
    assert records[1].weight_kg is None


def test_trend_window_is_calendar_days_not_rows():
    body = {
        D1: {"weight_kg": 80.0},
        dt.date(2026, 7, 20): {"weight_kg": 70.0},
    }
    records = add_trends(merge_daily(body, {}), metrics=("weight_kg",), window_days=7)
    last = records[-1]
    # The 1 July reading is 19 days back, so it must not pull the trend down.
    assert last.trend["weight_kg"] == pytest.approx(70.0)


def test_trend_is_none_when_window_is_empty():
    body = {D1: {"weight_kg": 80.0}}
    records = add_trends(
        merge_daily(body, {}, start=D1, end=dt.date(2026, 7, 20)),
        metrics=("weight_kg",),
        window_days=7,
    )
    assert records[-1].trend["weight_kg"] is None


def test_oura_temperature_deviation_keeps_negative_and_zero():
    days = oura_by_day(daily_readiness=[
        {"day": "2026-07-01", "score": 80, "temperature_deviation": -0.3},
        {"day": "2026-07-02", "score": 80, "temperature_deviation": 0.0},
    ])
    assert days[D1]["temp_deviation"] == -0.3
    assert days[D2]["temp_deviation"] == 0.0


def test_oura_sleep_picks_the_longest_period_not_a_nap():
    days = oura_by_day(sleep_periods=[
        {"day": "2026-07-01", "total_sleep_duration": 1800, "average_hrv": 20, "lowest_heart_rate": 60},
        {"day": "2026-07-01", "total_sleep_duration": 27000, "average_hrv": 45, "lowest_heart_rate": 51},
    ])
    assert days[D1]["total_sleep_hours"] == pytest.approx(7.5)
    assert days[D1]["hrv"] == 45


def test_merge_joins_both_sources_on_the_day():
    records = merge_daily(
        {D1: {"weight_kg": 80.0}},
        {D1: {"sleep_score": 82}},
    )
    assert records[0].weight_kg == 80.0
    assert records[0].sleep_score == 82


def test_summary_rate_is_per_week():
    body = {D1 + dt.timedelta(days=i): {"weight_kg": 80.0 - 0.1 * i} for i in range(15)}
    records = add_trends(merge_daily(body, {}), metrics=("weight_kg",))
    summary = summarize(records)
    assert summary.kg_per_week == pytest.approx(-0.7)
    assert summary.weigh_ins == 15


def test_summary_is_empty_without_weigh_ins():
    records = merge_daily({}, {D1: {"sleep_score": 70}})
    summary = summarize(records)
    assert summary.weigh_ins == 0
    assert summary.change_kg is None


def test_convert_units_converts_mass_and_trend_but_not_percent():
    record = DailyRecord(day=D1, weight_kg=100.0, body_fat_pct=25.0, fat_mass_kg=25.0)
    record.trend = {"weight_kg": 100.0}
    converted = convert_units([record], "lb")[0]
    assert converted.weight_kg == pytest.approx(220.462, rel=1e-4)
    assert converted.trend["weight_kg"] == pytest.approx(220.462, rel=1e-4)
    assert converted.body_fat_pct == 25.0
    # The original must be untouched.
    assert record.weight_kg == 100.0


def test_convert_units_rejects_unknown_unit():
    with pytest.raises(ValueError):
        convert_units([], "stone")


def test_deltas_are_measured_from_the_first_value():
    body = {
        D1: {"fat_mass_kg": 25.0, "lean_mass_kg": 60.0},
        D1 + dt.timedelta(days=10): {"fat_mass_kg": 22.0, "lean_mass_kg": 59.5},
    }
    records = add_deltas(add_trends(merge_daily(body, {}), metrics=("fat_mass_kg", "lean_mass_kg")))
    assert records[0].delta["fat_mass_kg"] == pytest.approx(0.0)
    assert records[-1].delta["fat_mass_kg"] == pytest.approx(-3.0)
    assert records[-1].delta["lean_mass_kg"] == pytest.approx(-0.5)


def test_deltas_skip_days_without_data_rather_than_reading_zero():
    body = {D1: {"fat_mass_kg": 25.0}, D1 + dt.timedelta(days=4): {"fat_mass_kg": 24.0}}
    records = add_deltas(add_trends(merge_daily(body, {}), metrics=("fat_mass_kg",), window_days=1))
    # A gap day is None, not 0.0 — a flat line through a gap would invent data.
    assert records[1].delta["fat_mass_kg"] is None
    assert records[4].delta["fat_mass_kg"] == pytest.approx(-1.0)


def test_to_dict_exposes_trend_and_delta_suffixes():
    record = DailyRecord(day=D1, weight_kg=80.0)
    record.trend = {"weight_kg": 80.5}
    record.delta = {"weight_kg": -1.5}
    data = record.to_dict()
    assert data["weight_kg_trend"] == 80.5
    assert data["weight_kg_delta"] == -1.5
    assert data["day"] == "2026-07-01"
    assert "trend" not in data and "delta" not in data


def test_convert_units_converts_deltas_too():
    record = DailyRecord(day=D1, weight_kg=100.0)
    record.delta = {"fat_mass_kg": -1.0}
    converted = convert_units([record], "lb")[0]
    assert converted.delta["fat_mass_kg"] == pytest.approx(-2.20462, rel=1e-4)
