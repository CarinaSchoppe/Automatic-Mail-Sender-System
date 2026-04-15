"""Tests und Hilfen fuer tests/test_cli.py."""

from __future__ import annotations

import csv
from pathlib import Path

from mail_sender import cli
from mail_sender.recipients import Recipient


def write_recipient(path: Path, company: str, email: str) -> None:
    """Kapselt den Hilfsschritt write_recipient."""
    path.write_text(f"company,mail\n{company},{email}\n", encoding="utf-8")


def test_cli_auto_processes_each_input_folder_and_logs_dry_run(project: Path, capsys) -> None:
    """Prueft das Verhalten fuer cli auto processes each input folder and logs dry run."""
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
    """Prueft das Verhalten fuer cli skips logged and duplicate addresses."""
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
    """Prueft das Verhalten fuer cli skips invalid addresses and persists invalid log."""
    write_recipient(project / "input/PhD/bad.csv", "Bad", "bad@example.invalid")
    write_recipient(project / "input/PhD/good.csv", "Good", "good@example.com")

    def fake_validate(email: str):
        """Kapselt den Hilfsschritt fake_validate."""
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


def test_cli_skips_addresses_already_in_invalid_log(project: Path, capsys) -> None:
    """Prueft das Verhalten fuer cli skips addresses already in invalid log."""
    write_recipient(project / "input/PhD/bad.csv", "Bad", "bad@example.invalid")
    with (project / "output/invalid_mails.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "invalid_reason", "detected_at"])
        writer.writerow(["Bad", "bad@example.invalid", "domain has no MX or A record", "2026-04-14T10:00+10:00"])

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments"])

    assert result == 0
    assert "already listed in invalid_mails.csv" in capsys.readouterr().out


def test_cli_checks_all_output_csv_logs(project: Path, capsys) -> None:
    """Prueft das Verhalten fuer cli checks all output csv logs."""
    write_recipient(project / "input/PhD/phd.csv", "Existing", "existing@example.com")
    with (project / "output/send_freelance.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "sent_at"])
        writer.writerow(["Existing", "existing@example.com", "2026-04-14T10:00+10:00"])

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments"])

    assert result == 0
    assert "already present in an output CSV log" in capsys.readouterr().out


def test_cli_returns_zero_when_all_recipients_are_logged(project: Path, capsys) -> None:
    """Prueft das Verhalten fuer cli returns zero when all recipients are logged."""
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
    """Prueft das Verhalten fuer cli returns zero when auto has no files."""
    result = cli.main(["--mode", "Auto", "--base-dir", str(project)])

    assert result == 0
    assert "No input files found" in capsys.readouterr().out


def test_cli_specific_mode_reports_missing_input_files(project: Path, capsys) -> None:
    """Prueft das Verhalten fuer cli specific mode reports missing input files."""
    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments", "--verbose"])

    assert result == 1
    output = capsys.readouterr().out
    assert "No recipient files found." in output
    assert "No .csv or .txt recipient files found" in output


def test_cli_errors_for_missing_attachments(project: Path, capsys) -> None:
    """Prueft das Verhalten fuer cli errors for missing attachments."""
    write_recipient(project / "input/Freelance_English/en.csv", "EN Co", "en@example.com")

    result = cli.main(["--mode", "Freelance_English", "--base-dir", str(project)])

    assert result == 1
    assert "No attachments found" in capsys.readouterr().out


def test_cli_resend_existing_bypasses_output_log(project: Path, capsys) -> None:
    """Prueft das Verhalten fuer cli resend existing bypasses output log."""
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
    """Prueft das Verhalten fuer cli send path uses mailer."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")
    sent = []

    class FakeMailer:
        """Dokumentiert die Test- oder Hilfsklasse FakeMailer."""

        def __init__(self, config) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.config = config

        def __enter__(self):
            """Initialisiert oder verwaltet das Testobjekt."""
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            return None

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send"])

    assert result == 0
    assert sent == [("phd@example.com", "PhD PhD Co", 1, 1)]
    with (project / "output/send_phd.csv").open("r", encoding="utf-8-sig", newline="") as f:
        reader = list(csv.reader(f))
        assert reader[1][1] == "phd@example.com"


def test_cli_send_path_respects_max_send_count(monkeypatch, project: Path, capsys) -> None:
    """Prueft das Verhalten fuer cli send path respects max send count."""
    (project / "input/PhD/phd.csv").write_text(
        "company,mail\nA,a@example.com\nB,b@example.com\nC,c@example.com\n",
        encoding="utf-8",
    )
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")
    sent = []

    class FakeMailer:
        """Dokumentiert die Test- oder Hilfsklasse FakeMailer."""

        def __init__(self, config) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.config = config

        def __enter__(self):
            """Initialisiert oder verwaltet das Testobjekt."""
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            return None

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send", "--max-send-count", "2"])

    assert result == 0
    assert sent == ["a@example.com", "b@example.com"]
    assert "Limiting this run to 2 recipient(s)." in capsys.readouterr().out
    with (project / "output/send_phd.csv").open("r", encoding="utf-8-sig", newline="") as f:
        assert len(list(csv.reader(f))) == 3


def test_cli_parallel_send_logs_each_recipient_once(monkeypatch, project: Path) -> None:
    """Prueft das Verhalten fuer cli parallel send logs each recipient once."""
    (project / "input/PhD/phd.csv").write_text(
        "company,mail\nA,a@example.com\nB,b@example.com\nC,c@example.com\n",
        encoding="utf-8",
    )
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")
    sent = []

    class FakeMailer:
        """Dokumentiert die Test- oder Hilfsklasse FakeMailer."""

        def __init__(self, config) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.config = config

        def __enter__(self):
            """Initialisiert oder verwaltet das Testobjekt."""
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            return None

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send", "--parallel-threads", "2"])

    assert result == 0
    assert sorted(sent) == ["a@example.com", "b@example.com", "c@example.com"]
    with (project / "output/send_phd.csv").open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert sorted(row[1] for row in rows[1:]) == ["a@example.com", "b@example.com", "c@example.com"]


def test_cli_rejects_invalid_max_send_count(project: Path, capsys) -> None:
    """Prueft das Verhalten fuer cli rejects invalid max send count."""
    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--max-send-count", "0"])

    assert result == 1
    assert "--max-send-count must be at least 1" in capsys.readouterr().out


def test_cli_can_disable_sent_csv_logging(monkeypatch, project: Path) -> None:
    """Prueft das Verhalten fuer cli can disable sent csv logging."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")

    class FakeMailer:
        """Dokumentiert die Test- oder Hilfsklasse FakeMailer."""

        def __init__(self, config) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.config = config

        def __enter__(self):
            """Initialisiert oder verwaltet das Testobjekt."""
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            return None

        def send(self, *args, **kwargs):
            """Kapselt den Hilfsschritt send."""
            pass

    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("mail_sender.cli.SmtpMailer", FakeMailer)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--send", "--no-write-sent-log"])

    assert result == 0
    assert not (project / "output/send_phd.csv").exists()


def test_cli_deletes_input_files_after_successful_real_send(monkeypatch, project: Path) -> None:
    """Prueft das Verhalten fuer cli deletes input files after successful real send."""
    input_file = project / "input/PhD/phd.csv"
    write_recipient(input_file, "PhD Co", "phd@example.com")
    (project / "attachments/PhD/file.txt").write_text("attachment", encoding="utf-8")

    class FakeMailer:
        """Dokumentiert die Test- oder Hilfsklasse FakeMailer."""

        def __init__(self, config) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.config = config

        def __enter__(self):
            """Initialisiert oder verwaltet das Testobjekt."""
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            return None

        def send(self, *args, **kwargs):
            """Kapselt den Hilfsschritt send."""
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
    """Prueft das Verhalten fuer cli keeps input files after dry run and error."""
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
        """Kapselt den Hilfsschritt broken_render."""
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
    """Prueft das Verhalten fuer cli deletes input files when everything was already logged."""
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
    """Prueft das Verhalten fuer cli returns error when processing recipient fails."""
    write_recipient(project / "input/PhD/phd.csv", "PhD Co", "phd@example.com")

    def broken_render(*_args, **_kwargs):
        """Kapselt den Hilfsschritt broken_render."""
        raise ValueError("boom")

    monkeypatch.setattr("mail_sender.cli.render_mail", broken_render)

    result = cli.main(["--mode", "PhD", "--base-dir", str(project), "--allow-empty-attachments"])

    assert result == 1
    assert "[ERROR] phd@example.com | boom" in capsys.readouterr().out


def test_process_recipients_requires_mailer_when_not_dry_run(project: Path) -> None:
    """Prueft das Verhalten fuer process recipients requires mailer when not dry run."""
    errors = cli._process_recipients(
        mailer=None,
        template_path=project / "templates/phd.txt",
        signature_path=project / "templates/signature.txt",
        log_path=project / "output/send_phd.csv",
        recipients=[],
        attachments=[],
        subject_override=None,
        signature_image_path=project / "templates/signature-logo.png",
        signature_image_width=180,
        dry_run=False,
        log_dry_run=False,
        write_sent_log=False,
        verbose=False,
    )
    assert errors == 0

    errors = cli._process_recipients(
        mailer=None,
        template_path=project / "templates/phd.txt",
        signature_path=project / "templates/signature.txt",
        log_path=project / "output/send_phd.csv",
        recipients=[Recipient(email="a@example.com", company="A")],
        attachments=[],
        subject_override=None,
        signature_image_path=project / "templates/signature-logo.png",
        signature_image_width=180,
        dry_run=False,
        log_dry_run=False,
        write_sent_log=False,
        verbose=False,
    )
    assert errors == 1
