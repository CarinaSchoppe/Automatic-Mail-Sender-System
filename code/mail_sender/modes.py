"""
Definition der verschiedenen Versand-Modi (PhD, Freelance German, Freelance English).
Verwaltet die Zuordnung von Verzeichnissen und Vorlagen zu den jeweiligen Modi.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MODE_NAMES = ["PhD", "Freelance_German", "Freelance_English"]


@dataclass(frozen=True)
class MailMode:
    """
    Hält die Pfade zu Vorlagen, Anhängen und Logs für einen spezifischen Modus.
    """
    key: str
    label: str
    recipients_dir: Path
    attachments_dir: Path
    template_path: Path
    log_path: Path


def get_mode(mode: str, base_dir: Path) -> MailMode:
    """
    Gibt ein MailMode-Objekt für den angegebenen Modus-Namen zurück.

    Args:
        mode (str): Name des Modus (case-insensitive).
        base_dir (Path): Basisverzeichnis des Projekts.

    Returns:
        MailMode: Die konfigurierten Pfade für diesen Modus.
    """
    normalized = mode.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "phd":
        return MailMode(
            key="phd",
            label="PhD",
            recipients_dir=base_dir / "input" / "PhD",
            attachments_dir=base_dir / "attachments" / "PhD",
            template_path=base_dir / "templates" / "phd.txt",
            log_path=base_dir / "output" / "send_phd.csv",
        )

    if normalized == "freelance_german":
        return _freelance_mode(
            base_dir,
            template_name="freelance_german.txt",
            attachments_dir_name="Freelance_German",
            label="Freelance German",
        )

    if normalized == "freelance_english":
        return _freelance_mode(
            base_dir,
            template_name="freelance_english.txt",
            attachments_dir_name="Freelance_English",
            label="Freelance English",
        )

    raise ValueError("Unknown mode. Use PhD, Freelance_German, or Freelance_English.")


def _freelance_mode(base_dir: Path, template_name: str, attachments_dir_name: str, label: str) -> MailMode:
    """Erstellt einen der beiden Freelance-Modi mit passenden Pfaden."""
    return MailMode(
        key="freelance",
        label=label,
        recipients_dir=base_dir / "input" / attachments_dir_name,
        attachments_dir=base_dir / "attachments" / attachments_dir_name,
        template_path=base_dir / "templates" / template_name,
        log_path=base_dir / "output" / "send_freelance.csv",
    )
