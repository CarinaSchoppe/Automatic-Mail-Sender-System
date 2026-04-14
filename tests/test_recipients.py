from __future__ import annotations

from pathlib import Path

import pytest

from mail_sender.recipients import (
    Recipient,
    list_recipient_files,
    normalize_email,
    normalize_key,
    read_recipients,
    read_recipients_from_dir,
)


def test_recipient_context_and_normalizers() -> None:
    recipient = Recipient(email="a@example.com", company="ACME")

    assert recipient.greeting == "Guten Tag"
    assert recipient.company_or_email == "ACME"
    assert Recipient(email="b@example.com").company_or_email == "b@example.com"
    assert recipient.template_context()["mail"] == "a@example.com"
    assert normalize_key("E Mail") == "email"
    assert normalize_key("e_mail") == "e-mail"
    assert normalize_email(" mailto:Person@Example.com ") == "Person@Example.com"


def test_reads_csv_and_txt_from_directory(tmp_path: Path) -> None:
    (tmp_path / "one.csv").write_text("company,mail\nOne,mailto:one@example.com\n", encoding="utf-8")
    (tmp_path / "two.txt").write_text("Unternehmen;mail\nTwo;two@example.com\n", encoding="utf-8")
    (tmp_path / "ignore.md").write_text("company,mail\nNo,no@example.com\n", encoding="utf-8")

    recipients = read_recipients_from_dir(tmp_path)

    assert list_recipient_files(tmp_path) == [tmp_path / "one.csv", tmp_path / "two.txt"]
    assert [(recipient.company, recipient.email) for recipient in recipients] == [
        ("One", "one@example.com"),
        ("Two", "two@example.com"),
    ]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("company,mail\nOne,\n", "Missing email address"),
        ("company,mail\nOne,invalid\n", "Invalid email address"),
        ("company,email_address\nOne,one@example.com\n", "must have a mail column"),
        ("mail\none@example.com\n", "must have a company column"),
    ],
)
def test_recipient_validation_errors(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "recipients.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        read_recipients(path)


def test_recipient_file_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_recipients(tmp_path / "missing.csv")

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        read_recipients(empty)

    blank = tmp_path / "blank.csv"
    blank.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        read_recipients(blank)

    separators_only = tmp_path / "separators.csv"
    separators_only.write_text(",\n,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable rows"):
        read_recipients(separators_only)

    with pytest.raises(FileNotFoundError):
        read_recipients_from_dir(tmp_path / "missing")

    file_path = tmp_path / "file.txt"
    file_path.write_text("company,mail\nA,a@example.com\n", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        read_recipients_from_dir(file_path)

    no_files = tmp_path / "emptydir"
    no_files.mkdir()
    assert list_recipient_files(tmp_path / "missing") == []
    with pytest.raises(FileNotFoundError, match="No .csv or .txt"):
        read_recipients_from_dir(no_files)
