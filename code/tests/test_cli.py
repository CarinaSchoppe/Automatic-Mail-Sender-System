"""Tests and helpers for tests/test_cli.py."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from mail_sender import cli
from mail_sender.recipients import Recipient


@pytest.fixture(autouse=True)
def disable_external_validation_by_default(monkeypatch) -> None:
    """Keeps unrelated CLI tests focused on local send behavior."""
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "none")


def write_recipient(path: Path, company: str, email: str) -> None:
    """Encapsulates the helper step write_recipient."""
    path.write_text(f"company,mail\n{company},{email}\n", encoding="utf-8")


def write_invalid_log(project: Path, company: str, mail: str, reason: str = "old invalid result") -> None:
    """Writes a test entry to the invalid_mails.csv file."""
    with (project / "output/invalid_mails.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "invalid_reason", "detected_at"])
        writer.writerow([company, mail, reason, "2026-04-14T10:00+10:00"])


def setup_fake_mailer(monkeypatch, send_callback) -> None:
    """Configures a FakeMailer with a callback for the sending process."""

    class FakeMailer:
        """Helper class for simulated SMTP sending processes."""

        def __init__(self, config) -> None:
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback) -> None:
            pass

        @staticmethod
        def send(*args, **kwargs) -> None:
            send_callback(*args, **kwargs)

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "none")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)


def test_cli_auto_processes_each_input_folder_and_logs_dry_run(project: Path, capsys) -> None:
    """Checks behavior for cli auto processes each input folder and logs dry run."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")
    write_recipient(project / "input/Freelance_German/de.txt", "DE Co", "de@example.com")
    write_recipient(project / "input/Freelance_English/en.csv", "EN Co", "en@example.com")

    result = cli.main([
        "--mode",
        "Auto",
        "--base-dir",
        str(project),
        "--allow-empty-attachments",
        "--log-dry-run",
        "--verbose",
    ])

    assert result == 0
    output = capsys.readouterr().out
    assert "Mode: PhD" in output
    assert "Mode: Freelance German" in output
    assert "Mode: Freelance English" in output
    with (project / "output/send_phd.csv").open("r", encoding="utf-8-sig", newline="") as f:
        assert len(list(csv.reader(f))) == 2
    with (project / "output/send_freelance.csv").open("r", encoding="utf-8-sig", newline="") as f:
        assert len(list(csv.reader(f))) == 3


def test_cli_skips_logged_and_duplicate_addresses(project: Path, capsys) -> None:
    """Checks behavior for cli skips logged and duplicate addresses."""
    write_recipient(project / "input/PhD/one.csv", "One", "one@example.com")
    (project / "input/PhD/two.csv").write_text("company,mail\nTwo,one@example.com\nLogged,logged@example.com\n", encoding="utf-8")
    with (project / "output/send_phd.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "sent_at"])
        writer.writerow(["Logged", "mailto:logged@example.com", "2026-04-14T10:00+10:00"])

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments"])

    assert result == 0
    output = capsys.readouterr().out
    assert "duplicate skipped" in output
    assert "already present in an output CSV log" in output
    assert "[DRY_RUN] one@example.com" in output


def test_cli_skips_invalid_addresses_and_persists_invalid_log(monkeypatch, project: Path, capsys) -> None:
    """Checks behavior for cli skips invalid addresses and persists invalid log."""
    write_recipient(project / "input/PhD/bad.csv", "Bad", "bad@example.invalid")
    write_recipient(project / "input/PhD/good.csv", "Good", "good@example.com")

    def fake_validate(email: str):
        """Encapsulates the helper step fake_validate."""
        if email == "bad@example.invalid":
            return type("Result", (), {"is_valid": False, "reason": "domain has no MX or A record"})()
        return type("Result", (), {"is_valid": True, "reason": ""})()

    monkeypatch.setattr("mail_sender.cli.validate_email_address", fake_validate)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments"])

    assert result == 0
    output = capsys.readouterr().out
    assert "[INVALID] bad@example.invalid | domain has no MX or A record" in output
    assert "[DRY_RUN] good@example.com" in output
    with (project / "output/invalid_mails.csv").open("r", encoding="utf-8-sig", newline="") as f:
        reader = list(csv.reader(f))
        assert reader[1][:3] == ["Bad", "bad@example.invalid", "domain has no MX or A record"]


def test_cli_strict_smtp_validation_flags_are_forwarded(monkeypatch, project: Path, capsys) -> None:
    """Checks that conservative mailbox validation options reach the validator."""
    write_recipient(project / "input/PhD/good.csv", "Good", "good@example.com")
    calls = []

    def fake_validate(email: str, **kwargs):
        """Captures strict validation kwargs."""
        calls.append((email, kwargs))
        return type("Result", (), {"is_valid": True, "reason": ""})()

    monkeypatch.setattr("mail_sender.cli.validate_email_address", fake_validate)
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "none")

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--allow-empty-attachments",
        "--require-email-smtp-pass",
        "--reject-catch-all",
        "--verify-email-smtp-timeout",
        "3",
    ])

    assert result == 0
    assert calls == [
        (
            "good@example.com",
            {
                "skip_dns_check": False,
                "verify_mailbox": True,
                "require_mailbox_confirmation": True,
                "reject_catch_all": True,
                "smtp_timeout": 3.0,
                "smtp_from_email": "info@carinaschoppe.com",
            },
        )
    ]
    output = capsys.readouterr().out
    assert "Require SMTP mailbox confirmation: yes" in output
    assert "Reject catch-all domains: yes" in output
    assert "Validation summary:" in output


def test_cli_forwards_selected_external_validation_key(monkeypatch, project: Path, capsys) -> None:
    """Checks that the configured NeverBounce API key reaches per-recipient send validation."""
    write_recipient(project / "input/PhD/good.csv", "Good", "good@example.com")
    external_calls = []

    def fake_validate(email: str, **kwargs):
        if kwargs.get("external_service") == "neverbounce":
            external_calls.append((email, kwargs["external_api_key"], kwargs["smtp_timeout"]))
        return type("Result", (), {"is_valid": True, "reason": ""})()

    monkeypatch.setattr("mail_sender.cli.validate_email_address", fake_validate)
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "neverbounce")
    monkeypatch.setenv("EXTERNAL_VALIDATION_STAGE", "send")
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "never-key")

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--allow-empty-attachments",
    ])

    assert result == 0
    assert external_calls == [("good@example.com", "never-key", 8.0)]
    output = capsys.readouterr().out
    assert "External validation: neverbounce" in output
    assert "External validation stage: send" in output


def test_cli_neverbounce_validation_blocks_send(monkeypatch, project: Path, capsys) -> None:
    """Checks that NeverBounce validation happens before real sending."""
    write_recipient(project / "input/PhD/bad.csv", "Bad", "bad@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")
    sent = []

    def fake_validate(_email: str, **kwargs):
        if kwargs.get("external_service") == "neverbounce":
            return type("Result", (), {"is_valid": False, "reason": "NeverBounce: invalid"})()
        return type("Result", (), {"is_valid": True, "reason": ""})()

    setup_fake_mailer(monkeypatch, lambda *args, **kwargs: sent.append((args, kwargs)))
    monkeypatch.setattr("mail_sender.cli.validate_email_address", fake_validate)
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "neverbounce")
    monkeypatch.setenv("EXTERNAL_VALIDATION_STAGE", "send")
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "never-key")

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--send",
    ])

    assert result == 0
    assert sent == []
    output = capsys.readouterr().out
    assert "[INVALID] bad@example.com | NeverBounce: invalid" in output
    assert "[SENT]" not in output
    with (project / "output/invalid_mails.csv").open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1][:3] == ["Bad", "bad@example.com", "NeverBounce: invalid"]


def test_cli_runs_neverbounce_as_per_recipient_send_gate(monkeypatch, project: Path, capsys) -> None:
    """Checks that NeverBounce checks each locally accepted final recipient separately."""
    (project / "input/PhD/phd.csv").write_text(
        "company,mail\nGood,good@example.com\nBad,bad@example.com\nLogged,logged@example.com\n",
        encoding="utf-8",
    )
    with (project / "output/send_phd.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "sent_at"])
        writer.writerow(["Logged", "logged@example.com", "2026-04-14T10:00+10:00"])

    local_calls = []
    neverbounce_calls = []

    def fake_validate(email: str, **kwargs):
        if kwargs.get("external_service") == "neverbounce":
            neverbounce_calls.append((email, kwargs["external_api_key"], kwargs["smtp_timeout"]))
            return type("Result", (), {
                "is_valid": email == "good@example.com",
                "reason": "" if email == "good@example.com" else "NeverBounce: invalid",
            })()
        local_calls.append((email, kwargs))
        return type("Result", (), {"is_valid": True, "reason": ""})()

    monkeypatch.setattr("mail_sender.cli.validate_email_address", fake_validate)
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "neverbounce")
    monkeypatch.setenv("EXTERNAL_VALIDATION_STAGE", "send")
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "never-key")

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--allow-empty-attachments",
        "--parallel-threads",
        "1",
    ])

    assert result == 0
    assert [email for email, _kwargs in local_calls] == ["good@example.com", "bad@example.com"]
    assert neverbounce_calls == [
        ("good@example.com", "never-key", 8.0),
        ("bad@example.com", "never-key", 8.0),
    ]
    output = capsys.readouterr().out
    assert "already present in an output CSV log" in output
    assert "[INVALID] bad@example.com | NeverBounce: invalid" in output
    assert "[DRY_RUN] good@example.com" in output


def test_cli_research_stage_does_not_repeat_neverbounce_at_send(monkeypatch, project: Path, capsys) -> None:
    """Checks that research-stage NeverBounce is not repeated during sending."""
    write_recipient(project / "input/PhD/good.csv", "Good", "good@example.com")
    calls = []

    def fake_validate(email: str, **kwargs):
        calls.append((email, kwargs))
        return type("Result", (), {"is_valid": True, "reason": ""})()

    monkeypatch.setattr("mail_sender.cli.validate_email_address", fake_validate)
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "neverbounce")
    monkeypatch.setenv("EXTERNAL_VALIDATION_STAGE", "research")
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "never-key")

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments"])

    assert result == 0
    assert calls == [("good@example.com", {"skip_dns_check": False})]
    assert all(call[1].get("external_service") != "neverbounce" for call in calls)
    assert "[DRY_RUN] good@example.com" in capsys.readouterr().out


def test_cli_skips_local_email_validation_when_all_validation_switches_are_off(
        monkeypatch,
        project: Path,
        capsys,
) -> None:
    """Checks that disabled validation settings do not still call the validator."""
    write_recipient(project / "input/PhD/good.csv", "Good", "good@example.com")

    def fail_validate(*_args, **_kwargs):
        raise AssertionError("validate_email_address should not run")

    monkeypatch.setattr("mail_sender.cli.validate_email_address", fail_validate)
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "none")

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--allow-empty-attachments",
        "--skip-email-dns-check",
        "--verbose",
    ])

    output = capsys.readouterr().out
    assert result == 0
    assert "Local email validation is disabled" in output
    assert "Checking recipient" not in output
    assert "Validation result" not in output
    assert "[DRY_RUN] good@example.com" in output


def test_cli_logs_validation_crashes_as_invalid(monkeypatch, project: Path, capsys) -> None:
    """Checks that validation worker crashes become invalid rows instead of killing the run."""
    write_recipient(project / "input/PhD/bad.csv", "Bad", "bad@example.com")

    def broken_validate(email: str):
        """Simulates a DNS/SMTP library crash during validation."""
        raise RuntimeError(f"validator died for {email}")

    monkeypatch.setattr("mail_sender.cli.validate_email_address", broken_validate)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments"])

    assert result == 0
    output = capsys.readouterr().out
    assert "[INVALID] bad@example.com | validation crashed: RuntimeError: validator died for bad@example.com" in output
    with (project / "output/invalid_mails.csv").open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1][:3] == [
        "Bad",
        "bad@example.com",
        "validation crashed: RuntimeError: validator died for bad@example.com",
    ]


def test_cli_skips_addresses_already_in_invalid_log(project: Path, capsys) -> None:
    """Checks behavior for cli skips addresses already in invalid log."""
    write_recipient(project / "input/PhD/bad.csv", "Bad", "bad@example.invalid")
    with (project / "output/invalid_mails.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "invalid_reason", "detected_at"])
        writer.writerow(["Bad", "bad@example.invalid", "domain has no MX or A record", "2026-04-14T10:00+10:00"])

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments", "--no-skip-invalid-check"])

    assert result == 0
    assert "already listed in invalid_mails.csv" in capsys.readouterr().out


def test_cli_resend_existing_and_skip_invalid_check_allows_invalid_log_address(project: Path, capsys) -> None:
    """Checks that resend and skip-invalid allow a logged invalid mail."""
    write_recipient(project / "input/PhD/bad.csv", "Bad", "bad@example.invalid")
    with (project / "output/send_phd.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "sent_at"])
        writer.writerow(["Bad", "bad@example.invalid", "2026-04-14T10:00+10:00"])
    with (project / "output/invalid_mails.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "invalid_reason", "detected_at"])
        writer.writerow(["Bad", "bad@example.invalid", "old invalid result", "2026-04-14T10:00+10:00"])

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--allow-empty-attachments",
        "--resend-existing",
        "--skip-invalid-check",
        "--skip-email-dns-check",
    ])

    output = capsys.readouterr().out
    assert result == 0
    assert "[DRY_RUN] bad@example.invalid" in output
    assert "Existing CSV check: disabled (--resend-existing)" in output
    assert "Invalid CSV check: disabled (--skip-invalid-check)" in output


def test_cli_skip_invalid_check_sends_invalid_log_address_when_not_sent(project: Path, capsys) -> None:
    """Checks that skip-invalid only ignores the invalid list."""
    write_recipient(project / "input/PhD/bad.csv", "Bad", "bad@example.invalid")
    write_invalid_log(project, "Bad", "bad@example.invalid")

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--allow-empty-attachments",
        "--skip-invalid-check",
        "--skip-email-dns-check",
    ])

    output = capsys.readouterr().out
    assert result == 0
    assert "[DRY_RUN] bad@example.invalid" in output
    assert "[SKIP_INVALID]" not in output
    assert "Existing CSV check: enabled" in output
    assert "Invalid CSV check: disabled (--skip-invalid-check)" in output


def test_cli_skip_invalid_check_still_blocks_sent_log_address_without_resend(project: Path, capsys) -> None:
    """Checks that skip-invalid does not disable the existing sent-log check."""
    write_recipient(project / "input/PhD/bad.csv", "Bad", "bad@example.invalid")
    with (project / "output/send_freelance.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "sent_at"])
        writer.writerow(["Bad", "bad@example.invalid", "2026-04-14T10:00+10:00"])
    write_invalid_log(project, "Bad", "bad@example.invalid")

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--allow-empty-attachments",
        "--skip-invalid-check",
        "--skip-email-dns-check",
    ])

    output = capsys.readouterr().out
    assert result == 0
    assert "already present in an output CSV log" in output
    assert "[DRY_RUN] bad@example.invalid" not in output
    assert "Existing CSV check: enabled" in output
    assert "Invalid CSV check: disabled (--skip-invalid-check)" in output


def test_cli_checks_all_output_csv_logs(project: Path, capsys) -> None:
    """Checks behavior for cli checks all output csv logs."""
    write_recipient(project / "input/PhD/phd.csv", "Existing", "existing@example.com")
    with (project / "output/send_freelance.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "sent_at"])
        writer.writerow(["Existing", "existing@example.com", "2026-04-14T10:00+10:00"])

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments"])

    assert result == 0
    assert "already present in an output CSV log" in capsys.readouterr().out


def test_cli_returns_zero_when_all_recipients_are_logged(project: Path, capsys) -> None:
    """Checks behavior for cli returns zero when all recipients are logged."""
    write_recipient(project / "input/PhD/one.csv", "One", "one@example.com")
    with (project / "output/send_phd.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "sent_at"])
        writer.writerow(["One", "one@example.com", "2026-04-14T10:00+10:00"])

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments", "--verbose"])

    assert result == 0
    output = capsys.readouterr().out
    assert "Loaded 1 existing email address" in output
    assert "Nothing to process." in output


def test_cli_returns_zero_when_auto_has_no_files(project: Path, capsys) -> None:
    """Checks behavior for cli returns zero when auto has no files."""
    result = cli.main(["--mode", "Auto", "--base-dir", str(project)])

    assert result == 0
    assert "No input files found" in capsys.readouterr().out


def test_cli_specific_mode_reports_missing_input_files(project: Path, capsys) -> None:
    """Checks behavior for cli specific mode reports missing input files."""
    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments", "--verbose"])

    assert result == 1
    output = capsys.readouterr().out
    assert "No recipient files found." in output
    assert "No .csv or .txt recipient files found" in output


def test_cli_errors_for_missing_attachments(project: Path, capsys) -> None:
    """Checks behavior for cli errors for missing attachments."""
    write_recipient(project / "input/Freelance_English/en.csv", "EN Co", "en@example.com")

    result = cli.main(["--mode", "Freelance_English", "--base-dir", str(project)])

    assert result == 1
    assert "No attachments found" in capsys.readouterr().out


def test_cli_resend_existing_bypasses_output_log(project: Path, capsys) -> None:
    """Checks behavior for cli resend existing bypasses output log."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")
    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--allow-empty-attachments",
        "--resend-existing",
        "--verbose",
    ])

    assert result == 0
    assert "Existing CSV log addresses will be ignored" in capsys.readouterr().out


def test_cli_send_path_uses_mailer(monkeypatch, project: Path) -> None:
    """Checks behavior for cli send path uses mailer."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")
    sent = []

    class FakeMailer:
        """Documents the test or helper class FakeMailer."""

        def __init__(self, config) -> None:
            """Initializes or manages the test object."""
            self.config = config

        def __enter__(self):
            """Initializes or manages the test object."""
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Initializes or manages the test object."""
            return None

        @staticmethod
        def send(recipient, subject, _text_body, _html_body, attachments, inline_images) -> None:
            """Notes the simulated sending with subject and attachment count."""
            sent.append((recipient.email, subject, len(attachments), len(inline_images)))

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send"])

    assert result == 0
    assert sent == [("phd@example.com", "PhD PhD Co", 1, 0)]
    with (project / "output/send_phd.csv").open("r", encoding="utf-8-sig", newline="") as f:
        reader = list(csv.reader(f))
        assert reader[1][1] == "phd@example.com"


def test_cli_spam_safe_uses_safe_template_and_skips_attachments(monkeypatch, project: Path, capsys) -> None:
    """Checks that spam-safe mode switches template and sends no MIME extras."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")
    sent = []

    class FakeMailer:
        """Documents the test or helper class FakeMailer."""

        def __init__(self, config) -> None:
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        @staticmethod
        def send(recipient, subject, _text_body, html_body, attachments, inline_images) -> None:
            sent.append((recipient.email, subject, len(attachments), len(inline_images), html_body))

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send", "--spam-safe"])

    assert result == 0
    assert len(sent) == 1
    assert sent[0][:4] == ("phd@example.com", "PhD safe PhD Co", 0, 0)
    assert "cid:" not in sent[0][4]
    output = capsys.readouterr().out
    assert "Spam-safe mode: yes" in output
    assert "skipping all mail attachments" in output


def test_cli_resend_existing_sends_without_duplicate_sent_log(monkeypatch, project: Path) -> None:
    """Checks that resend sends but does not write a duplicate sent-log row."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")
    with (project / "output/send_phd.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "sent_at"])
        writer.writerow(["Old", "mailto:phd@example.com", "2026-04-14T10:00+10:00"])
    sent = []

    class FakeMailer:
        """Documents the test or helper class FakeMailer."""

        def __init__(self, config) -> None:
            """Initializes or manages the test object."""
            self.config = config

        def __enter__(self):
            """Initializes or manages the test object."""
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            return None

        @staticmethod
        def send(recipient, *_args, **_kwargs) -> None:
            """Notes the address sent again despite resend."""
            sent.append(recipient.email)

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send", "--resend-existing"])

    assert result == 0
    assert sent == ["phd@example.com"]
    with (project / "output/send_phd.csv").open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2


def test_cli_logs_sent_mail_immediately_after_successful_send(monkeypatch, project: Path) -> None:
    """Checks that the sent-log is written directly after successful SMTP-send."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")
    events = []

    class FakeMailer:
        """Documents the test or helper class FakeMailer."""

        def __init__(self, config) -> None:
            """Initializes or manages the test object."""
            self.config = config

        def __enter__(self):
            """Initializes or manages the test object."""
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Initializes or manages the test object."""
            return None

        @staticmethod
        def send(recipient, *_args, **_kwargs) -> None:
            """Notes the successful simulated SMTP-send."""
            events.append(("send", recipient.email))

    def fake_append_log(_log_path, recipient) -> None:
        """Notes the direct sent-log write time."""
        events.append(("log", recipient.email))

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)
    monkeypatch.setattr("mail_sender.cli.append_log", fake_append_log)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send"])

    assert result == 0
    assert events == [("send", "phd@example.com"), ("log", "phd@example.com")]


def test_cli_does_not_log_sent_mail_when_smtp_send_is_uncertain(monkeypatch, project: Path, capsys) -> None:
    """Checks that SMTP timeouts or rate limits are retryable and not logged."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")

    def fail_send(*_args, **_kwargs) -> None:
        """Simulates an uncertain SMTP result."""
        raise TimeoutError("SMTP timeout / too many requests")

    setup_fake_mailer(monkeypatch, fail_send)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send"])

    assert result == 1
    output = capsys.readouterr().out
    assert "[SENT]" not in output
    assert "[ERROR] phd@example.com | TimeoutError: SMTP timeout / too many requests" in output
    assert not (project / "output/send_phd.csv").exists()
    assert not (project / "output/invalid_mails.csv").exists()


def test_cli_send_path_respects_max_send_count(monkeypatch, project: Path, capsys) -> None:
    """Checks behavior for cli send path respects max send count."""
    (project / "input/PhD/phd.csv").write_text(
        "company,mail\nA,a@example.com\nB,b@example.com\nC,c@example.com\n",
        encoding="utf-8",
    )
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")
    sent = []
    setup_fake_mailer(monkeypatch, lambda recipient, *_args, **_kwargs: sent.append(recipient.email))

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send", "--max-send-count", "2"])

    assert result == 0
    assert sent == ["a@example.com", "b@example.com"]
    assert "Limiting this run to 2 recipient(s)." in capsys.readouterr().out
    with (project / "output/send_phd.csv").open("r", encoding="utf-8-sig", newline="") as f:
        assert len(list(csv.reader(f))) == 3


def test_cli_parallel_send_logs_each_recipient_once(monkeypatch, project: Path) -> None:
    """Checks behavior for cli parallel send logs each recipient once."""
    (project / "input/PhD/phd.csv").write_text(
        "company,mail\nA,a@example.com\nB,b@example.com\nC,c@example.com\n",
        encoding="utf-8",
    )
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")
    sent = []
    setup_fake_mailer(monkeypatch, lambda recipient, *_args, **_kwargs: sent.append(recipient.email))

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send", "--parallel-threads", "2"])

    assert result == 0
    assert sorted(sent) == ["a@example.com", "b@example.com", "c@example.com"]
    with (project / "output/send_phd.csv").open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert sorted(row[1] for row in rows[1:]) == ["a@example.com", "b@example.com", "c@example.com"]


def test_cli_rejects_invalid_max_send_count(project: Path, capsys) -> None:
    """Checks behavior for cli rejects invalid max send count."""
    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--max-send-count", "0"])

    assert result == 1
    assert "--max-send-count must be at least 1" in capsys.readouterr().out


def test_cli_can_disable_sent_csv_logging(monkeypatch, project: Path) -> None:
    """Checks behavior for cli can disable sent csv logging."""

    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")

    class FakeMailer:
        """Documents the test or helper class FakeMailer."""

        def __init__(self, config) -> None:
            """Initializes or manages the test object."""
            self.config = config

        def __enter__(self):
            """Initializes or manages the test object."""
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Initializes or manages the test object."""
            return None

        def send(self, *args, **kwargs):
            """Encapsulates the helper step send."""
            pass

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send", "--no-write-sent-log"])

    assert result == 0
    assert not (project / "output/send_phd.csv").exists()


def test_cli_deletes_input_files_after_successful_real_send(monkeypatch, project: Path) -> None:
    """Checks behavior for cli deletes input files after successful real send."""
    input_file = project / "input/PhD/phd.csv"
    write_recipient(input_file, "PhD Co", "phd@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")

    class FakeMailer:
        """Documents the test or helper class FakeMailer."""

        def __init__(self, config) -> None:
            """Initializes or manages the test object."""
            self.config = config

        def __enter__(self):
            """Initializes or manages the test object."""
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Initializes or manages the test object."""
            return None

        def send(self, *args, **kwargs):
            """Encapsulates the helper step send."""
            pass

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--send",
        "--delete-input-after-success",
    ])

    assert result == 0
    assert not input_file.exists()


def test_cli_keeps_input_files_after_dry_run_and_error(monkeypatch, project: Path) -> None:
    """Checks behavior for cli keeps input files after dry run and error."""
    input_file = project / "input/PhD/phd.csv"
    write_recipient(input_file, "PhD Co", "phd@example.com")

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--allow-empty-attachments",
        "--delete-input-after-success",
    ])
    assert result == 0
    assert input_file.exists()

    def broken_render(*_args, **_kwargs):
        """Encapsulates the helper step broken_render."""
        raise ValueError("boom")

    monkeypatch.setattr("mail_sender.cli.render_mail", broken_render)
    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--send",
        "--allow-empty-attachments",
        "--delete-input-after-success",
    ])
    assert result == 1
    assert input_file.exists()


def test_cli_deletes_input_files_when_everything_was_already_logged(project: Path) -> None:
    """Checks behavior for cli deletes input files when everything was already logged."""
    input_file = project / "input/PhD/phd.csv"
    write_recipient(input_file, "PhD Co", "phd@example.com")
    with (project / "output/send_phd.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "sent_at"])
        writer.writerow(["PhD Co", "phd@example.com", "2026-04-14T10:00+10:00"])

    result = cli.main([
        "--mode",
        "PhD",
        "--base-dir",
        str(project),
        "--send",
        "--allow-empty-attachments",
        "--delete-input-after-success",
    ])

    assert result == 0
    assert not input_file.exists()


def test_cli_returns_error_when_processing_recipient_fails(monkeypatch, project: Path, capsys) -> None:
    """Checks behavior for cli returns error when processing recipient fails."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")

    def broken_render(*_args, **_kwargs):
        """Encapsulates the helper step broken_render."""
        raise ValueError("boom")

    monkeypatch.setattr("mail_sender.cli.render_mail", broken_render)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments"])

    assert result == 1
    assert "[ERROR] phd@example.com | ValueError: boom" in capsys.readouterr().out


def test_process_recipients_requires_mailer_when_not_dry_run(project: Path) -> None:
    """Checks behavior for process recipients requires mailer when not dry run."""
    invalid_log = project / "output/invalid_mails.csv"
    errors = cli._process_recipients(
        mailer=None,
        template_path=project / "templates/phd.txt",
        signature_path=project / "templates/signature.html",
        log_path=project / "output/send_phd.csv",
        invalid_log_path=invalid_log,
        recipients=[],
        attachments=[],
        subject_override=None,
        dry_run=False,
        log_dry_run=False,
        write_sent_log=False,
        verbose=False,
    )
    assert errors == 0

    errors = cli._process_recipients(
        mailer=None,
        template_path=project / "templates/phd.txt",
        signature_path=project / "templates/signature.html",
        log_path=project / "output/send_phd.csv",
        invalid_log_path=invalid_log,
        recipients=[Recipient(email="a@example.com", company="A")],
        attachments=[],
        subject_override=None,
        dry_run=False,
        log_dry_run=False,
        write_sent_log=False,
        verbose=False,
    )
    assert errors == 1
