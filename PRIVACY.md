# Privacy Policy

_Last updated: 6 August 2026_

WLBC is a personal, self-hosted tool. It runs on the machine of the person who
installs it, and it is operated by that same person for their own data. There is
no hosted service, no server operated by the author, and no other users.

## What data is accessed

When you connect your accounts, WLBC reads:

- **From Oura** (via the Oura Cloud API v2, with your authorization): daily sleep,
  readiness, and activity summaries, sleep periods, heart rate, and the other
  collections covered by the scopes you grant.
- **From Renpho** (via your normal account login): body-composition measurements
  from your scale, and circumference records from a smart tape measure if you use one.

## Where it goes

Nowhere. All processing happens locally on your own machine.

- Data fetched from either service is held in memory for the duration of a command,
  and written to disk only to files you explicitly ask for (`--csv`, `--json`,
  `-o report.html`).
- The generated HTML report is a single self-contained file with no external
  assets and no network calls. Opening it transmits nothing.
- No analytics, telemetry, tracking, or crash reporting of any kind.
- Nothing is transmitted to the author of this software, who has no access to your
  data and no ability to obtain it.

The only network requests WLBC makes are to Oura's API and Renpho's API, to fetch
your own data on your behalf.

## Credentials

- Your Oura OAuth token is stored at `~/.config/wlbc/oura_token.json` with
  `0600` permissions (readable only by your user account).
- Your Renpho login is read from environment variables or a local `.env` file,
  which is excluded from version control.
- Credentials are sent only to the service they belong to, over HTTPS.

## Deleting your data

Delete the files. `wlbc-oura logout` removes the stored Oura token; you can also
revoke WLBC's access from the [Oura developer portal](https://developer.ouraring.com)
at any time. Any CSV, JSON, or HTML files are yours to delete.

## Contact

kova@patton.blue
