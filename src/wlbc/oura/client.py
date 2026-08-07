"""Synchronous client for the Oura Cloud API v2."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any, Iterator, Sequence

import httpx

from .auth import OAuth2Auth, StaticTokenAuth, auth_from_env
from .errors import OuraAuthError, OuraRateLimitError, _retry_after_seconds, raise_for_response

BASE_URL = "https://api.ouraring.com"

# Collections keyed by date (start_date / end_date).
DATE_COLLECTIONS = (
    "daily_activity",
    "daily_cardiovascular_age",
    "daily_readiness",
    "daily_resilience",
    "daily_sleep",
    "daily_spo2",
    "daily_stress",
    "enhanced_tag",
    "rest_mode_period",
    "session",
    "sleep",
    "sleep_time",
    "tag",
    "vO2_max",
    "workout",
)

# Collections keyed by timestamp (start_datetime / end_datetime).
DATETIME_COLLECTIONS = ("heartrate", "ring_battery_level")

DateLike = str | dt.date | dt.datetime


def _as_date(value: DateLike | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def _as_datetime(value: DateLike | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.astimezone()  # Oura wants an offset; assume local time.
        return value.isoformat()
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day).astimezone().isoformat()
    return str(value)


class OuraClient:
    """Talks to the Oura v2 API, handling pagination, retries, and token refresh.

    Usable as a context manager so the underlying HTTP connection pool is closed:

        with OuraClient() as oura:
            print(oura.personal_info())
    """

    def __init__(
        self,
        auth: OAuth2Auth | StaticTokenAuth | None = None,
        *,
        base_url: str = BASE_URL,
        sandbox: bool = False,
        timeout: float = 30.0,
        max_retries: int = 4,
        max_retry_wait: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.auth = auth or auth_from_env()
        self.sandbox = sandbox
        self.max_retries = max_retries
        self.max_retry_wait = max_retry_wait
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OuraClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- transport -------------------------------------------------------

    def _prefix(self) -> str:
        return "/v2/sandbox/usercollection" if self.sandbox else "/v2/usercollection"

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """GET with retry on 429/5xx and one token refresh on 401."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        refreshed = False

        for attempt in range(self.max_retries + 1):
            headers = {"Authorization": f"Bearer {self.auth.access_token()}"}
            try:
                response = self._http.get(path, params=params, headers=headers)
            except httpx.TransportError:
                if attempt == self.max_retries:
                    raise
                time.sleep(self._backoff(attempt))
                continue

            if response.status_code == 401 and not refreshed and self.auth.refresh():
                refreshed = True
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.max_retries:
                    raise_for_response(response)
                wait = _retry_after_seconds(response) if response.status_code == 429 else None
                time.sleep(min(wait if wait is not None else self._backoff(attempt),
                               self.max_retry_wait))
                continue

            raise_for_response(response)
            return response.json()

        # Unreachable: the final attempt either returns or raises above.
        raise OuraRateLimitError("Exhausted retries without a definitive response.")

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2.0**attempt, 30.0)

    # -- pagination ------------------------------------------------------

    def iter_documents(
        self,
        collection: str,
        params: dict[str, Any] | None = None,
    ) -> Iterator[dict]:
        """Yield every document in a collection, following next_token to the end."""
        path = f"{self._prefix()}/{collection}"
        page_params = dict(params or {})
        while True:
            payload = self._request(path, page_params)
            yield from payload.get("data", [])
            next_token = payload.get("next_token")
            if not next_token:
                return
            page_params["next_token"] = next_token

    def get_documents(
        self,
        collection: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Eagerly collect every page of a collection into a list."""
        return list(self.iter_documents(collection, params))

    def get_document(self, collection: str, document_id: str) -> dict:
        """Fetch a single document by its id."""
        return self._request(f"{self._prefix()}/{collection}/{document_id}")

    # -- typed entry points ----------------------------------------------

    def personal_info(self) -> dict:
        """Age, weight, height, biological sex, email."""
        return self._request(f"{self._prefix()}/personal_info")

    def ring_configuration(self, fields: Sequence[str] | None = None) -> list[dict]:
        return self.get_documents(
            "ring_configuration", {"fields": ",".join(fields) if fields else None}
        )

    def date_range(
        self,
        collection: str,
        start_date: DateLike | None = None,
        end_date: DateLike | None = None,
        fields: Sequence[str] | None = None,
    ) -> list[dict]:
        """Fetch a date-keyed collection (e.g. daily_sleep, workout, tag).

        Oura defaults to roughly the last day when the range is omitted.
        """
        if collection not in DATE_COLLECTIONS:
            raise ValueError(
                f"{collection!r} is not a date-keyed collection. "
                f"Valid: {', '.join(DATE_COLLECTIONS)}"
            )
        return self.get_documents(
            collection,
            {
                "start_date": _as_date(start_date),
                "end_date": _as_date(end_date),
                "fields": ",".join(fields) if fields else None,
            },
        )

    def datetime_range(
        self,
        collection: str,
        start_datetime: DateLike | None = None,
        end_datetime: DateLike | None = None,
        fields: Sequence[str] | None = None,
    ) -> list[dict]:
        """Fetch a timestamp-keyed collection (heartrate, ring_battery_level)."""
        if collection not in DATETIME_COLLECTIONS:
            raise ValueError(
                f"{collection!r} is not a datetime-keyed collection. "
                f"Valid: {', '.join(DATETIME_COLLECTIONS)}"
            )
        return self.get_documents(
            collection,
            {
                "start_datetime": _as_datetime(start_datetime),
                "end_datetime": _as_datetime(end_datetime),
                "fields": ",".join(fields) if fields else None,
            },
        )

    def heartrate(
        self,
        start_datetime: DateLike | None = None,
        end_datetime: DateLike | None = None,
    ) -> list[dict]:
        return self.datetime_range("heartrate", start_datetime, end_datetime)

    def verify(self) -> dict:
        """Confirm the token works. Raises OuraAuthError if it does not."""
        info = self.personal_info()
        if not isinstance(info, dict):
            raise OuraAuthError(f"Unexpected personal_info response: {info!r}")
        return info


def _make_date_method(collection: str):
    def method(
        self: OuraClient,
        start_date: DateLike | None = None,
        end_date: DateLike | None = None,
        fields: Sequence[str] | None = None,
    ) -> list[dict]:
        return self.date_range(collection, start_date, end_date, fields)

    method.__name__ = collection
    method.__doc__ = f"Fetch the {collection} collection over a date range."
    return method


# daily_sleep(), workout(), tag(), ... as first-class methods, so callers get
# autocomplete without hand-writing fifteen identical wrappers.
for _collection in DATE_COLLECTIONS:
    setattr(OuraClient, _collection, _make_date_method(_collection))

OuraClient.ring_battery_level = lambda self, start_datetime=None, end_datetime=None: (
    self.datetime_range("ring_battery_level", start_datetime, end_datetime)
)
