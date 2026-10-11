from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

PORTAL_ORIGIN = "https://web-jongmok-portal-8d0218f4.azurewebsites.net"


@dataclass(frozen=True)
class BackendSettings:
    api_key: str = field(repr=False)
    cors_origins: tuple[str, ...] = (PORTAL_ORIGIN,)

    @classmethod
    def from_env(cls) -> BackendSettings:
        key = os.environ.get("BACKEND_API_KEY", "")
        if len(key) < 32:
            raise ValueError("BACKEND_API_KEY must contain at least 32 characters")
        origins = tuple(
            value.strip()
            for value in os.environ.get("BACKEND_CORS_ORIGINS", PORTAL_ORIGIN).split(",")
            if value.strip()
        )
        if not origins:
            raise ValueError("BACKEND_CORS_ORIGINS must not be empty")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or "*" in origin
            ):
                raise ValueError("CORS origins must be exact HTTP(S) origins without paths")
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
                raise ValueError("Non-local CORS origins must use HTTPS")
        return cls(api_key=key, cors_origins=origins)
