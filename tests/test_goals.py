import datetime as dt
import math

import pytest

from wlbc.combined.merge import DailyRecord
from wlbc.goals import GoalsError, Plan, StepPlan, evaluate

START = dt.date(2026, 8, 5)


def plan(**kwargs):
    defaults = dict(
        start_date=START,
        start_weight=153.6,
        goal_weight=128.0,
        plan_weeks=52,
        units="lb",
        steps=StepPlan(baseline=3000, goal=12000, increment=1000, every_weeks=2),
    )
    return Plan(**{**defaults, **kwargs})


def test_weekly_weight_targets_are_linear():
    p = plan()
    assert p.target_weight(START) == pytest.approx(153.6)
    assert p.target_weight(START + dt.timedelta(weeks=52)) == pytest.approx(128.0)
    assert p.target_weight(START + dt.timedelta(weeks=26)) == pytest.approx(140.8)
    assert p.per_week == pytest.approx(-25.6 / 52)


def test_step_ramp_matches_the_published_schedule():
    # Week 0 sits at baseline, then weeks 1-2 share a target, 3-4 the next.
    expected = {0: 3000, 1: 4000, 2: 4000, 3: 5000, 4: 5000, 13: 10000, 15: 11000}
    steps = plan().steps
    for week, value in expected.items():
        assert steps.target(week) == value


def test_step_target_caps_at_the_goal():
    steps = plan().steps
    assert steps.target(17) == 12000
    assert steps.target(52) == 12000
    assert steps.target(500) == 12000


def test_targets_are_absent_before_the_plan_starts():
    p = plan()
    assert p.target_weight(START - dt.timedelta(days=1)) is None
    assert p.target_steps(START - dt.timedelta(days=1)) is None


def test_weight_target_holds_at_goal_past_the_end():
    p = plan()
    beyond = p.target_weight(START + dt.timedelta(weeks=80))
    # The plan ends; the line must not keep falling below the goal.
    assert beyond == pytest.approx(128.0)


def test_unit_conversion_round_trips():
    p = plan()
    kg = p.in_units("kg")
    assert kg.units == "kg"
    assert kg.start_weight == pytest.approx(69.67, abs=0.01)
    assert kg.goal_weight == pytest.approx(58.06, abs=0.01)
    # Step targets are counts, not masses — unchanged.
    assert kg.target_steps(START) == p.target_steps(START)
    assert kg.in_units("lb").start_weight == pytest.approx(153.6)


def test_unit_conversion_rejects_nonsense():
    with pytest.raises(ValueError):
        plan().in_units("stone")


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "goals.json"
    plan().save(path)
    loaded = Plan.load(path)
    assert loaded.start_date == START
    assert loaded.goal_weight == 128.0
    assert loaded.steps.every_weeks == 2


def test_load_missing_plan_explains_how_to_make_one(tmp_path):
    with pytest.raises(GoalsError, match="goals import"):
        Plan.load(tmp_path / "nope.json")


def test_load_corrupt_plan_reports_the_path(tmp_path):
    path = tmp_path / "goals.json"
    path.write_text("{not json")
    with pytest.raises(GoalsError):
        Plan.load(path)


def record(day, weight):
    r = DailyRecord(day=day, weight_kg=weight)
    r.trend = {}
    return r


def test_evaluate_reports_being_ahead_of_plan():
    p = plan()
    day = START + dt.timedelta(weeks=10)
    # Target at week 10 is ~148.7; 147 is ahead.
    progress = evaluate(p, [record(day, 147.0)], actual_per_week=-0.6)
    assert progress.delta < 0
    assert progress.status == "ahead of plan"
    assert progress.on_track is True


def test_evaluate_reports_being_behind_plan():
    p = plan()
    day = START + dt.timedelta(weeks=10)
    progress = evaluate(p, [record(day, 152.0)], actual_per_week=-0.1)
    assert progress.delta > 0
    assert progress.status == "behind plan"
    assert progress.on_track is False


def test_evaluate_skips_projection_without_a_rate():
    p = plan()
    progress = evaluate(p, [record(START, 153.6)], actual_per_week=None)
    # One weigh-in cannot support a 52-week projection.
    assert progress.projected_end_weight is None
    assert progress.status == "on track"


def test_evaluate_projects_forward_from_the_measured_rate():
    p = plan()
    day = START + dt.timedelta(weeks=12)
    progress = evaluate(p, [record(day, 148.0)], actual_per_week=-0.5)
    assert progress.projected_end_weight == pytest.approx(148.0 - 0.5 * 40, abs=0.1)


def test_evaluate_with_no_weigh_ins_is_empty():
    progress = evaluate(plan(), [])
    assert progress.actual is None
    assert progress.status == "no data"


def test_step_plan_rejects_zero_frequency():
    with pytest.raises(ValueError):
        StepPlan(every_weeks=0).target(3)
