"""Environment-backed configuration for the Renpho client."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import RenphoConfigError


@dataclass(frozen=True)
class RenphoConfig:
    email: str
    password: str
    extra_user_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> "RenphoConfig":
        """Build a config from RENPHO_* variables, loading *env_file* first."""
        if env_file:
            load_dotenv(env_file)

        email = os.environ.get("RENPHO_EMAIL", "").strip()
        password = os.environ.get("RENPHO_PASSWORD", "")
        if not email or not password:
            raise RenphoConfigError(
                "RENPHO_EMAIL and RENPHO_PASSWORD must be set. Copy .env.example "
                "to .env and fill them in."
            )

        raw_ids = os.environ.get("RENPHO_EXTRA_USER_IDS", "")
        extra = [part.strip() for part in raw_ids.split(",") if part.strip()]
        return cls(email=email, password=password, extra_user_ids=extra)


def load_dotenv(path: str | Path = ".env") -> None:
    """Load ``KEY=value`` lines from *path* into os.environ without overriding."""
    file = Path(path)
    if not file.is_file():
        return

    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))
