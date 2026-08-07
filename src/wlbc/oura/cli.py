"""Command line interface: `wlbc-oura`."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path

from .auth import ALL_SCOPES, EXTAPI_SCOPES, OAuth2Auth, TokenStore, auth_from_env
from .client import DATE_COLLECTIONS, DATETIME_COLLECTIONS, OuraClient
from .errors import OuraError


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader; real environment variables always win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _print(records, as_csv: bool) -> None:
    if not as_csv:
        json.dump(records, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    rows = records if isinstance(records, list) else [records]
    if not rows:
        return
    # Union of keys across rows, so a field missing from row 0 is not dropped.
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    writer = csv.DictWriter(sys.stdout, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _flatten(v) for k, v in row.items()})


def _flatten(value):
    return json.dumps(value, default=str) if isinstance(value, (dict, list)) else value


def cmd_login(args) -> int:
    auth = auth_from_env(TokenStore(Path(args.token_path)) if args.token_path else None)
    if not isinstance(auth, OAuth2Auth):
        print(
            "OURA_ACCESS_TOKEN is set, so there is nothing to log in to. "
            "Unset it to use the OAuth flow.",
            file=sys.stderr,
        )
        return 1
    if args.scopes:
        auth.scopes = EXTAPI_SCOPES if args.scopes == "extapi" else tuple(
            scope.strip() for scope in args.scopes.split(",") if scope.strip()
        )
    print(f"Requesting scopes: {' '.join(auth.scopes)}")
    token = auth.login(open_browser=not args.no_browser)
    print(f"Authorized. Scopes: {token.scope or '(not reported)'}")
    print(f"Token saved to {auth.store.path}")
    return 0


def cmd_logout(args) -> int:
    store = TokenStore(Path(args.token_path)) if args.token_path else TokenStore()
    store.clear()
    print(f"Cleared {store.path}")
    return 0


def cmd_verify(args) -> int:
    with OuraClient(sandbox=args.sandbox) as client:
        info = client.verify()
    print("Connected to the Oura API.")
    _print(info, as_csv=False)
    return 0


def cmd_fetch(args) -> int:
    with OuraClient(sandbox=args.sandbox) as client:
        fields = args.fields.split(",") if args.fields else None
        if args.collection == "personal_info":
            records = client.personal_info()
        elif args.collection in DATETIME_COLLECTIONS:
            records = client.datetime_range(
                args.collection, args.start, args.end, fields=fields
            )
        elif args.collection == "ring_configuration":
            records = client.ring_configuration(fields=fields)
        else:
            records = client.date_range(args.collection, args.start, args.end, fields=fields)
    _print(records, as_csv=args.csv)
    return 0


def cmd_collections(args) -> int:
    print("Date-keyed (--start/--end as YYYY-MM-DD):")
    for name in DATE_COLLECTIONS:
        print(f"  {name}")
    print("\nDatetime-keyed (--start/--end as ISO 8601 timestamps):")
    for name in DATETIME_COLLECTIONS:
        print(f"  {name}")
    print("\nNo range:")
    print("  personal_info\n  ring_configuration")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wlbc-oura", description="Oura Cloud API v2 client")
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Hit Oura's sandbox collections, which return sample data.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="Authorize with Oura via OAuth2 and store the token.")
    login.add_argument("--no-browser", action="store_true", help="Print the URL instead of opening it.")
    login.add_argument("--token-path", help="Where to store the token JSON.")
    login.add_argument(
        "--scopes",
        metavar="LIST",
        help=(
            "Override the requested scopes: a comma-separated list, or the literal "
            "'extapi' for the developer portal's extapi:-prefixed names. Try this if "
            f"login fails on an invalid scope. Default: {' '.join(ALL_SCOPES)}"
        ),
    )
    login.set_defaults(func=cmd_login)

    logout = sub.add_parser("logout", help="Delete the stored token.")
    logout.add_argument("--token-path", help="Path to the token JSON to delete.")
    logout.set_defaults(func=cmd_logout)

    verify = sub.add_parser("verify", help="Check the connection by fetching personal_info.")
    verify.set_defaults(func=cmd_verify)

    collections = sub.add_parser("collections", help="List every fetchable collection.")
    collections.set_defaults(func=cmd_collections)

    fetch = sub.add_parser("fetch", help="Fetch a collection.")
    fetch.add_argument(
        "collection",
        choices=[*DATE_COLLECTIONS, *DATETIME_COLLECTIONS, "personal_info", "ring_configuration"],
    )
    fetch.add_argument("--start", help="Start date (YYYY-MM-DD) or ISO timestamp.")
    fetch.add_argument("--end", help="End date (YYYY-MM-DD) or ISO timestamp.")
    fetch.add_argument("--days", type=int, help="Shorthand for the last N days, ending today.")
    fetch.add_argument("--fields", help="Comma-separated subset of fields to return.")
    fetch.add_argument("--csv", action="store_true", help="Emit CSV instead of JSON.")
    fetch.set_defaults(func=cmd_fetch)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    if getattr(args, "days", None):
        if args.start or args.end:
            print("--days cannot be combined with --start/--end.", file=sys.stderr)
            return 2
        today = dt.date.today()
        args.start = (today - dt.timedelta(days=args.days)).isoformat()
        args.end = today.isoformat()

    try:
        return args.func(args)
    except OuraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
