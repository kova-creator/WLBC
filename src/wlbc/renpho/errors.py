"""Exceptions raised by the Renpho client."""

from __future__ import annotations

from contextlib import contextmanager

from renpho import RenphoAPIError as _UpstreamError


class RenphoError(Exception):
    """Base class for every error this package raises."""


class RenphoConfigError(RenphoError):
    """Credentials are missing from the environment."""


class RenphoAuthError(RenphoError):
    """Renpho rejected the email/password pair."""


class RenphoAPIError(RenphoError):
    """Any other API-level failure reported by the upstream client."""

    def __init__(self, message: str, code: object = None):
        super().__init__(message)
        self.code = code


@contextmanager
def translated(context: str):
    """Re-raise upstream ``renpho.RenphoAPIError`` as our own error types.

    The upstream client signals everything — bad password included — with a
    single exception type, so authentication is detected from the context.
    """
    try:
        yield
    except _UpstreamError as exc:
        message = f"{context}: {exc}"
        if context == "login":
            raise RenphoAuthError(
                f"{message}. Check RENPHO_EMAIL and RENPHO_PASSWORD in .env."
            ) from exc
        raise RenphoAPIError(message, code=getattr(exc, "code", None)) from exc
