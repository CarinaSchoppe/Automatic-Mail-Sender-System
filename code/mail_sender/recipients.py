from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

EMAIL_KEYS = {"email", "e-mail", "mail", "emailaddress"}
COMPANY_KEYS = {"company", "organization"}
RECIPIENT_FILE_SUFFIXES = {".csv", ".txt"}


@dataclass(frozen=True)
class Recipient:
    email: str
    company: str = ""

    @property
    def greeting(self) -> str:
        return "Hello"

    @property
    def company_or_email(self) -> str:
        return self.company or self.email

    def template_context(self) -> dict[str, str]:
        context = {
            "email": self.email,
            "mail": self.email,
            "company": self.company,
            "greeting": self.greeting,
            "company_or_email": self.company_or_email,
        }
        return context


def read_recipients(path: Path) -> list[Recipient]:
    if not path.exists():
        raise FileNotFoundError(f"Recipient file not found: {path}")

    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError(f"Recipient file is empty: {path}")

    dialect = _detect_dialect(text)
    rows = list(csv.reader(text.splitlines(), dialect))
    rows = [[cell.strip() for cell in row] for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError(f"Recipient file has no usable rows: {path}")

    return _read_with_header(rows)


def read_recipients_from_dir(directory: Path) -> list[Recipient]:
    if not directory.exists():
        raise FileNotFoundError(f"Recipient input directory not found: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Recipient input path is not a directory: {directory}")

    files = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in RECIPIENT_FILE_SUFFIXES
    )
    if not files:
        raise FileNotFoundError(f"No .csv or .txt recipient files found in {directory}")

    recipients: list[Recipient] = []
    for path in files:
        recipients.extend(read_recipients(path))
    return recipients


def list_recipient_files(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []

    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in RECIPIENT_FILE_SUFFIXES
    )


class DefaultCsvDialect(csv.Dialect):
    """Standard CSV dialect (equivalent to Excel) without using the Excel name."""
    delimiter = ','
    quotechar = '"'
    doublequote = True
    skipinitialspace = False
    lineterminator = '\r\n'
    quoting = csv.QUOTE_MINIMAL


def _detect_dialect(text: str) -> csv.Dialect | type[csv.Dialect]:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        return DefaultCsvDialect


def _read_with_header(rows: list[list[str]]) -> list[Recipient]:
    header = [normalize_key(value) for value in rows[0]]
    if not set(header) & EMAIL_KEYS:
        raise ValueError("recipients.csv must have a mail column.")
    if not set(header) & COMPANY_KEYS:
        raise ValueError("recipients.csv must have a company column.")

    recipients: list[Recipient] = []

    for line_number, row in enumerate(rows[1:], start=2):
        values = {header[index]: value.strip() for index, value in enumerate(row) if index < len(header)}
        email = normalize_email(_first_value(values, EMAIL_KEYS))
        if not email:
            raise ValueError(f"Missing email address in recipients.csv line {line_number}.")
        if not _validate_email(email):
            raise ValueError(f"Invalid email address in recipients.csv line {line_number}: {email}")

        recipients.append(
            Recipient(
                email=email,
                company=_first_value(values, COMPANY_KEYS),
            )
        )

    return recipients


def _first_value(values: dict[str, str], keys: set[str]) -> str:
    for key in keys:
        value = values.get(key, "").strip()
        if value:
            return value
    return ""


def normalize_key(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(" ", "")


def normalize_email(value: str) -> str:
    email = value.strip()
    if email.lower().startswith("mailto:"):
        email = email[7:].strip()
    return email


def _validate_email(email: str) -> bool:
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        return False
    return True
