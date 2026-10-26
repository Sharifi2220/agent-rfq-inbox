"""Configuration file handling (TOML) and service construction."""

from __future__ import annotations

import os
import secrets
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .profile import Profile
from .service import Limits, QuoteService
from .store import Store

DEFAULT_CONFIG = """\
# OpenQuote Lite configuration
[instance]
# Public base URL under which agents reach this endpoint (behind your TLS reverse proxy).
base_url = "{base_url}"
# Provider profile: the single source of truth for services, area and policy.
profile = '{profile}'
# Local directory for the SQLite database and the instance secret. Keep it on a local disk.
data_dir = "data"

[http]
host = "127.0.0.1"
port = 8787
# Set to true only behind a reverse proxy that appends the client address to X-Forwarded-For.
trust_proxy = false

[limits]
per_client_per_hour = 10
per_contact_per_day = 5
global_per_day = 200
status_per_client_per_hour = 60
duplicate_window_hours = 24
idempotency_days = 7
max_body_bytes = 32768

[privacy]
# Requests older than this are deleted by `openquote-lite privacy purge`.
retention_days = 180
"""


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    path: Path
    base_url: str
    profile_path: Path
    data_dir: Path
    host: str
    port: int
    trust_proxy: bool
    limits: Limits
    retention_days: int

    @property
    def database_path(self) -> Path:
        return self.data_dir / "openquote.sqlite3"

    @property
    def secret_path(self) -> Path:
        return self.data_dir / "instance.secret"


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_config(path: str | Path) -> Config:
    path = Path(path).expanduser().resolve()
    try:
        data = tomllib.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path} (create one with `openquote-lite init`)") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from None
    instance = data.get("instance", {})
    http = data.get("http", {})
    limits = data.get("limits", {})
    privacy = data.get("privacy", {})
    base_url = str(instance.get("base_url", "")).rstrip("/")
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        port = parsed.port  # access also rejects invalid port numbers
    except ValueError:
        raise ConfigError("instance.base_url is not a valid URL") from None
    if (
        not hostname or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or parsed.path not in ("", "/")
        or parsed.scheme not in ("https", "http")
        or (parsed.scheme == "http" and hostname not in ("localhost", "127.0.0.1", "::1"))
    ):
        raise ConfigError("instance.base_url must be an https:// origin (http:// only for exact loopback hosts)")
    if parsed.path == "/":
        base_url = base_url[:-1]
    if "profile" not in instance:
        raise ConfigError("instance.profile is required")
    known_limits = set(Limits.__dataclass_fields__)
    unknown = set(limits) - known_limits
    if unknown:
        raise ConfigError(f"unknown [limits] keys: {', '.join(sorted(unknown))}")
    try:
        limit_values = {key: int(value) for key, value in limits.items()}
    except (TypeError, ValueError):
        raise ConfigError("[limits] values must be integers") from None
    if any(value < 1 for value in limit_values.values()):
        raise ConfigError("[limits] values must be >= 1")
    proxy_value = http.get("trust_proxy", False)
    if not isinstance(proxy_value, bool):
        raise ConfigError("http.trust_proxy must be a TOML boolean (true or false)")
    retention_days = int(privacy.get("retention_days", 180))
    if retention_days < 1:
        raise ConfigError("privacy.retention_days must be >= 1")
    return Config(
        path=path,
        base_url=base_url,
        profile_path=_resolve(path.parent, instance["profile"]),
        data_dir=_resolve(path.parent, instance.get("data_dir", "data")),
        host=str(http.get("host", "127.0.0.1")),
        port=int(http.get("port", 8787)),
        trust_proxy=proxy_value,
        limits=Limits(**limit_values),
        retention_days=retention_days,
    )


def ensure_secret(path: Path) -> bytes:
    """Create (once) and read the per-instance secret used for pseudonymous hashes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(secrets.token_hex(32))
    value = path.read_text("ascii").strip()
    if len(value) < 32:
        raise ConfigError(f"instance secret in {path} is too short")
    return value.encode("ascii")


def build_service(config: Config) -> QuoteService:
    profile = Profile.from_file(config.profile_path)
    store = Store(config.database_path)
    secret = ensure_secret(config.secret_path)
    return QuoteService(
        store,
        profile,
        secret,
        base_url=config.base_url,
        limits=config.limits,
        retention_days=config.retention_days,
    )


def write_default_config(target_dir: Path, *, base_url: str, profile: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "openquote.toml"
    if path.exists():
        raise ConfigError(f"{path} already exists; not overwriting")
    if "'" in profile or '"' in base_url or "\\" in base_url:
        raise ConfigError("profile path must not contain ' and base_url must not contain quotes or backslashes")
    # TOML literal string for the path, so Windows backslashes need no escaping.
    path.write_text(DEFAULT_CONFIG.format(base_url=base_url, profile=profile), "utf-8")
    return path
