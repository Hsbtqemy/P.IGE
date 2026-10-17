"""Server settings, read from environment variables.

On the VPS these live in a root-only EnvironmentFile loaded by systemd
(see ``deploy/``); nothing secret is ever written to the data directory.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    password_hash: str
    session_secret: str
    api_token_hashes: frozenset[str]
    web_dir: Path | None = None
    cookie_secure: bool = True
    session_days: int = 30
    sessions_not_before: int = 0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)

        def required(name: str) -> str:
            value = env.get(name, "").strip()
            if not value:
                raise ConfigError(f"Missing environment variable {name}")
            return value

        tokens = frozenset(
            item.strip().lower()
            for item in env.get("PIGE_API_TOKEN_HASHES", "").split(",")
            if item.strip()
        )
        for token_hash in tokens:
            if not re.fullmatch(r"[0-9a-f]{64}", token_hash):
                raise ConfigError("PIGE_API_TOKEN_HASHES must hold sha256 hex digests")
        web_dir = env.get("PIGE_WEB_DIR", "").strip()
        return cls(
            data_dir=Path(required("PIGE_DATA_DIR")).expanduser(),
            password_hash=required("PIGE_PASSWORD_HASH"),
            session_secret=required("PIGE_SESSION_SECRET"),
            api_token_hashes=tokens,
            web_dir=Path(web_dir).expanduser() if web_dir else None,
            cookie_secure=env.get("PIGE_COOKIE_SECURE", "1").strip() not in ("0", "false", "no"),
            session_days=int(env.get("PIGE_SESSION_DAYS", "30")),
            sessions_not_before=int(env.get("PIGE_SESSIONS_NOT_BEFORE", "0")),
        )
