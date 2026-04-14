from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


EMAIL_KEYS = {"email", "e-mail", "mail", "emailadresse", "e-mail-adresse", "emailaddress"}
COMPANY_KEYS = {"company", "unternehmen", "firma", "organisation", "organization"}


@dataclass(frozen=True)
class Recipient:
    email: str
    company: str = ""

    @property
    def greeting(self) -> str:
        return "Guten Tag"

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


def _detect_dialect(text: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _read_with_header(rows: list[list[str]]) -> list[Recipient]:
    header = [normalize_key(value) for value in rows[0]]
    if not set(header) & EMAIL_KEYS:
        raise ValueError("recipients.csv must have a mail column.")
    if not set(header) & COMPANY_KEYS:
        raise ValueError("recipients.csv must have a company column.")

    recipients: list[Recipient] = []

    for line_number, row in enumerate(rows[1:], start=2):
        values = {header[index]: value.strip() for index, value in enumerate(row) if index < len(header)}
        email = _first_value(values, EMAIL_KEYS)
        if not email:
            raise ValueError(f"Missing email address in recipients.csv line {line_number}.")
        _validate_email(email, line_number)

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


def _validate_email(email: str, line_number: int) -> None:
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError(f"Invalid email address in recipients.csv line {line_number}: {email}")
