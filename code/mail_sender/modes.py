"""Definition and path resolution for built-in and user-defined mailing modes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

try:
    from mail_sender.prompts import load_prompts
except ImportError:
    load_prompts = None

MODE_NAMES = ["PhD", "Freelance_German", "Freelance_English"]
_BUILT_IN_MODE_LABELS = {
    "phd": "PhD",
    "freelance_german": "Freelance German",
    "freelance_english": "Freelance English",
}


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
    spam_safe_template_path: Path
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
    normalized = mode_name_key(mode)
    if normalized == "phd":
        return MailMode(
            key="phd",
            label="PhD",
            recipients_dir=base_dir / "input" / "PhD",
            attachments_dir=base_dir / "attachments" / "PhD",
            template_path=base_dir / "templates" / "phd.txt",
            spam_safe_template_path=base_dir / "templates" / "phd_spam_safe.txt",
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

    label = mode_label_from_name(mode)
    return MailMode(
        key=normalized,
        label=label,
        recipients_dir=base_dir / "input" / mode_name_from_label(label),
        attachments_dir=base_dir / "attachments" / mode_name_from_label(label),
        template_path=base_dir / "templates" / f"{mode_template_slug(label)}.txt",
        spam_safe_template_path=base_dir / "templates" / f"{mode_template_slug(label)}_spam_safe.txt",
        log_path=base_dir / "output" / f"send_{mode_template_slug(label)}.csv",
    )


def _freelance_mode(base_dir: Path, template_name: str, attachments_dir_name: str, label: str) -> MailMode:
    """Creates one of the two freelance modes with appropriate paths."""
    return MailMode(
        key="freelance",
        label=label,
        recipients_dir=base_dir / "input" / attachments_dir_name,
        attachments_dir=base_dir / "attachments" / attachments_dir_name,
        template_path=base_dir / "templates" / template_name,
        spam_safe_template_path=base_dir / "templates" / template_name.replace(".txt", "_spam_safe.txt"),
        log_path=base_dir / "output" / "send_freelance.csv",
    )


def mode_name_key(value: str) -> str:
    """Normalizes a user-facing mode value for comparisons."""
    normalized = re.sub(r"[^\w]+", "_", value.strip(), flags=re.UNICODE).strip("_")
    return normalized.lower()


def mode_name_from_label(label: str) -> str:
    """Returns the settings/input-folder mode name for a display label."""
    normalized = re.sub(r"[^\w]+", "_", label.strip(), flags=re.UNICODE).strip("_")
    if not normalized:
        raise ValueError("Mode name cannot be empty.")
    key = normalized.lower()
    if key == "phd":
        return "PhD"
    if key == "freelance_german":
        return "Freelance_German"
    if key == "freelance_english":
        return "Freelance_English"
    return normalized


def mode_label_from_name(mode_name: str) -> str:
    """Returns the prompt/display label for a settings mode name."""
    key = mode_name_key(mode_name)
    if key in _BUILT_IN_MODE_LABELS:
        return _BUILT_IN_MODE_LABELS[key]
    return re.sub(r"\s+", " ", mode_name.strip().replace("_", " ")).strip()


def mode_template_slug(label_or_mode: str) -> str:
    """Returns the template/log filename slug for a mode label or mode name."""
    return mode_name_key(label_or_mode)


def get_available_mode_names(base_dir: Path | None = None) -> list[str]:
    """Returns built-in mode names plus user-defined task names from prompts.toml."""
    mode_names = list(MODE_NAMES)
    prompts_path = (base_dir / "prompts.toml") if base_dir is not None else None
    prompts = {}
    if load_prompts is not None:
        prompts = load_prompts(prompts_path) if prompts_path is not None else load_prompts()

    seen = {mode_name_key(name) for name in mode_names}
    for label in prompts:
        if label == "Overseer":
            continue
        mode_name = mode_name_from_label(label)
        key = mode_name_key(mode_name)
        if key not in seen:
            mode_names.append(mode_name)
            seen.add(key)
    return mode_names
