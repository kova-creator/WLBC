"""Command line entry point: ``wlbc``."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import webbrowser
from pathlib import Path

from ..goals import DEFAULT_GOALS_PATH, GoalsError, Plan, evaluate
from ..oura.cli import load_dotenv
from ..oura.errors import OuraError
from ..renpho.errors import RenphoError
from .merge import BODY_FIELDS, OURA_FIELDS, convert_units, summarize
from .report import build_report
from .sources import collect


def _resolve_range(args) -> tuple[dt.date, dt.date]:
    end = dt.date.fromisoformat(args.end) if args.end else dt.date.today()
    if args.start:
        start = dt.date.fromisoformat(args.start)
    else:
        start = end - dt.timedelta(days=args.days - 1)
    if start > end:
        raise SystemExit("error: --start is after --end")
    return start, end


def _load_plan(args) -> Plan | None:
    """The plan, if one is saved. Absent is fine — goals are optional."""
    path = Path(args.goals) if args.goals else DEFAULT_GOALS_PATH
    if not path.is_file():
        if args.goals:
            raise GoalsError(f"No plan at {path}.")
        return None
    return Plan.load(path)


def _gather(args):
    start, end = _resolve_range(args)
    body_start = dt.date.fromisoformat(args.body_start) if args.body_start else None
    records = collect(
        start,
        end,
        pick=args.pick,
        window_days=args.window,
        use_oura=not args.no_oura,
        use_renpho=not args.no_renpho,
        sandbox=args.sandbox,
        body_start=body_start,
    )
    return convert_units(records, args.units), summarize(convert_units(records, args.units))


def cmd_summary(args) -> int:
    records, summary = _gather(args)
    unit = args.units
    if not summary.weigh_ins:
        print("No body-composition measurements in this range.")
        return 0

    print(f"{summary.start_day} → {summary.end_day}  ({summary.days_covered} days, {summary.weigh_ins} weigh-ins)")
    print()
    # One weigh-in is a snapshot; change and rate need two points to mean
    # anything, and printing "+0.0" implies a measurement that never happened.
    comparable = summary.weigh_ins >= 2
    rows = [
        ("Weight now (trend)", summary.last_weight_kg, unit, 1),
        ("Weight at start", summary.first_weight_kg if comparable else None, unit, 1),
        ("Change", summary.change_kg if comparable else None, unit, 1),
        ("Rate", summary.kg_per_week if comparable else None, f"{unit}/week", 2),
        ("Body fat now", summary.last_body_fat_pct, "%", 1),
        ("Body fat change", summary.body_fat_change_pct if comparable else None, "pts", 1),
        ("Fat mass change", summary.fat_change_kg if comparable else None, unit, 1),
        ("Lean mass change", summary.lean_change_kg if comparable else None, unit, 1),
    ]
    for label, value, suffix, digits in rows:
        if value is None:
            continue
        sign = "+" if label.endswith(("Change", "change", "Rate")) else ""
        print(f"  {label:<22} {value:{sign}.{digits}f} {suffix}")

    plan = _load_plan(args)
    if plan is not None:
        progress = evaluate(plan.in_units(unit), records, summary.kg_per_week)
        print(f"\nAgainst plan  ({plan.start_date} → {plan.end_date}, week {progress.week:.1f})")
        if progress.target is not None:
            print(f"  {'Target today':<22} {progress.target:.1f} {unit}")
            print(f"  {'Difference':<22} {progress.delta:+.1f} {unit}  ({progress.status})")
        if progress.remaining is not None:
            print(f"  {'Remaining to goal':<22} {abs(progress.remaining):.1f} {unit}")
        print(f"  {'Required rate':<22} {progress.required_per_week:+.2f} {unit}/week")
        if progress.actual_per_week is not None:
            print(f"  {'Your rate':<22} {progress.actual_per_week:+.2f} {unit}/week")
        if progress.projected_end_weight is not None:
            print(f"  {'Projected at week 52':<22} {progress.projected_end_weight:.1f} {unit}")
    return 0


def cmd_merge(args) -> int:
    records, _ = _gather(args)
    if args.only_measured:
        records = [record for record in records if record.has_body_comp]
    payload = [record.to_dict() for record in records]

    if args.csv:
        columns = (
            ["day", *BODY_FIELDS, *OURA_FIELDS]
            + [f"{m}_trend" for m in ("weight_kg", "body_fat_pct", "fat_mass_kg", "lean_mass_kg")]
            + [f"{m}_delta" for m in ("weight_kg", "fat_mass_kg", "lean_mass_kg")]
        )
        stream = open(args.csv, "w", newline="") if args.csv != "-" else sys.stdout
        try:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(payload)
        finally:
            if stream is not sys.stdout:
                stream.close()
                print(f"Wrote {len(payload)} rows to {args.csv}")
        return 0

    if args.json and args.json != "-":
        Path(args.json).write_text(json.dumps(payload, indent=2))
        print(f"Wrote {len(payload)} rows to {args.json}")
        return 0

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_goals(args) -> int:
    path = Path(args.goals) if args.goals else DEFAULT_GOALS_PATH
    if args.import_from:
        plan = Plan.from_xlsx(args.import_from)
        plan.save(path)
        print(f"Imported plan from {args.import_from}\nSaved to {path.resolve()}\n")
    else:
        plan = Plan.load(path)

    unit = plan.units
    print(f"{plan.start_date} → {plan.end_date}  ({plan.plan_weeks} weeks)")
    print(f"  Start weight         {plan.start_weight:.1f} {unit}")
    print(f"  Goal weight          {plan.goal_weight:.1f} {unit}")
    print(f"  Total to lose        {abs(plan.total_change):.1f} {unit}")
    print(f"  Required rate        {plan.per_week:+.2f} {unit}/week")
    if plan.target_calories:
        print(f"  Target calories      {plan.target_calories:.0f} kcal/day")
    print(
        f"  Steps                {plan.steps.baseline:,} → {plan.steps.goal:,}"
        f"  (+{plan.steps.increment:,} every {plan.steps.every_weeks} weeks)"
    )
    return 0


def cmd_report(args) -> int:
    records, summary = _gather(args)
    plan = _load_plan(args)
    html = build_report(
        records,
        summary,
        units=args.units,
        window_days=args.window,
        title=args.title,
        plan=plan.in_units(args.units) if plan else None,
    )
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out.resolve()}  ({summary.weigh_ins} weigh-ins, {summary.days_covered} days)")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wlbc",
        description="Combine Renpho body composition with Oura daily metrics.",
    )
    parser.add_argument("--days", type=int, default=90, help="range length ending today (default: 90)")
    parser.add_argument("--start", help="start date YYYY-MM-DD (overrides --days)")
    parser.add_argument("--end", help="end date YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--units",
        choices=["kg", "lb"],
        default=None,
        help="mass units (defaults to your plan's units, else kg)",
    )
    parser.add_argument(
        "--goals",
        metavar="PATH",
        help=f"plan file to read (default: {DEFAULT_GOALS_PATH} if it exists)",
    )
    parser.add_argument("--window", type=int, default=7, help="trailing trend window in days (default: 7)")
    parser.add_argument(
        "--pick",
        choices=["first", "last", "mean"],
        default="first",
        help="which weigh-in to use when a day has several (default: first, the morning reading)",
    )
    parser.add_argument(
        "--body-start",
        metavar="YYYY-MM-DD",
        help=(
            "ignore Renpho weigh-ins before this date, without shortening Oura's range. "
            "Use when older scale readings aren't yours or aren't trustworthy."
        ),
    )
    parser.add_argument("--no-oura", action="store_true", help="skip Oura; body composition only")
    parser.add_argument("--no-renpho", action="store_true", help="skip Renpho; Oura only")
    parser.add_argument("--sandbox", action="store_true", help="use Oura's sample-data sandbox")

    sub = parser.add_subparsers(dest="command", required=True)

    summary = sub.add_parser("summary", help="print headline body-composition numbers")
    summary.set_defaults(func=cmd_summary)

    merge = sub.add_parser("merge", help="emit the merged daily dataset")
    merge.add_argument("--csv", metavar="PATH", help="write CSV ('-' for stdout)")
    merge.add_argument("--json", metavar="PATH", help="write JSON ('-' for stdout)")
    merge.add_argument("--only-measured", action="store_true", help="drop days with no weigh-in")
    merge.set_defaults(func=cmd_merge)

    goals = sub.add_parser("goals", help="show or import your weight/step plan")
    goals.add_argument(
        "--import",
        dest="import_from",
        metavar="FILE.xlsx",
        help="import the plan from a tracker spreadsheet and save it",
    )
    goals.set_defaults(func=cmd_goals)

    report = sub.add_parser("report", help="build the HTML report")
    report.add_argument("-o", "--out", default="wlbc-report.html", help="output path")
    report.add_argument("--title", default="Body composition", help="report heading")
    report.add_argument("--open", action="store_true", help="open the report in a browser")
    report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Both sources read credentials from the environment. Renpho's config loader
    # happens to load .env as a side effect, but that only fires when Renpho is
    # in play — load it up front so --no-renpho still finds the Oura token.
    load_dotenv()
    args = build_parser().parse_args(argv)
    if args.no_oura and args.no_renpho:
        print("error: --no-oura and --no-renpho together leave nothing to fetch.", file=sys.stderr)
        return 2

    # Your plan is in pounds; the tool defaults to kg. Follow the plan unless
    # --units says otherwise, so the report and the plan never disagree.
    if args.units is None:
        try:
            plan = _load_plan(args)
        except GoalsError:
            plan = None
        args.units = plan.units if plan else "kg"

    try:
        return args.func(args)
    except (OuraError, RenphoError, GoalsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
