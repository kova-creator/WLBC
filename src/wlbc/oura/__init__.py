"""Client for the Oura Cloud API v2."""

from .auth import ALL_SCOPES, OAuth2Auth, StaticTokenAuth, Token, TokenStore, auth_from_env
from .client import DATE_COLLECTIONS, DATETIME_COLLECTIONS, OuraClient
from .errors import (
    OuraAPIError,
    OuraAuthError,
    OuraError,
    OuraForbiddenError,
    OuraRateLimitError,
)

__all__ = [
    "ALL_SCOPES",
    "DATE_COLLECTIONS",
    "DATETIME_COLLECTIONS",
    "OAuth2Auth",
    "OuraAPIError",
    "OuraAuthError",
    "OuraClient",
    "OuraError",
    "OuraForbiddenError",
    "OuraRateLimitError",
    "StaticTokenAuth",
    "Token",
    "TokenStore",
    "auth_from_env",
]
