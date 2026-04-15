"""CSV log helpers for sent and invalid email tracking."""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mail_sender.recipients import EMAIL_KEYS
from mail_sender.recipients import Recipient
from mail_sender.recipients import normalize_email
from mail_sender.recipients import normalize_key

HEADERS = [
    "company",
    "mail",
    "sent_at",
]

INVALID_HEADERS = [
    "company",
    "mail",
    "invalid_reason",
    "detected_at",
]

_CSV_WRITE_LOCK = threading.Lock()


def append_log(
        log_path: Path,
        recipient: Recipient,
) -> None:
    """Haengt einen Versanddatensatz an die Logdatei an."""
    _append_csv_row(log_path, HEADERS, [
        recipient.company,
        recipient.email,
        datetime.now(ZoneInfo("Australia/Brisbane")).isoformat(timespec="minutes"),
    ], unique_index=1)


def append_invalid_email(log_path: Path, recipient: Recipient, reason: str) -> None:
    """Haengt eine ungueltige E-Mail an das Fehlerlog an."""
    _append_csv_row(log_path, INVALID_HEADERS, [
        recipient.company,
        recipient.email,
        reason,
        datetime.now(ZoneInfo("Australia/Brisbane")).isoformat(timespec="minutes"),
    ], unique_index=1)


def read_logged_emails(log_path: Path) -> set[str]:
    """Liest logged E-Mails."""
    rows = read_logged_rows(log_path)
    return {row["mail"] for row in rows if row["mail"]}


def read_logged_rows(log_path: Path) -> list[dict[str, str]]:
    """Read normalized company/email rows from a sent or invalid CSV log."""
    if not log_path.exists():
        return []

    try:
        with log_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return []

            company_index = _find_header_index(header, {"company", "organization", "firma"})
            email_index = _find_header_index(header, EMAIL_KEYS)
            if email_index is None:
                return []

            rows: list[dict[str, str]] = []
            for row in reader:
                if not row:
                    continue
                company = ""
                if company_index is not None and 0 < company_index <= len(row):
                    company = row[company_index - 1].strip()

                email = ""
                if 0 < email_index <= len(row):
                    email = normalize_email(row[email_index - 1]).lower()

                rows.append({"company": company, "mail": email})
            return rows
    except (OSError, csv.Error):
        return []
    except Exception:  # Fallback for unexpected errors during read
        return []


def read_invalid_emails(log_path: Path) -> set[str]:
    """Liest ungueltige Eintraege E-Mails."""
    return read_logged_emails(log_path)


def read_known_output_emails(output_dir: Path) -> set[str]:
    """Liest bekannte Eintraege Ausgabe E-Mails."""
    if not output_dir.exists() or not output_dir.is_dir():
        return set()

    emails: set[str] = set()
    for path in output_dir.glob("*.csv"):
        if path.name.lower() == "invalid_mails.csv":
            continue
        emails.update(read_logged_emails(path))
    return emails


def _append_csv_row(path: Path, headers: list[str], row: list[str], unique_index: int | None = None) -> None:
    """Haengt eine Zeile an eine CSV-Datei an."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _CSV_WRITE_LOCK:
        file_exists = path.exists()
        if file_exists and unique_index is not None and len(row) > unique_index:
            val_to_check = row[unique_index].lower()
            try:
                # Efficiently check for existing value before opening for append
                with path.open("r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.reader(f)
                    try:
                        next(reader)  # skip header
                        for existing_row in reader:
                            if len(existing_row) > unique_index and existing_row[unique_index].lower() == val_to_check:
                                return  # Already exists
                    except StopIteration:
                        pass
            except (OSError, csv.Error):
                pass

        with path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if not file_exists or os.path.getsize(path) == 0:
                writer.writerow(headers)
            writer.writerow(row)


def _find_header_index(header: list[str], allowed_keys: set[str]) -> int | None:
    """Findet Kopfzeile index."""
    for index, value in enumerate(header, start=1):
        if normalize_key(value) in allowed_keys:
            return index
    return None
