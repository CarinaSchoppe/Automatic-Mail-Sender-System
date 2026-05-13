"""Tests and helpers for tests/test_templates_smtp.py."""

from __future__ import annotations

import smtplib
from pathlib import Path

import pytest

from mail_sender.config import SmtpConfig
from mail_sender.recipients import Recipient
from mail_sender.smtp_sender import SmtpMailer, guess_content_type
from mail_sender.templates import InlineImage, _HtmlTextExtractor, _append_signature_html, _html_to_text, render_mail


def test_render_mail_with_html_signature(project: Path) -> None:
    """Checks behavior for render mail with the configured HTML signature."""
    rendered = render_mail(
        project / "templates/phd.txt",
        project / "templates/signature.html",
        Recipient(email="a@example.com", company="ACME"),
    )

    assert rendered.subject == "PhD ACME"
    assert "Carina Sophie Schoppe" in rendered.text_body
    assert "<table>" in rendered.html_body
    assert "cid:" not in rendered.html_body
    assert rendered.inline_images == []


def test_render_mail_supports_signature_placeholder(project: Path) -> None:
    """Checks that {SIGNATURE} places the configured HTML signature exactly there."""
    template = project / "templates/phd.txt"
    template.write_text("Subject: PhD {company}\n\nHello {company}\n{SIGNATURE}\nAfter", encoding="utf-8")

    rendered = render_mail(
        template,
        project / "templates/signature.html",
        Recipient(email="a@example.com", company="ACME"),
    )

    assert rendered.html_body.index("<table>") < rendered.html_body.index("After")
    assert rendered.inline_images == []


def test_render_mail_subject_fallback_and_override(tmp_path: Path) -> None:
    """Checks behavior for render mail subject fallback and override."""
    template = tmp_path / "template.txt"
    signature = tmp_path / "signature.html"
    template.write_text("Body for {company}", encoding="utf-8")
    signature.write_text("<html><body></body></html>", encoding="utf-8")

    rendered = render_mail(template, signature, Recipient(email="a@example.com", company="ACME"))
    assert rendered.subject == "Message for ACME"

    rendered = render_mail(template, signature, Recipient(email="a@example.com"), subject_override="Hi {mail}")
    assert rendered.subject == "Hi a@example.com"
    assert rendered.inline_images == []


def test_render_mail_without_signature_and_html_text_edge_cases(tmp_path: Path) -> None:
    """Covers no-signature rendering and HTML-to-text helper edge cases."""
    template = tmp_path / "template.txt"
    signature = tmp_path / "signature.html"
    template.write_text("Subject: Hello {company}\n\nPlain body", encoding="utf-8")
    signature.write_text("", encoding="utf-8")

    rendered = render_mail(template, signature, Recipient(email="a@example.com", company="ACME"))

    assert rendered.text_body == "Plain body"
    assert rendered.html_body == "<html><body>Plain body</body></html>"
    assert _append_signature_html(rendered.html_body, "") == rendered.html_body
    assert _html_to_text('<div>Hello<img alt="Logo"><br></div>') == "Hello Logo"
    assert _html_to_text("<div>Hello<img></div>") == "Hello"
    assert _html_to_text("<p>One</p>\n\n<p>Two</p>") == "One\nTwo"
    assert _html_to_text("<br><p> </p>") == ""
    extractor = _HtmlTextExtractor()
    extractor._chunks = ["\n", "Kept"]
    assert extractor.text() == "Kept"


def test_render_mail_errors(project: Path, tmp_path: Path) -> None:
    """Checks behavior for render mail errors."""
    with pytest.raises(FileNotFoundError, match="Mail template"):
        render_mail(tmp_path / "missing.txt", project / "templates/signature.txt", Recipient(email="a@example.com"))

    with pytest.raises(FileNotFoundError, match="Signature HTML file"):
        render_mail(project / "templates/phd.txt", tmp_path / "missing.html", Recipient(email="a@example.com"))


class FakeSMTP:
    """Helper class for simulated SMTP connection."""
    instances: list["FakeSMTP"] = []

    def __init__(self, host: str, port: int, context) -> None:
        """Initializes or manages the test object."""
        self.host = host
        self.port = port
        self.context = context
        self.logged_in = None
        self.sent_messages = []
        self.quit_called = False
        FakeSMTP.instances.append(self)

    def login(self, username: str, password: str) -> None:
        """Encapsulates the helper step login."""
        self.logged_in = (username, password)

    def send_message(self, message) -> None:
        """Encapsulates the helper step send_message."""
        self.sent_messages.append(message)

    def quit(self) -> None:
        """Encapsulates the helper step quit."""
        self.quit_called = True


def test_smtp_mailer_sends_message_with_attachment(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Checks behavior for smtp mailer sends message with attachment."""
    monkeypatch.setattr("mail_sender.smtp_sender.smtplib.SMTP_SSL", FakeSMTP)
    FakeSMTP.instances.clear()
    attachment = project / "attachments/PhD/file.txt"
    attachment.write_text("attachment", encoding="utf-8")
    rendered = render_mail(
        project / "templates/phd.txt",
        project / "templates/signature.html",
        Recipient(email="to@example.com", company="ACME"),
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


def test_smtp_mailer_embeds_inline_images(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Checks the MIME path that embeds CID images in HTML mail."""
    monkeypatch.setattr("mail_sender.smtp_sender.smtplib.SMTP_SSL", FakeSMTP)
    FakeSMTP.instances.clear()
    image = project / "inline.png"
    image.write_bytes(b"fake image")
    config = SmtpConfig("smtp.example.com", 465, "user", "pass", "from@example.com", "From Name")

    with SmtpMailer(config) as mailer:
        mailer.send(
            Recipient(email="to@example.com", company="ACME"),
            "Subject",
            "text",
            '<html><body><img src="cid:logo"></body></html>',
            [],
            [InlineImage(path=image, cid="logo", width=100)],
        )

    html_part = FakeSMTP.instances[0].sent_messages[0].get_payload()[-1]
    assert any(part.get_filename() == "inline.png" for part in html_part.iter_attachments())


def test_smtp_mailer_rejects_refused_recipient_response(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Checks that SMTP refusal dictionaries are treated as failed sends."""

    class RefusingSMTP(FakeSMTP):
        """Simulates an SMTP server that reports a rate-limited recipient."""

        def send_message(self, message):
            """Records the message, then reports the recipient as refused."""
            super().send_message(message)
            return {"to@example.com": (450, b"4.7.0 too many requests")}

    monkeypatch.setattr("mail_sender.smtp_sender.smtplib.SMTP_SSL", RefusingSMTP)
    FakeSMTP.instances.clear()
    config = SmtpConfig("smtp.example.com", 465, "user", "pass", "from@example.com", "From Name")

    with pytest.raises(smtplib.SMTPRecipientsRefused) as error:
        with SmtpMailer(config) as mailer:
            mailer.send(Recipient(email="to@example.com"), "Subject", "text", "<p>text</p>", [], [])

    assert "to@example.com" in error.value.recipients
    assert FakeSMTP.instances[0].quit_called is True


def test_smtp_mailer_requires_open_connection() -> None:
    """Checks behavior for smtp mailer requires open connection."""
    config = SmtpConfig("host", 465, "user", "pass", "from@example.com", "From")
    with pytest.raises(RuntimeError, match="not open"):
        SmtpMailer(config).send(Recipient(email="to@example.com"), "Subject", "text", "<p>text</p>", [], [])


def test_smtp_mailer_exit_without_open_connection() -> None:
    """Checks that an unopen SMTP mailer can be exited cleanly."""
    config = SmtpConfig("host", 465, "user", "pass", "from@example.com", "From")

    SmtpMailer(config).__exit__(None, None, None)
