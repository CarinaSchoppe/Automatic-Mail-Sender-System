"""
Definition of the various mailing modes (PhD, Freelance German, Freelance English).
Manages the assignment of directories and templates to the respective modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MODE_NAMES = ["PhD", "Freelance_German", "Freelance_English"]


@dataclass(frozen=True)
class MailMode:
    """
    Holds the paths to templates, attachments, and logs for a specific mode.
    """
    key: str
    label: str
    recipients_dir: Path
    attachments_dir: Path
    template_path: Path
    log_path: Path


def get_mode(mode: str, base_dir: Path) -> MailMode:
    """
    Returns a MailMode object for the specified mode name.

    Args:
        mode (str): Name of the mode (case-insensitive).
        base_dir (Path): Base directory of the project.

    Returns:
        MailMode: The configured paths for this mode.
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
    """Creates one of the two freelance modes with appropriate paths."""
    return MailMode(
        key="freelance",
        label=label,
        recipients_dir=base_dir / "input" / attachments_dir_name,
        attachments_dir=base_dir / "attachments" / attachments_dir_name,
        template_path=base_dir / "templates" / template_name,
        log_path=base_dir / "output" / "send_freelance.csv",
    )
