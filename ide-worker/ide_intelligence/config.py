"""Configuration for the optional IDE intelligence provider."""

from dataclasses import dataclass
import os


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"Invalid integer configuration: {name}") from error
    if not minimum <= value <= maximum:
        raise RuntimeError(f"Out-of-range configuration: {name}")
    return value


@dataclass(frozen=True)
class IdeConfig:
    enabled: bool
    protocol_version: int
    session_ttl_seconds: int
    max_code_bytes: int
    max_edits: int
    max_sessions_per_user: int
    completion_rate: int
    diagnostics_rate: int
    completion_timeout_ms: int
    definition_timeout_ms: int
    diagnostics_timeout_ms: int
    server_mode: str


def load_config() -> IdeConfig:
    mode = os.environ.get("AUTOLAB_IDE_SERVER_MODE", "disabled").strip().lower()
    if mode not in {"disabled", "host", "docker"}:
        raise RuntimeError("AUTOLAB_IDE_SERVER_MODE must be disabled, host or docker")
    return IdeConfig(
        enabled=os.environ.get("AUTOLAB_IDE_INTELLIGENCE_ENABLED", "0") == "1",
        protocol_version=_int("AUTOLAB_IDE_PROTOCOL_VERSION", 1, 1, 10),
        session_ttl_seconds=_int("AUTOLAB_IDE_SESSION_TTL_SECONDS", 900, 60, 86400),
        max_code_bytes=_int("AUTOLAB_IDE_MAX_CODE_BYTES", 262144, 1024, 1048576),
        max_edits=_int("AUTOLAB_IDE_MAX_EDITS", 64, 1, 256),
        max_sessions_per_user=_int("AUTOLAB_IDE_MAX_SESSIONS_PER_USER", 4, 1, 64),
        completion_rate=_int("AUTOLAB_IDE_COMPLETION_RATE", 5, 1, 60),
        diagnostics_rate=_int("AUTOLAB_IDE_DIAGNOSTICS_RATE", 2, 1, 30),
        completion_timeout_ms=_int("AUTOLAB_IDE_COMPLETION_TIMEOUT_MS", 800, 100, 10000),
        definition_timeout_ms=_int("AUTOLAB_IDE_DEFINITION_TIMEOUT_MS", 1000, 100, 10000),
        diagnostics_timeout_ms=_int("AUTOLAB_IDE_DIAGNOSTICS_TIMEOUT_MS", 1500, 100, 10000),
        server_mode=mode,
    )
