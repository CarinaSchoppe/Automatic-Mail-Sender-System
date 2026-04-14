from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

load_dotenv: Callable[[], bool] | None
try:
    from dotenv import load_dotenv as _dotenv_load
    load_dotenv = _dotenv_load
except ImportError:  # pragma: no cover - optional until requirements are installed
    load_dotenv = None


class ConfigError(RuntimeError):
    """Raised when required SMTP configuration is missing."""


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    encryption: str = "ssl"


def load_smtp_config(require_password: bool) -> SmtpConfig:
    if load_dotenv is not None:
        load_dotenv()

    host = os.getenv("SMTP_HOST", "smtp.hostinger.com").strip()
    port_text = os.getenv("SMTP_PORT", "465").strip()
    encryption = os.getenv("SMTP_ENCRYPTION", "ssl").strip().lower()
    username = os.getenv("SMTP_USERNAME", "info@carinaschoppe.com").strip()
    from_email = os.getenv("SMTP_FROM_EMAIL", username).strip()
    from_name = os.getenv("SMTP_FROM_NAME", "Carina Sophie Schoppe").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()

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
    )
