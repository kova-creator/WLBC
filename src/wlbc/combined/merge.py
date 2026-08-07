"""Join Renpho body-composition data to Oura daily metrics on the calendar day.

Renpho is the primary series here: it carries weight, fat, and lean mass. Oura
rides along as daily context. The two are keyed on local calendar date, which is
the only key they share — Renpho stamps an epoch per weigh-in, Oura already
summarizes per ``day``.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Iterable, Literal, Sequence

KG_PER_LB = 0.45359237

BODY_FIELDS = (
    "weight_kg",
    "body_fat_pct",
    "fat_mass_kg",
    "lean_mass_kg",
    "bmi",
    "water_pct",
    "muscle_pct",
    "visceral_fat",
    "bmr",
)

OURA_FIELDS = (
    "sleep_score",
    "readiness_score",
    "activity_score",
    "steps",
    "active_calories",
    "total_sleep_hours",
    "resting_hr",
    "hrv",
    "temp_deviation",
)

Pick = Literal["first", "last", "mean"]


@dataclass
class DailyRecord:
    """One calendar day, with whatever each source had for it.

    Every metric is optional — body composition is measured when you step on the
    scale, not daily, and Oura has gaps whenever the ring is off the charger or
    off your hand.
    """

    day: dt.date

    weight_kg: float | None = None
    body_fat_pct: float | None = None
    fat_mass_kg: float | None = None
    lean_mass_kg: float | None = None
    bmi: float | None = None
    water_pct: float | None = None
    muscle_pct: float | None = None
    visceral_fat: float | None = None
    bmr: float | None = None

    sleep_score: float | None = None
    readiness_score: float | None = None
    activity_score: float | None = None
    steps: float | None = None
    active_calories: float | None = None
    total_sleep_hours: float | None = None
    resting_hr: float | None = None
    hrv: float | None = None
    temp_deviation: float | None = None

    # Trailing-window smoothing, filled in by add_trends().
    trend: dict[str, float | None] = field(default_factory=dict)
    # Change since the first trend value in range, filled in by add_deltas().
    delta: dict[str, float | None] = field(default_factory=dict)

    @property
    def has_body_comp(self) -> bool:
        return self.weight_kg is not None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["day"] = self.day.isoformat()
        for suffix in ("trend", "delta"):
            for key, value in (data.pop(suffix, {}) or {}).items():
                data[f"{key}_{suffix}"] = value
        return data


# ---------------------------------------------------------------------------
# Renpho


def _measurement_day(measurement: dict) -> dt.date | None:
    """Local calendar day of a weigh-in.

    ``localCreatedAt`` is already the user's wall clock, so it beats converting
    the epoch through whatever timezone this script happens to run in.
    """
    local = measurement.get("localCreatedAt") or measurement.get("local_created_at")
    if isinstance(local, str) and len(local) >= 10:
        try:
            return dt.date.fromisoformat(local[:10])
        except ValueError:
            pass

    epoch = measurement.get("timeStamp") or measurement.get("time_stamp")
    if epoch:
        try:
            return dt.datetime.fromtimestamp(int(epoch)).date()
        except (ValueError, OSError, OverflowError):
            return None
    return None


def _number(value: Any) -> float | None:
    """Renpho sends unmeasured metrics as 0 or an empty string, not null."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number == 0.0 or math.isnan(number):
        return None
    return number


def _body_comp(measurement: dict) -> dict[str, float | None]:
    weight = _number(measurement.get("weight"))
    fat_pct = _number(measurement.get("bodyfat"))

    fat_mass = weight * fat_pct / 100.0 if weight and fat_pct else None
    # `sinew` is Renpho's lean body mass in kg; derive it if the scale skipped it.
    lean = _number(measurement.get("sinew")) or _number(measurement.get("fatFreeWeight"))
    if lean is None and weight and fat_mass is not None:
        lean = weight - fat_mass

    return {
        "weight_kg": weight,
        "body_fat_pct": fat_pct,
        "fat_mass_kg": fat_mass,
        "lean_mass_kg": lean,
        "bmi": _number(measurement.get("bmi")),
        "water_pct": _number(measurement.get("water")),
        "muscle_pct": _number(measurement.get("muscle")),
        "visceral_fat": _number(measurement.get("visfat")),
        "bmr": _number(measurement.get("bmr")),
    }


def renpho_by_day(
    measurements: Iterable[dict],
    pick: Pick = "first",
) -> dict[dt.date, dict[str, float | None]]:
    """Collapse weigh-ins to one record per day.

    ``pick`` decides what to do with multiple weigh-ins on the same day.
    ``first`` (the default) takes the earliest, which is normally the
    fasted morning reading and the most comparable day to day.
    """
    if pick not in ("first", "last", "mean"):
        raise ValueError(f"pick must be 'first', 'last', or 'mean'; got {pick!r}")

    buckets: dict[dt.date, list[dict]] = {}
    for measurement in measurements:
        day = _measurement_day(measurement)
        if day is None:
            continue
        buckets.setdefault(day, []).append(measurement)

    result: dict[dt.date, dict[str, float | None]] = {}
    for day, group in buckets.items():
        # Renpho returns oldest-first, but do not rely on the caller preserving that.
        group = sorted(group, key=lambda m: int(m.get("timeStamp") or m.get("time_stamp") or 0))
        if pick == "first":
            result[day] = _body_comp(group[0])
        elif pick == "last":
            result[day] = _body_comp(group[-1])
        else:
            per_metric = [_body_comp(m) for m in group]
            result[day] = {
                key: (statistics.fmean(values) if (values := [d[key] for d in per_metric if d[key] is not None]) else None)
                for key in BODY_FIELDS
            }
    return result


# ---------------------------------------------------------------------------
# Oura


def _oura_day(document: dict) -> dt.date | None:
    raw = document.get("day")
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def oura_by_day(
    daily_sleep: Sequence[dict] = (),
    daily_readiness: Sequence[dict] = (),
    daily_activity: Sequence[dict] = (),
    sleep_periods: Sequence[dict] = (),
) -> dict[dt.date, dict[str, float | None]]:
    """Fold Oura's four daily collections into one record per day."""
    days: dict[dt.date, dict[str, float | None]] = {}

    def slot(day: dt.date) -> dict[str, float | None]:
        return days.setdefault(day, {key: None for key in OURA_FIELDS})

    for document in daily_sleep:
        if (day := _oura_day(document)) is not None:
            slot(day)["sleep_score"] = _number(document.get("score"))

    for document in daily_readiness:
        if (day := _oura_day(document)) is not None:
            entry = slot(day)
            entry["readiness_score"] = _number(document.get("score"))
            # Can legitimately be negative, so _number()'s zero-stripping is wrong here.
            deviation = document.get("temperature_deviation")
            entry["temp_deviation"] = float(deviation) if isinstance(deviation, (int, float)) else None

    for document in daily_activity:
        if (day := _oura_day(document)) is not None:
            entry = slot(day)
            entry["activity_score"] = _number(document.get("score"))
            entry["steps"] = _number(document.get("steps"))
            entry["active_calories"] = _number(document.get("active_calories"))

    # A day can hold naps as well as the night; the longest period is the night.
    longest: dict[dt.date, dict] = {}
    for document in sleep_periods:
        day = _oura_day(document)
        if day is None:
            continue
        duration = _number(document.get("total_sleep_duration")) or 0.0
        best = longest.get(day)
        if best is None or duration > (_number(best.get("total_sleep_duration")) or 0.0):
            longest[day] = document

    for day, document in longest.items():
        entry = slot(day)
        seconds = _number(document.get("total_sleep_duration"))
        entry["total_sleep_hours"] = seconds / 3600.0 if seconds else None
        entry["resting_hr"] = _number(document.get("lowest_heart_rate")) or _number(
            document.get("average_heart_rate")
        )
        entry["hrv"] = _number(document.get("average_hrv"))

    return days


# ---------------------------------------------------------------------------
# Join and derive


def merge_daily(
    body_by_day: dict[dt.date, dict[str, float | None]],
    oura_by_day_map: dict[dt.date, dict[str, float | None]] | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    fill_gaps: bool = True,
) -> list[DailyRecord]:
    """Produce one DailyRecord per day, ascending.

    With ``fill_gaps`` the range is a continuous run of calendar days, so days
    with no data anywhere still appear (empty). That keeps the x-axis honest:
    a two-week gap between weigh-ins looks like a two-week gap, not one step.
    """
    oura_by_day_map = oura_by_day_map or {}
    known = sorted({*body_by_day, *oura_by_day_map})
    if not known and not (start and end):
        return []

    first = start or (known[0] if known else end)
    last = end or (known[-1] if known else start)
    if first is None or last is None or first > last:
        return []

    if fill_gaps:
        span = (last - first).days
        all_days = [first + dt.timedelta(days=offset) for offset in range(span + 1)]
    else:
        all_days = [day for day in known if first <= day <= last]

    records = []
    for day in all_days:
        record = DailyRecord(day=day)
        for key, value in (body_by_day.get(day) or {}).items():
            setattr(record, key, value)
        for key, value in (oura_by_day_map.get(day) or {}).items():
            setattr(record, key, value)
        records.append(record)
    return records


def add_trends(
    records: Sequence[DailyRecord],
    metrics: Sequence[str] = ("weight_kg", "body_fat_pct", "fat_mass_kg", "lean_mass_kg"),
    window_days: int = 7,
    min_observations: int = 2,
) -> list[DailyRecord]:
    """Attach a trailing-mean trend for each metric, in place.

    The window is measured in *calendar days*, not in rows, so a gap in
    weigh-ins widens the window rather than silently reaching further back
    through time than intended. Day-to-day scale weight swings by a kilo or more
    on water alone; the trend line is the part worth reading.

    ``min_observations`` guards against the degenerate case: a window holding a
    single weigh-in has nothing to average, and averaging it anyway produces a
    flat plateau that holds the last reading for a week and then steps. On
    sparse data that staircase reads as "weight was stable, then jumped" when
    the truth is just "there was one measurement." Below the threshold the trend
    is None, and the chart falls back to showing the readings themselves.
    """
    if window_days < 1:
        raise ValueError("window_days must be at least 1")
    if min_observations < 1:
        raise ValueError("min_observations must be at least 1")

    for index, record in enumerate(records):
        cutoff = record.day - dt.timedelta(days=window_days - 1)
        for metric in metrics:
            values = [
                value
                for earlier in records[: index + 1]
                if earlier.day >= cutoff
                and (value := getattr(earlier, metric)) is not None
            ]
            record.trend[metric] = (
                statistics.fmean(values) if len(values) >= min_observations else None
            )
    return list(records)


def add_deltas(
    records: Sequence[DailyRecord],
    metrics: Sequence[str] = ("fat_mass_kg", "lean_mass_kg", "weight_kg"),
) -> list[DailyRecord]:
    """Attach each metric's change since the start of the range, in place.

    Fat mass and lean mass sit tens of kilos apart, so plotting them raw on one
    axis flattens both into straight lines. Indexed to a common zero they share
    an axis honestly, and the split of any weight change is the thing you read
    straight off the chart.

    Baselines come from the trend where one exists, so the zero point is not
    whichever water-weight day happened to come first.
    """
    baselines: dict[str, float] = {}
    for record in records:
        for metric in metrics:
            value = record.trend.get(metric)
            if value is None:
                value = getattr(record, metric, None)
            if value is None:
                record.delta[metric] = None
                continue
            baselines.setdefault(metric, value)
            record.delta[metric] = value - baselines[metric]
    return list(records)


@dataclass
class Summary:
    """Headline numbers over the covered range."""

    start_day: dt.date | None = None
    end_day: dt.date | None = None
    days_covered: int = 0
    weigh_ins: int = 0
    first_weight_kg: float | None = None
    last_weight_kg: float | None = None
    change_kg: float | None = None
    kg_per_week: float | None = None
    first_body_fat_pct: float | None = None
    last_body_fat_pct: float | None = None
    body_fat_change_pct: float | None = None
    lean_change_kg: float | None = None
    fat_change_kg: float | None = None


def _linear_rate_per_day(points: Sequence[tuple[dt.date, float]]) -> float | None:
    """Least-squares slope in units/day. Needs two points on distinct days."""
    if len(points) < 2:
        return None
    origin = points[0][0]
    xs = [(day - origin).days for day, _ in points]
    ys = [value for _, value in points]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator


def summarize(records: Sequence[DailyRecord]) -> Summary:
    """Headline body-composition numbers.

    Endpoints come from the smoothed trend where one exists, so the summary is
    not hostage to whether the first and last weigh-ins happened to be high or
    low water days. The rate is a least-squares fit over every weigh-in.
    """
    summary = Summary()
    if not records:
        return summary

    summary.start_day = records[0].day
    summary.end_day = records[-1].day
    summary.days_covered = (records[-1].day - records[0].day).days + 1

    weighed = [record for record in records if record.has_body_comp]
    summary.weigh_ins = len(weighed)
    if not weighed:
        return summary

    def endpoints(metric: str) -> tuple[float | None, float | None]:
        seen = [
            (record.trend.get(metric) or getattr(record, metric))
            for record in weighed
            if (record.trend.get(metric) is not None or getattr(record, metric) is not None)
        ]
        return (seen[0], seen[-1]) if seen else (None, None)

    summary.first_weight_kg, summary.last_weight_kg = endpoints("weight_kg")
    if summary.first_weight_kg is not None and summary.last_weight_kg is not None:
        summary.change_kg = summary.last_weight_kg - summary.first_weight_kg

    summary.first_body_fat_pct, summary.last_body_fat_pct = endpoints("body_fat_pct")
    if summary.first_body_fat_pct is not None and summary.last_body_fat_pct is not None:
        summary.body_fat_change_pct = summary.last_body_fat_pct - summary.first_body_fat_pct

    lean_first, lean_last = endpoints("lean_mass_kg")
    if lean_first is not None and lean_last is not None:
        summary.lean_change_kg = lean_last - lean_first

    fat_first, fat_last = endpoints("fat_mass_kg")
    if fat_first is not None and fat_last is not None:
        summary.fat_change_kg = fat_last - fat_first

    rate = _linear_rate_per_day(
        [(record.day, record.weight_kg) for record in weighed if record.weight_kg is not None]
    )
    summary.kg_per_week = rate * 7 if rate is not None else None
    return summary


def to_lb(kg: float | None) -> float | None:
    return None if kg is None else kg / KG_PER_LB


def convert_units(records: Sequence[DailyRecord], units: str) -> list[DailyRecord]:
    """Return records with mass metrics converted. ``kg`` is a no-op."""
    if units == "kg":
        return list(records)
    if units != "lb":
        raise ValueError(f"units must be 'kg' or 'lb'; got {units!r}")

    mass_metrics = ("weight_kg", "fat_mass_kg", "lean_mass_kg")
    converted = []
    for record in records:
        clone = DailyRecord(**{f.name: getattr(record, f.name) for f in fields(record)})
        clone.trend = dict(record.trend)
        clone.delta = dict(record.delta)
        for metric in mass_metrics:
            setattr(clone, metric, to_lb(getattr(clone, metric)))
            for mapping in (clone.trend, clone.delta):
                if metric in mapping:
                    mapping[metric] = to_lb(mapping[metric])
        converted.append(clone)
    return converted
