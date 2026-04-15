from __future__ import annotations

import csv
from pathlib import Path

from mail_sender.recipients import Recipient
from mail_sender.sent_log import (
    append_invalid_email,
    append_log,
    read_invalid_emails,
    read_known_output_emails,
    read_logged_emails,
    read_logged_rows,
)


def test_append_log_creates_three_column_output(tmp_path: Path) -> None:
    log_path = tmp_path / "output/send_phd.csv"

    append_log(log_path, Recipient(email="person@example.com", company="ACME"))

    with log_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = list(csv.reader(f))
        assert len(reader[0]) == 3
        assert reader[0] == ["company", "mail", "sent_at"]
        assert reader[1][:2] == ["ACME", "person@example.com"]
        assert "+10:00" in reader[1][2]

    assert read_logged_emails(log_path) == {"person@example.com"}
    assert read_logged_rows(log_path) == [{"company": "ACME", "mail": "person@example.com"}]


def test_read_logged_emails_normalizes_mailto_and_handles_missing_headers(tmp_path: Path) -> None:
    assert read_logged_emails(tmp_path / "missing.csv") == set()

    log_path = tmp_path / "send.csv"
    with log_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail"])
        writer.writerow(["ACME", "mailto:person@example.com"])
        writer.writerow(["Blank", ""])

    assert read_logged_emails(log_path) == {"person@example.com"}

    no_mail = tmp_path / "no-mail.csv"
    with no_mail.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company"])
    assert read_logged_emails(no_mail) == set()


def test_append_log_uses_correct_headers_even_if_file_empty(tmp_path: Path) -> None:
    log_path = tmp_path / "send.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch()

    append_log(log_path, Recipient(email="new@example.com", company="New"))

    with log_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = list(csv.reader(f))
        assert reader[0] == ["company", "mail", "sent_at"]
        assert reader[1][:2] == ["New", "new@example.com"]


def test_invalid_email_log_and_known_output_email_scan(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    sent_path = output_dir / "send_phd.csv"
    invalid_path = output_dir / "invalid_mails.csv"

    append_log(sent_path, Recipient(email="sent@example.com", company="Sent"))
    append_invalid_email(invalid_path, Recipient(email="bad@example.invalid", company="Bad"), "domain has no MX or A record")

    with invalid_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = list(csv.reader(f))
        assert reader[0] == [
            "company",
            "mail",
            "invalid_reason",
            "detected_at",
        ]
    assert read_invalid_emails(invalid_path) == {"bad@example.invalid"}
    assert read_known_output_emails(output_dir) == {"sent@example.com"}


def test_known_output_email_scan_handles_missing_output_dir(tmp_path: Path) -> None:
    assert read_known_output_emails(tmp_path / "missing-output") == set()
