"""Tests und Hilfen fuer tests/test_modes_attachments_config.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from mail_sender.attachments import list_attachments
from mail_sender.config import ConfigError, load_smtp_config
from mail_sender.modes import get_mode


def test_modes_point_to_input_attachments_and_output(project: Path) -> None:
    """Prueft das Verhalten fuer modes point to input attachments and output."""
    phd = get_mode("PhD", project)
    german = get_mode("Freelance_German", project)
    english = get_mode("freelance english", project)

    assert phd.recipients_dir == project / "input/PhD"
    assert phd.log_path == project / "output/send_phd.csv"
    assert german.template_path.name == "freelance_german.txt"
    assert german.attachments_dir == project / "attachments/Freelance_German"
    assert german.log_path == project / "output/send_freelance.csv"
    assert english.template_path.name == "freelance_english.txt"
    assert english.recipients_dir == project / "input/Freelance_English"

    with pytest.raises(ValueError, match="Unknown mode"):
        get_mode("Freelance", project)


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
    monkeypatch.setattr("mail_sender.config.load_dotenv", lambda: None)
    for key in [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_ENCRYPTION",
        "SMTP_USERNAME",
        "SMTP_FROM_EMAIL",
        "SMTP_FROM_NAME",
        "SMTP_PASSWORD",
    ]:
        monkeypatch.delenv(key, raising=False)

    config = load_smtp_config(require_password=False)
    assert config.host == "smtp.hostinger.com"
    assert config.port == 465
    assert config.username == "info@carinaschoppe.com"
    assert config.password == ""

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_PORT", "2525")
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
