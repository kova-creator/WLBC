"""Thin wrapper around the unofficial ``renpho-api`` client.

The upstream package (https://pypi.org/project/renpho-api/) does the actual
protocol work — encrypted login, sharded measurement tables, pagination. This
wrapper adds the bits the rest of wlbc expects: config from the environment,
lazy login, and our own exception types.
"""

from __future__ import annotations

from typing import Any

from renpho import RenphoClient as _RenphoClient

from .config import RenphoConfig
from .errors import translated


class RenphoConnection:
    """A logged-in Renpho session.

    Usage::

        with RenphoConnection.from_env() as renpho:
            for m in renpho.measurements():
                print(m["created_at"], m["weight"])
    """

    def __init__(self, config: RenphoConfig, *, debug: bool = False):
        self.config = config
        self._client = _RenphoClient(config.email, config.password, debug=debug)
        self._account: dict[str, Any] | None = None

    @classmethod
    def from_env(cls, *, debug: bool = False) -> "RenphoConnection":
        return cls(RenphoConfig.from_env(), debug=debug)

    def __enter__(self) -> "RenphoConnection":
        self.login()
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    @property
    def user_id(self) -> int | str | None:
        return self._client.user_id

    def login(self) -> dict[str, Any]:
        """Authenticate, or return the cached account info if already logged in."""
        if self._account is None:
            with translated("login"):
                self._account = self._client.login()
        return self._account

    @property
    def email(self) -> str | None:
        """The account email, once logged in."""
        account = self.login()
        return (account.get("login") or {}).get("email")

    def measurement_tables(self) -> list[dict[str, Any]]:
        """The sharded tables holding this account's data.

        Renpho reports storage shards here rather than physical devices; each
        entry carries a ``tableName``, a record ``count``, and the ``userIds``
        it covers.
        """
        self.login()
        with translated("device info"):
            info = self._client.get_device_info()
        return info.get("scale", []) or []

    def measurements(self) -> list[dict[str, Any]]:
        """Every body-composition measurement, oldest first.

        Includes any accounts listed in ``RENPHO_EXTRA_USER_IDS`` — some users
        end up with several Renpho user ids behind one email address.
        """
        self.login()
        with translated("measurements"):
            data = self._client.get_all_measurements(
                extra_user_ids=self.config.extra_user_ids or None
            )
        return sorted(data, key=_timestamp)

    def girth_measurements(self) -> list[dict[str, Any]]:
        """Smart-tape circumference records, oldest first."""
        self.login()
        with translated("girth measurements"):
            data = self._client.get_girth_measurements()
        return sorted(data, key=_timestamp)


def _timestamp(measurement: dict[str, Any]) -> int:
    """Sort key — Renpho returns the epoch under either spelling."""
    return int(measurement.get("timeStamp") or measurement.get("time_stamp") or 0)
