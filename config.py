import os
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import quote, quote_plus, urlparse, unquote, urlunparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# Force UTF-8 to avoid mojibake when OS default is cp932/cp1252, etc.
load_dotenv(BASE_DIR / ".env", encoding="utf-8")


def _clean(value: Optional[str]) -> str:
    return (value or "").strip().lstrip("\ufeff")


def _is_placeholder(value: str) -> bool:
    return value.upper() in {"", "HOST", "USERNAME", "PASSWORD", "DBNAME", "PORT"}


def _encode_host(host: str) -> str:
    try:
        return host.encode("idna").decode("ascii")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("DB_HOST contains invalid characters; use ASCII/Punycode host names.") from exc


class Settings:
    """Application configuration loader."""

    def __init__(self) -> None:
        self.google_maps_api_key = _clean(os.getenv("GOOGLE_MAPS_API_KEY"))
        if not self.google_maps_api_key:
            raise RuntimeError("Environment variable GOOGLE_MAPS_API_KEY is not set or empty after cleanup.")

        self.map_id = _clean(os.getenv("MAP_ID"))
        if not self.map_id:
            raise RuntimeError("Environment variable MAP_ID is not set or empty after cleanup.")

        # Prefer full DATABASE_URL; otherwise build from components.
        database_url_env = _clean(os.getenv("DATABASE_URL"))
        if database_url_env:
            self.database_url = self._normalize_url(database_url_env)
        else:
            self.database_url = self._build_url_from_parts()

        parsed = urlparse(self.database_url)
        self.db_scheme = parsed.scheme
        self.db_user = unquote(parsed.username or "")
        self.db_password = unquote(parsed.password or "")
        self.db_host = parsed.hostname or ""
        self.db_port = parsed.port
        self.db_name = (parsed.path or "").lstrip("/")

        if _is_placeholder(self.db_host):
            raise RuntimeError("DATABASE_URL/DB_HOST is not set correctly (placeholder value detected).")

        # Ensure final DSN is ASCII-safe (percent/punycode encoded) to avoid psycopg2 UnicodeDecodeError
        try:
            self.database_url.encode("ascii")
        except UnicodeEncodeError as exc:  # noqa: BLE001
            raise RuntimeError("DATABASE_URL still contains non-ASCII characters after normalization.") from exc

    def _normalize_url(self, url: str) -> str:
        """Percent-encode user/password/path to avoid psycopg2 UnicodeDecodeError."""
        parsed = urlparse(url)
        if not parsed.scheme:
            raise RuntimeError("DATABASE_URL is malformed (missing scheme).")
        user = quote_plus(unquote(parsed.username or ""))
        password = quote_plus(unquote(parsed.password or ""))
        host = _encode_host(parsed.hostname or "")
        port_part = f":{parsed.port}" if parsed.port else ""
        auth = f"{user}:{password}@" if user or password else ""
        # Quote path segment (dbname), keep leading slash
        path = parsed.path or ""
        if path.startswith("/"):
            path = "/" + quote(path.lstrip("/"))
        else:
            path = quote(path)
        return urlunparse((parsed.scheme, f"{auth}{host}{port_part}", path, parsed.params, parsed.query, parsed.fragment))

    def _build_url_from_parts(self) -> str:
        user = _clean(os.getenv("DB_USER"))
        password = _clean(os.getenv("DB_PASSWORD"))
        host = _encode_host(_clean(os.getenv("DB_HOST")))
        port = _clean(os.getenv("DB_PORT"))
        name = _clean(os.getenv("DB_NAME"))
        scheme = _clean(os.getenv("DB_SCHEME") or "postgresql+psycopg2")

        missing = [k for k, v in {"DB_USER": user, "DB_PASSWORD": password, "DB_HOST": host, "DB_PORT": port, "DB_NAME": name}.items() if _is_placeholder(v)]
        if missing:
            raise RuntimeError(f"Database settings missing/placeholder: {', '.join(missing)}")

        auth = f"{quote_plus(user)}:{quote_plus(password)}"
        port_part = f":{port}" if port else ""
        path = "/" + quote(name)
        return f"{scheme}://{auth}@{host}{port_part}{path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
