"""
Verwaltet das Laden und Validieren der SMTP-Konfiguration.
Kombiniert Werte aus Umgebungsvariablen (.env) und der settings.toml Datei.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

load_dotenv: Callable[..., Any]
try:
    from dotenv import load_dotenv as _dotenv_load

    load_dotenv = _dotenv_load
except ImportError:  # pragma: no cover
    def _dotenv_load_stub():
        """Ersetzt python-dotenv, wenn das Paket in einer Minimalumgebung fehlt."""
        return False


    load_dotenv = _dotenv_load_stub

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "settings.toml"


class ConfigError(RuntimeError):
    """
    Wird ausgelöst, wenn erforderliche SMTP-Einstellungen fehlen oder ungültig sind.
    """


@dataclass(frozen=True)
class SmtpConfig:
    """
    Datentransferobjekt für SMTP-Verbindungsdaten.
    """
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    encryption: str = "ssl"


def _load_settings() -> dict:
    """
    Lädt die Einstellungen aus der settings.toml.
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
    Lädt die vollständige SMTP-Konfiguration und prüft auf Vollständigkeit.

    Args:
        require_password (bool): Ob das Passwort zwingend vorhanden sein muss
                                 (wird bei Dry-Runs oft nicht benötigt).

    Returns:
        SmtpConfig: Die validierte Konfiguration.
    """
    if load_dotenv is not None:
        load_dotenv()

    settings = _load_settings()

    def _get(key: str, default: str) -> str:
        # 1. OS Env
        # 2. settings.toml
        # 3. default
        """Ermittelt die benoetigten Werte."""
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
