"""
Manages loading and validation of the SMTP configuration.
Combines values from environment variables (.env) and the settings.toml file.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

load_dotenv: Callable[..., Any]
try:
    from dotenv import load_dotenv

except ImportError:  # pragma: no cover
    def _dotenv_load_stub():
        """Replaces python-dotenv if the package is missing in a minimal environment."""
        return False


    load_dotenv = _dotenv_load_stub

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "settings.toml"


class ConfigError(RuntimeError):
    """
    Raised when required SMTP settings are missing or invalid.
    """


@dataclass(frozen=True)
class SmtpConfig:
    """
    Data transfer object for SMTP connection data.
    """
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    encryption: str = "ssl"
    external_validation_service: str = "none"
    external_validation_api_key: str = ""


def _load_settings() -> dict:
    """
    Loads settings from settings.toml.
    """
    if not SETTINGS_PATH.exists():
        return {}
    try:
        with SETTINGS_PATH.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def load_smtp_config(require_password: bool) -> SmtpConfig:
    """
    Loads the complete SMTP configuration and checks for completeness.

    Args:
        require_password (bool): Whether the password must be present
                                 (often not needed for dry-runs).

    Returns:
        SmtpConfig: The validated configuration.
    """
    if load_dotenv is not None:
        env_path = PROJECT_ROOT / ".env"
        load_dotenv(dotenv_path=env_path)

    settings = _load_settings()

    def _get(key: str, default: str) -> str:
        # 1. OS Env
        # 2. settings.toml
        # 3. default
        """Retrieves the required values."""
        val = os.getenv(key)
        if val is not None:
            return val.strip()
        toml_val = settings.get(key)
        if toml_val is not None:
            return str(toml_val).strip()
        return default

    host = _get("SMTP_HOST", "smtp.hostinger.com")
    port_text = _get("SMTP_PORT", "465")
    encryption = _get("SMTP_ENCRYPTION", "ssl").lower()
    username = _get("SMTP_USERNAME", "info@carinaschoppe.com")
    from_email = _get("SMTP_FROM_EMAIL", username)
    from_name = _get("SMTP_FROM_NAME", "Carina Sophie Schoppe")
    password = os.getenv("SMTP_PASSWORD", "").strip()

    external_validation_service = _get("EXTERNAL_VALIDATION_SERVICE", "none").lower()
    external_validation_api_key = os.getenv("EXTERNAL_VALIDATION_API_KEY", _get("EXTERNAL_VALIDATION_API_KEY", "")).strip()

    if encryption != "ssl":
        raise ConfigError("Only SSL/SMTPS is supported right now. Set SMTP_ENCRYPTION=ssl.")

    try:
        port = int(port_text)
    except ValueError as exc:
        raise ConfigError("SMTP_PORT must be a number.") from exc

    missing = []
    if not host:
        missing.append("SMTP_HOST")
    if not username:
        missing.append("SMTP_USERNAME")
    if not from_email:
        missing.append("SMTP_FROM_EMAIL")
    if require_password and not password:
        missing.append("SMTP_PASSWORD")

    if missing:
        joined = ", ".join(missing)
        raise ConfigError(f"Missing SMTP configuration: {joined}.")

    return SmtpConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        from_email=from_email,
        from_name=from_name,
        encryption=encryption,
        external_validation_service=external_validation_service,
        external_validation_api_key=external_validation_api_key,
    )
