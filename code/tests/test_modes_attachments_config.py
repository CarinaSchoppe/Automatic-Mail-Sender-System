"""Tests und Hilfen fuer tests/test_modes_attachments_config.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from mail_sender.attachments import list_attachments
from mail_sender.config import ConfigError, load_smtp_config
from mail_sender.modes import get_mode, mode_label_from_name, mode_name_from_label


def test_modes_point_to_input_attachments_and_output(project: Path) -> None:
    """Prueft das Verhalten fuer modes point to input attachments and output."""
    phd = get_mode("PhD", project)
    german = get_mode("Freelance_German", project)
    english = get_mode("freelance english", project)

    assert phd.recipients_dir == project / "input/PhD"
    assert phd.log_path == project / "output/send_phd.csv"
    assert german.template_path.name == "freelance_german.txt"
    assert german.spam_safe_template_path.name == "freelance_german_spam_safe.txt"
    assert german.attachments_dir == project / "attachments/Freelance_German"
    assert german.log_path == project / "output/send_freelance.csv"
    assert english.template_path.name == "freelance_english.txt"
    assert english.spam_safe_template_path.name == "freelance_english_spam_safe.txt"
    assert english.recipients_dir == project / "input/Freelance_English"
    assert phd.spam_safe_template_path.name == "phd_spam_safe.txt"

    custom = get_mode("Custom Training Task", project)
    assert custom.label == "Custom Training Task"
    assert custom.recipients_dir == project / "input/Custom_Training_Task"
    assert custom.attachments_dir == project / "attachments/Custom_Training_Task"
    assert custom.template_path == project / "templates/custom_training_task.txt"
    assert custom.spam_safe_template_path == project / "templates/custom_training_task_spam_safe.txt"
    assert custom.log_path == project / "output/send_custom_training_task.csv"


def test_mode_name_and_label_helpers_cover_builtins_and_empty_values() -> None:
    """Checks mode helper edge cases used by GUI custom task dropdowns."""
    assert mode_name_from_label("PhD") == "PhD"
    assert mode_name_from_label("Freelance German") == "Freelance_German"
    assert mode_name_from_label("Freelance English") == "Freelance_English"
    assert mode_label_from_name("phd") == "PhD"
    assert mode_label_from_name("custom_task") == "custom task"
    with pytest.raises(ValueError, match="Mode name cannot be empty"):
        mode_name_from_label("  !!!  ")


def test_list_attachments_filters_gitkeep_and_sorts(tmp_path: Path) -> None:
    """Prueft das Verhalten fuer list attachments filters gitkeep and sorts."""
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    (tmp_path / "b.pdf").write_text("b", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/a.pdf").write_text("a", encoding="utf-8")

    assert [path.name for path in list_attachments(tmp_path)] == ["b.pdf", "a.pdf"]

    with pytest.raises(FileNotFoundError):
        list_attachments(tmp_path / "missing")

    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        list_attachments(file_path)


def test_load_smtp_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prueft das Verhalten fuer load smtp config."""
    monkeypatch.setattr("mail_sender.config.load_dotenv", lambda **_kwargs: None)
    monkeypatch.setattr("mail_sender.config._load_settings", lambda: {})
    for key in [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_ENCRYPTION",
        "SMTP_USERNAME",
        "SMTP_FROM_EMAIL",
        "SMTP_FROM_NAME",
        "SMTP_PASSWORD",
        "EXTERNAL_VALIDATION_SERVICE",
        "EXTERNAL_VALIDATION_STAGE",
        "NEVERBOUNCE_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)

    config = load_smtp_config(require_password=False)
    assert config.host == "smtp.hostinger.com"
    assert config.port == 465
    assert config.username == "info@carinaschoppe.com"
    assert config.password == ""
    assert config.external_validation_stage == "research"

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "never-key")
    config = load_smtp_config(require_password=True)
    assert config.password == "secret"
    assert config.port == 2525

    monkeypatch.setenv("SMTP_PORT", "bad")
    with pytest.raises(ConfigError, match="SMTP_PORT"):
        load_smtp_config(require_password=True)

    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_ENCRYPTION", "starttls")
    with pytest.raises(ConfigError, match="Only SSL"):
        load_smtp_config(require_password=True)

    monkeypatch.setenv("SMTP_ENCRYPTION", "ssl")
    monkeypatch.setenv("SMTP_PASSWORD", "")
    with pytest.raises(ConfigError, match="SMTP_PASSWORD"):
        load_smtp_config(require_password=True)

    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("SMTP_USERNAME", "")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "")
    with pytest.raises(ConfigError) as exc_info:
        load_smtp_config(require_password=True)
    message = str(exc_info.value)
    assert "SMTP_HOST" in message
    assert "SMTP_USERNAME" in message
    assert "SMTP_FROM_EMAIL" in message


def test_load_smtp_config_uses_selected_validation_service_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks that the NeverBounce validation key is selected from .env."""
    monkeypatch.setattr("mail_sender.config.load_dotenv", lambda **_kwargs: None)
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "neverbounce")
    monkeypatch.setenv("EXTERNAL_VALIDATION_STAGE", "send")
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "never-key")

    config = load_smtp_config(require_password=False)

    assert config.external_validation_service == "neverbounce"
    assert config.external_validation_api_key == "never-key"
    assert config.external_validation_stage == "send"


def test_load_smtp_config_defaults_to_neverbounce(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks that NeverBounce is the default validation provider."""
    monkeypatch.setattr("mail_sender.config.load_dotenv", lambda **_kwargs: None)
    monkeypatch.setattr("mail_sender.config._load_settings", lambda: {})
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.delenv("EXTERNAL_VALIDATION_SERVICE", raising=False)
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "never-key")

    config = load_smtp_config(require_password=False)

    assert config.external_validation_service == "neverbounce"
    assert config.external_validation_api_key == "never-key"


def test_load_smtp_config_rejects_unknown_validation_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks that mistyped validation providers fail loudly."""
    monkeypatch.setattr("mail_sender.config.load_dotenv", lambda **_kwargs: None)
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "mail-wizard")

    with pytest.raises(ConfigError, match="EXTERNAL_VALIDATION_SERVICE"):
        load_smtp_config(require_password=False)


def test_load_smtp_config_rejects_unknown_validation_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks that mistyped validation timing values fail loudly."""
    monkeypatch.setattr("mail_sender.config.load_dotenv", lambda **_kwargs: None)
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EXTERNAL_VALIDATION_STAGE", "later")

    with pytest.raises(ConfigError, match="EXTERNAL_VALIDATION_STAGE"):
        load_smtp_config(require_password=False)


def test_load_smtp_config_requires_neverbounce_key_for_real_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks that send-stage validation does not silently skip NeverBounce."""
    monkeypatch.setattr("mail_sender.config.load_dotenv", lambda **_kwargs: None)
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "neverbounce")
    monkeypatch.setenv("EXTERNAL_VALIDATION_STAGE", "send")
    monkeypatch.delenv("NEVERBOUNCE_API_KEY", raising=False)

    with pytest.raises(ConfigError, match="NEVERBOUNCE_API_KEY"):
        load_smtp_config(require_password=False)


def test_load_smtp_config_does_not_need_key_for_research_stage_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks that the sender does not require a key when NeverBounce already ran in research."""
    monkeypatch.setattr("mail_sender.config.load_dotenv", lambda **_kwargs: None)
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "neverbounce")
    monkeypatch.setenv("EXTERNAL_VALIDATION_STAGE", "research")
    monkeypatch.delenv("NEVERBOUNCE_API_KEY", raising=False)

    config = load_smtp_config(require_password=True)

    assert config.external_validation_stage == "research"
    assert config.external_validation_api_key == ""


def test_load_smtp_config_allows_disabling_external_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks that external validation can be disabled explicitly."""
    monkeypatch.setattr("mail_sender.config.load_dotenv", lambda **_kwargs: None)
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "none")
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "never-key")

    config = load_smtp_config(require_password=False)

    assert config.external_validation_service == "none"
    assert config.external_validation_api_key == ""
