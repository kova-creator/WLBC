"""Exceptions raised by the Oura client."""

from __future__ import annotations

import httpx


class OuraError(Exception):
    """Base class for every error this package raises."""


class OuraAuthError(OuraError):
    """No usable token, or the token was rejected/expired (401)."""


class OuraForbiddenError(OuraError):
    """403 — missing scope, or the user's Oura subscription has lapsed."""


class OuraRateLimitError(OuraError):
    """429 that survived the client's retry budget."""

    def __init__(self, message: str, retry_after: float | None = None, tier: str | None = None):
        super().__init__(message)
        self.retry_after = retry_after
        self.tier = tier


class OuraAPIError(OuraError):
    """Any other non-2xx response."""

    def __init__(self, message: str, status_code: int, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def raise_for_response(response: httpx.Response) -> None:
    """Translate a non-2xx response into the matching OuraError subclass."""
    if response.is_success:
        return

    body = response.text[:1000]
    status = response.status_code

    if status == 401:
        raise OuraAuthError(
            "Oura rejected the access token (401). It is expired, malformed, or revoked. "
            "Run `wlbc-oura login` to get a fresh one."
        )
    if status == 403:
        raise OuraForbiddenError(
            f"Oura returned 403. The token is missing a required scope, or the user's "
            f"Oura subscription has expired. Body: {body}"
        )
    if status == 429:
        raise OuraRateLimitError(
            f"Rate limited by Oura and out of retries. Body: {body}",
            retry_after=_retry_after_seconds(response),
            tier=response.headers.get("X-RateLimit-Tier"),
        )
    raise OuraAPIError(f"Oura API returned {status}: {body}", status_code=status, body=body)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Read Retry-After, falling back to X-RateLimit-Reset (Unix epoch seconds)."""
    raw = response.headers.get("Retry-After")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass  # RFC 7231 also permits an HTTP-date; fall through to Reset.

    reset = response.headers.get("X-RateLimit-Reset")
    if reset:
        try:
            import time

            return max(0.0, float(reset) - time.time())
        except ValueError:
            pass
    return None
