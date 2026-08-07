"""Command line entry point: ``wlbc``."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import webbrowser
from pathlib import Path

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
    rows = [
        ("Weight now (trend)", summary.last_weight_kg, unit, 1),
        ("Weight at start", summary.first_weight_kg, unit, 1),
        ("Change", summary.change_kg, unit, 1),
        ("Rate", summary.kg_per_week, f"{unit}/week", 2),
        ("Body fat now", summary.last_body_fat_pct, "%", 1),
        ("Body fat change", summary.body_fat_change_pct, "pts", 1),
        ("Fat mass change", summary.fat_change_kg, unit, 1),
        ("Lean mass change", summary.lean_change_kg, unit, 1),
    ]
    for label, value, suffix, digits in rows:
        if value is None:
            continue
        sign = "+" if label.endswith(("Change", "change", "Rate")) else ""
        print(f"  {label:<22} {value:{sign}.{digits}f} {suffix}")
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


def cmd_report(args) -> int:
    records, summary = _gather(args)
    html = build_report(
        records,
        summary,
        units=args.units,
        window_days=args.window,
        title=args.title,
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
    parser.add_argument("--units", choices=["kg", "lb"], default="kg", help="mass units (default: kg)")
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
    try:
        return args.func(args)
    except (OuraError, RenphoError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
