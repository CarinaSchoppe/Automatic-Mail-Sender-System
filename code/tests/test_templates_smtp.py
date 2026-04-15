"""Tests und Hilfen fuer tests/test_templates_smtp.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from mail_sender.config import SmtpConfig
from mail_sender.recipients import Recipient
from mail_sender.smtp_sender import SmtpMailer, guess_content_type
from mail_sender.templates import render_mail


def test_render_mail_with_inline_image(project: Path) -> None:
    """Prueft das Verhalten fuer render mail with inline image."""
    rendered = render_mail(
        project / "templates/phd.txt",
        project / "templates/signature.txt",
        Recipient(email="a@example.com", company="ACME"),
        signature_image_path=project / "templates/signature-logo.png",
        signature_image_width=222,
    )

    assert rendered.subject == "PhD ACME"
    assert "[Logo]" in rendered.text_body
    assert 'width="222"' in rendered.html_body
    assert rendered.inline_images[0].path.name == "signature-logo.png"


def test_render_mail_subject_fallback_and_override(tmp_path: Path) -> None:
    """Prueft das Verhalten fuer render mail subject fallback and override."""
    template = tmp_path / "template.txt"
    signature = tmp_path / "signature.txt"
    template.write_text("Body for {company}", encoding="utf-8")
    signature.write_text("", encoding="utf-8")

    rendered = render_mail(template, signature, Recipient(email="a@example.com", company="ACME"))
    assert rendered.subject == "Message for ACME"

    rendered = render_mail(template, signature, Recipient(email="a@example.com"), subject_override="Hi {mail}")
    assert rendered.subject == "Hi a@example.com"
    assert rendered.inline_images == []


def test_render_mail_errors(project: Path, tmp_path: Path) -> None:
    """Prueft das Verhalten fuer render mail errors."""
    with pytest.raises(FileNotFoundError, match="Mail template"):
        render_mail(tmp_path / "missing.txt", project / "templates/signature.txt", Recipient(email="a@example.com"))

    with pytest.raises(FileNotFoundError, match="Signature template"):
        render_mail(project / "templates/phd.txt", tmp_path / "missing.txt", Recipient(email="a@example.com"))

    with pytest.raises(FileNotFoundError, match="logo file"):
        render_mail(project / "templates/phd.txt", project / "templates/signature.txt", Recipient(email="a@example.com"))

    not_image = tmp_path / "file.txt"
    not_image.write_text("not image", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an image"):
        render_mail(
            project / "templates/phd.txt",
            project / "templates/signature.txt",
            Recipient(email="a@example.com"),
            signature_image_path=not_image,
        )


class FakeSMTP:
    """Dokumentiert die Test- oder Hilfsklasse FakeSMTP."""
    instances: list["FakeSMTP"] = []

    def __init__(self, host: str, port: int, context) -> None:
        """Initialisiert oder verwaltet das Testobjekt."""
        self.host = host
        self.port = port
        self.context = context
        self.logged_in = None
        self.sent_messages = []
        self.quit_called = False
        FakeSMTP.instances.append(self)

    def login(self, username: str, password: str) -> None:
        """Kapselt den Hilfsschritt login."""
        self.logged_in = (username, password)

    def send_message(self, message) -> None:
        """Kapselt den Hilfsschritt send_message."""
        self.sent_messages.append(message)

    def quit(self) -> None:
        """Kapselt den Hilfsschritt quit."""
        self.quit_called = True


def test_smtp_mailer_sends_message_with_attachment_and_inline_image(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Prueft das Verhalten fuer smtp mailer sends message with attachment and inline image."""
    monkeypatch.setattr("mail_sender.smtp_sender.smtplib.SMTP_SSL", FakeSMTP)
    FakeSMTP.instances.clear()
    attachment = project / "attachments/PhD/file.txt"
    attachment.write_text("attachment", encoding="utf-8")
    rendered = render_mail(
        project / "templates/phd.txt",
        project / "templates/signature.txt",
        Recipient(email="to@example.com", company="ACME"),
        signature_image_path=project / "templates/signature-logo.png",
    )
    config = SmtpConfig(
        host="smtp.example.com",
        port=465,
        username="user",
        password="pass",
        from_email="from@example.com",
        from_name="From Name",
    )

    with SmtpMailer(config) as mailer:
        mailer.send(
            Recipient(email="to@example.com", company="ACME"),
            rendered.subject,
            rendered.text_body,
            rendered.html_body,
            [attachment],
            rendered.inline_images,
        )

    server = FakeSMTP.instances[0]
    assert server.host == "smtp.example.com"
    assert server.logged_in == ("user", "pass")
    assert server.sent_messages[0]["To"] == "to@example.com"
    assert server.quit_called is True
    assert guess_content_type(Path("unknown.abcxyz"), ("application", "octet-stream")) == ("application", "octet-stream")


def test_smtp_mailer_requires_open_connection() -> None:
    """Prueft das Verhalten fuer smtp mailer requires open connection."""
    config = SmtpConfig("host", 465, "user", "pass", "from@example.com", "From")
    with pytest.raises(RuntimeError, match="not open"):
        SmtpMailer(config).send(Recipient(email="to@example.com"), "Subject", "text", "<p>text</p>", [], [])


def test_smtp_mailer_exit_without_open_connection() -> None:
    """Prueft, dass ein ungeoeffneter SMTP-Mailer sauber verlassen werden kann."""
    config = SmtpConfig("host", 465, "user", "pass", "from@example.com", "From")

    SmtpMailer(config).__exit__(None, None, None)
