"""Command line entry point: ``wlbc-renpho``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from renpho.export import format_girth, format_measurement, save_csv, save_json

from .client import RenphoConnection
from .errors import RenphoError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wlbc-renpho",
        description="Log in to Renpho and pull scale / tape-measure data.",
    )
    parser.add_argument(
        "--limit", type=int, default=5, help="how many recent records to print (default: 5)"
    )
    parser.add_argument(
        "--girth", action="store_true", help="also fetch smart-tape circumference records"
    )
    parser.add_argument(
        "--out",
        type=Path,
        metavar="DIR",
        help="write the full history to DIR as JSON and CSV",
    )
    parser.add_argument("--debug", action="store_true", help="print upstream request details")
    return parser


def _tail(records: list[dict], limit: int) -> list[dict]:
    """The last *limit* records — ``--limit 0`` means print none, not all."""
    return records[-limit:] if limit > 0 else []


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        with RenphoConnection.from_env(debug=args.debug) as renpho:
            print(f"Logged in as {renpho.email or '?'} (user {renpho.user_id})")

            for table in renpho.measurement_tables():
                print(f"  table: {table.get('tableName', '?')} ({table.get('count', 0)} records)")

            measurements = renpho.measurements()
            print(f"\n{len(measurements)} measurements")
            for m in _tail(measurements, args.limit):
                print(format_measurement(m), "\n")

            girth = renpho.girth_measurements() if args.girth else []
            if args.girth:
                print(f"{len(girth)} girth records")
                for g in _tail(girth, args.limit):
                    print(format_girth(g), "\n")

            if args.out:
                save_json(measurements, args.out / "measurements.json")
                save_csv(measurements, args.out / "measurements.csv")
                if girth:
                    save_json(girth, args.out / "girth.json")
                    save_csv(girth, args.out / "girth.csv")
                print(f"Saved to {args.out}/")
    except RenphoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
