# WLBC

Body composition over time, built from two sources:

- **Renpho** smart scale — weight, body fat, lean mass ([`wlbc.renpho`](src/wlbc/renpho))
- **Oura** ring — daily sleep, readiness, activity ([`wlbc.oura`](src/wlbc/oura))

[`wlbc.combined`](src/wlbc/combined) joins them on the calendar day and renders a
self-contained HTML report.

```bash
wlbc report --days 90 --open
```

Three commands, one per layer:

| Command | What it does |
|---|---|
| `wlbc` | the combined view — `summary`, `merge`, `report` |
| `wlbc-oura` | Oura only — `login`, `verify`, `fetch`, `collections` |
| `wlbc-renpho` | Renpho only — print recent measurements, export history |

## The combined tool

```bash
wlbc summary --days 90                    # headline numbers
wlbc report --days 90 -o report.html      # HTML report with charts
wlbc merge --days 90 --csv merged.csv     # one row per day, both sources
wlbc merge --days 30 --only-measured      # drop days with no weigh-in
```

Global options apply to every subcommand: `--days` / `--start` / `--end`,
`--units kg|lb`, `--window` (trend window, default 7 days), `--pick` (which
weigh-in to use when a day has several), `--body-start`, `--no-oura` /
`--no-renpho`.

### Different ranges per source

`--body-start` ignores Renpho weigh-ins before a date without shortening Oura's
range — for when older scale readings aren't yours or aren't trustworthy. Oura
still covers the full span; the body-composition charts begin where the good
readings do, and the report header says so.

```bash
wlbc --start 2026-04-03 --body-start 2026-08-05 report -o report.html
```

### It adapts to how much data you have

The report changes shape rather than implying precision the data doesn't
support:

| Weigh-ins | What you get |
|---|---|
| 0 | "No Renpho measurements in this range" |
| 1 | Weight and body fat as a point. No change, rate, or fat/lean split — one reading is a starting point, not a trajectory. |
| Sparse (< ~1 per 3 days) | The actual readings, connected. A trailing mean here would hold each reading flat for a week and then step, which reads as stability that never happened. |
| Dense | Dots plus the trailing mean, and the full fat/lean split. |

### What the report shows

- **Stat tiles** — current trend weight, change over the range, rate in kg/week
  (least-squares over every weigh-in), body fat, and how the change split between
  fat and lean mass.
- **Weight** — every weigh-in as a dot with the trailing mean over it. Scale weight
  swings on water and food; the line is the part worth reading.
- **Where the change came from** — fat mass and lean mass indexed to zero at the
  start of the range. Raw, they sit tens of kilos apart and both flatten into
  straight lines; indexed, the gap between them *is* the split of your weight change.
- **Body fat %** — moves when fat and lean mass move differently.
- **Oura context** — sleep score, resting HR, and steps as separate panels, each
  with its own axis.
- **Table view** — every value, reachable without relying on color.

The report is one HTML file with no external assets, so it works offline and
follows your system light/dark theme.

### As a library

```python
import datetime as dt
from wlbc.combined import collect, summarize, build_report

end = dt.date.today()
records = collect(end - dt.timedelta(days=90), end)   # fetches both sources
summary = summarize(records)

print(summary.change_kg, summary.kg_per_week)
for record in records:
    if record.has_body_comp:
        print(record.day, record.weight_kg, record.trend["weight_kg"], record.sleep_score)

open("report.html", "w").write(build_report(records, summary))
```

`collect()` returns one `DailyRecord` per calendar day across the range, including
days where neither source has anything — a two-week gap between weigh-ins reads as
a two-week gap rather than a single step. `record.trend` holds trailing means and
`record.delta` holds change-since-baseline.

### How the join works

The two APIs share exactly one key: the local calendar date. Renpho stamps an
epoch per weigh-in; Oura already summarizes per `day`.

- Renpho's `localCreatedAt` is preferred over the epoch, so a late-evening
  weigh-in doesn't drift into the next day through a timezone conversion.
- Multiple weigh-ins on one day collapse via `--pick` (default `first`, normally
  the fasted morning reading and the most comparable day to day).
- Renpho reports unmeasured metrics as `0`, not null; those become `None` rather
  than a real zero.
- Trend windows are measured in **calendar days**, not rows, so a gap in weigh-ins
  widens the window instead of silently reaching further back through time.
- The fetch warms up one window before the requested start, so day one of the
  chart has a real trend rather than a lone reading.

## Setup

### Installing

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in what you have — either source can be
skipped with `--no-oura` / `--no-renpho`.

### Connecting Renpho

Set `RENPHO_EMAIL` and `RENPHO_PASSWORD` to your normal Renpho app login. If your
account has several user ids behind one email, list the extras in
`RENPHO_EXTRA_USER_IDS` and they get merged in.

This goes through the unofficial `renpho-api` package — not a documented API, so
it can break whenever Renpho changes their app protocol.

### Connecting Oura

**Oura deprecated personal access tokens in December 2025.** The API spec states they
are "no longer available for use," so OAuth2 authorization code is the only way to get
a working token. This client supports both:

- **OAuth2** (`OAuth2Auth`) — register an app, run `wlbc-oura login`, tokens refresh automatically.
- **A bearer token you already hold** (`StaticTokenAuth`) — set `OURA_ACCESS_TOKEN`. No refresh;
  a 401 is terminal.

Register an application at <https://cloud.ouraring.com/oauth/applications>, set its
redirect URI to `http://localhost:8765/callback`, then fill in `OURA_CLIENT_ID` and
`OURA_CLIENT_SECRET` in `.env` and authorize:

```bash
.venv/bin/wlbc-oura login
```

That opens a browser, captures the callback on localhost, and writes the token to
`~/.config/wlbc/oura_token.json` with `0600` permissions. Confirm it worked:

```bash
.venv/bin/wlbc-oura verify
```

### Try it without credentials

Oura's sandbox returns sample data, so you can exercise the whole client before you
have an app registered:

```bash
.venv/bin/wlbc-oura --sandbox fetch daily_sleep --days 7
```

## Oura client

### CLI

```bash
.venv/bin/wlbc-oura collections                                    # list every collection
.venv/bin/wlbc-oura fetch daily_readiness --days 30                # last 30 days as JSON
.venv/bin/wlbc-oura fetch workout --start 2026-07-01 --end 2026-08-01 --csv
.venv/bin/wlbc-oura fetch daily_activity --days 7 --fields day,score,steps
.venv/bin/wlbc-oura fetch heartrate --start 2026-08-05T00:00:00-07:00 --end 2026-08-05T06:00:00-07:00
.venv/bin/wlbc-oura logout                                         # delete the stored token
```

`--csv` flattens nested objects to JSON strings so the output stays one row per document.

### Library

```python
import datetime as dt
from wlbc.oura import OuraClient

with OuraClient() as oura:
    print(oura.personal_info())

    week = oura.daily_sleep(dt.date.today() - dt.timedelta(days=7), dt.date.today())
    for day in week:
        print(day["day"], day["score"])

    # Stream instead of buffering, for long ranges of high-frequency data.
    for sample in oura.iter_documents("heartrate", {"start_datetime": "2026-08-01T00:00:00-07:00"}):
        print(sample["bpm"])
```

Every date-keyed collection is a method: `daily_activity`, `daily_cardiovascular_age`,
`daily_readiness`, `daily_resilience`, `daily_sleep`, `daily_spo2`, `daily_stress`,
`enhanced_tag`, `rest_mode_period`, `session`, `sleep`, `sleep_time`, `tag`, `vO2_max`,
`workout`. Each takes `(start_date, end_date, fields)`.

`heartrate` and `ring_battery_level` are timestamp-keyed and take
`(start_datetime, end_datetime)`.

### What the Oura client handles for you

- **Pagination** — follows `next_token` to the end of the collection.
- **Rate limits** — retries 429s honoring `Retry-After`, falling back to `X-RateLimit-Reset`,
  then exponential backoff. Raises `OuraRateLimitError` with the `X-RateLimit-Tier` when
  the retry budget runs out.
- **Token refresh** — one automatic refresh-and-retry on a 401.
- **Typed errors** — `OuraAuthError` (401), `OuraForbiddenError` (403, usually a missing
  scope or a lapsed Oura subscription), `OuraRateLimitError` (429), `OuraAPIError` (everything else).

Oura recommends [webhooks](https://cloud.ouraring.com/v2/docs#tag/Webhook-Subscription-Routes)
over polling for ongoing updates: one historical backfill when a user connects, then
webhooks after. This client covers the read endpoints only; webhook subscriptions are not
implemented.

## Tests

```bash
.venv/bin/python -m pytest
```

Tests use `httpx.MockTransport`, so nothing hits the network.
