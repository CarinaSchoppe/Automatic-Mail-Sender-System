"""
Modul zum Parsen von KI-Antworten in verschiedenen Formaten (CSV, JSON, Headerless).
Beinhaltet Logik zur Bereinigung von Markdown-Codeblöcken und zur Normalisierung von Daten.
"""

from __future__ import annotations

import csv
import json
import re

from mail_sender.recipients import COMPANY_KEYS, EMAIL_KEYS, Recipient, normalize_email, normalize_key

SOURCE_KEYS = {"source", "source-url", "source_url", "sourceurl", "url", "website"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COMPANY_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")


class DefaultCsvDialect(csv.Dialect):
    """
    Ein robuster Standard-CSV-Dialekt, der verwendet wird, wenn die automatische
    Erkennung (Sniffer) fehlschlägt.
    """
    delimiter = ","
    quotechar = '"'
    doublequote = True
    skipinitialspace = False
    lineterminator = "\r\n"
    quoting = csv.QUOTE_MINIMAL


def parse_recipients(
        raw_response: str,
        existing_emails: set[str],
        existing_companies: set[str] | None = None,
        verbose: bool = False,
) -> list[Recipient]:
    """
    Versucht, Empfänger-Informationen aus einem rohen Text (KI-Antwort) zu extrahieren.
    Probiert nacheinander CSV mit Header, Headerless CSV und JSON.

    Args:
        raw_response (str): Der rohe Text von der KI.
        existing_emails (set[str]): Menge bereits bekannter E-Mails zur Duplikatprüfung.
        existing_companies (set[str] | None): Menge bereits bekannter Firmen.
        verbose (bool): Aktiviert detaillierte Protokollierung.

    Returns:
        list[Recipient]: Eine Liste der erfolgreich parsierten und validierten Empfänger.
    """
    if isinstance(existing_companies, bool):
        verbose = existing_companies
        existing_companies = None
    _verbose(verbose, f"Parsing AI response with {len(raw_response)} character(s).")
    csv_text = strip_csv_fence(raw_response)
    _verbose(verbose, f"CSV candidate text length after fence stripping: {len(csv_text)}.")
    rows = list(csv.DictReader(csv_text.splitlines(), dialect=detect_dialect(csv_text))) if csv_text.strip() else []
    _verbose(verbose, f"CSV DictReader row count: {len(rows)}.")
    if rows:
        company_field = find_field(rows[0], COMPANY_KEYS)
        email_field = find_field(rows[0], EMAIL_KEYS)
        _verbose(verbose, f"Detected CSV fields: company={company_field!r}, email={email_field!r}.")
        if company_field and email_field:
            source_field = find_field(rows[0], SOURCE_KEYS)
            _verbose(verbose, f"Detected CSV source field: {source_field!r}.")
            recipients = _extract_from_rows(rows, company_field, email_field, existing_emails, existing_companies, source_field, verbose)
            _verbose(verbose, f"Parsed CSV recipients: {len(recipients)}")
            return recipients

    recipients = parse_headerless_csv_recipients(csv_text, existing_emails, existing_companies, verbose)
    if recipients:
        _verbose(verbose, f"Parsed headerless CSV recipients: {len(recipients)}")
        return recipients

    recipients = parse_json_recipients(raw_response, existing_emails, existing_companies, verbose)
    if recipients:
        _verbose(verbose, f"Parsed JSON recipients: {len(recipients)}")
        return recipients

    _verbose(verbose, "No recipients could be parsed from AI response.")
    return []


def normalize_company(company: str) -> str:
    """
    Normalisiert einen Firmennamen für einen robusten Vergleich (Kleinschreibung, keine Sonderzeichen).

    Args:
        company (str): Der zu normalisierende Name.

    Returns:
        str: Der normalisierte Name.
    """
    return COMPANY_NORMALIZE_PATTERN.sub("", company.strip().lower())


def parse_headerless_csv_recipients(
        raw_text: str,
        existing_emails: set[str],
        existing_companies: set[str] | None = None,
        verbose: bool = False,
) -> list[Recipient]:
    """
    Parst CSV-Daten, die keinen Header besitzen.
    Nimmt an, dass die letzte Spalte die E-Mail ist und davor der Firmenname steht.
    """
    if isinstance(existing_companies, bool):
        verbose = existing_companies
        existing_companies = None
    text = raw_text.strip().strip("'\"`").replace("\\n", "\n")
    if not text:
        _verbose(verbose, "Headerless CSV parser skipped empty text.")
        return []

    try:
        rows = list(csv.reader(text.splitlines(), dialect=detect_dialect(text)))
    except csv.Error:
        _verbose(verbose, "Headerless CSV parser failed to read CSV rows.")
        return []

    _verbose(verbose, f"Headerless CSV row count: {len(rows)}.")
    parsed_rows: list[dict[str, str]] = []
    for row in rows:
        cells = [cell.strip().strip("'\"`") for cell in row if cell.strip()]
        if len(cells) < 2:
            _verbose(verbose, f"Headerless CSV row skipped because it has fewer than 2 cells: {row!r}.")
            continue
        email = cells[-1]
        company = ", ".join(cells[:-1]).strip()
        parsed_rows.append({"company": company, "mail": email})

    return _extract_from_rows(parsed_rows, "company", "mail", existing_emails, existing_companies, verbose=verbose)


def parse_json_recipients(
        raw_response: str,
        existing_emails: set[str],
        existing_companies: set[str] | None = None,
        verbose: bool = False,
) -> list[Recipient]:
    """
    Versucht, Empfänger aus einer JSON-Struktur zu extrahieren.
    Unterstützt Listen von Objekten oder ein Objekt mit einem "leads"-Key.
    """
    if isinstance(existing_companies, bool):
        verbose = existing_companies
        existing_companies = None
    payload_text = strip_json_fence(raw_response)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        _verbose(verbose, "JSON parser skipped response because it is not valid JSON.")
        return []

    if isinstance(payload, dict):
        lead_rows = payload.get("leads", [])
    elif isinstance(payload, list):
        lead_rows = payload
    else:
        _verbose(verbose, f"JSON parser skipped unsupported payload type: {type(payload).__name__}.")
        return []

    _verbose(verbose, f"JSON lead row count: {len(lead_rows)}.")
    rows: list[dict[str, str]] = []
    for lead in lead_rows:
        if not isinstance(lead, dict):
            continue
        company = str(lead.get("company", "")).strip()
        emails = lead.get("emails", lead.get("mail", lead.get("email", "")))
        email_values = emails if isinstance(emails, list) else [emails]
        sources = lead.get("source_urls", lead.get("source_url", lead.get("source", "")))
        source_values = sources if isinstance(sources, list) else [sources]
        source = str(source_values[0]) if source_values else ""
        for email in email_values:
            rows.append({"company": company, "mail": str(email), "source_url": source})

    return _extract_from_rows(rows, "company", "mail", existing_emails, existing_companies, "source_url", verbose)


def _extract_from_rows(
        rows: list[dict[str, str]],
        company_field: str,
        email_field: str,
        existing_emails: set[str],
        existing_companies: set[str] | None = None,
        source_field: str | None = None,
        verbose: bool = False,
) -> list[Recipient]:
    """
    Interne Hilfsfunktion zum Umwandeln von Dictionary-Zeilen in Recipient-Objekte
    inklusive Validierung und Duplikatprüfung.
    """
    recipients: list[Recipient] = []
    seen_emails = {email.lower() for email in existing_emails}
    seen_companies = {company for company in existing_companies or set() if company}

    for row in rows:
        company = str(row.get(company_field, "")).strip()
        company_key = normalize_company(company)
        email = normalize_email(str(row.get(email_field, ""))).lower()
        source_url = str(row.get(source_field, "")).strip() if source_field else ""
        if not company or not email:
            _verbose(verbose, f"Recipient row skipped because company or email is missing: {row!r}.")
            continue
        if source_field and not source_url:
            _verbose(verbose, f"Recipient row skipped because source URL is missing: {row!r}.")
            continue
        if company_key in seen_companies:
            _verbose(verbose, f"Recipient row skipped because company already exists for this mode: {company}.")
            continue
        if email in seen_emails or not EMAIL_PATTERN.match(email):
            reason = "duplicate/existing" if email in seen_emails else "invalid email format"
            _verbose(verbose, f"Recipient row skipped because of {reason}: {email}.")
            continue

        recipients.append(Recipient(email=email, company=company, source_url=source_url))
        seen_emails.add(email)
        _verbose(verbose, f"Recipient row accepted: {company} <{email}>.")

    return recipients


def strip_csv_fence(text: str) -> str:
    """
    Entfernt Markdown-Code-Fences (```csv ... ```) um einen CSV-String.
    """
    stripped = text.strip()
    matches = re.findall(r"```csv\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    for match in matches:
        candidate = match.strip()
        first_line = candidate.splitlines()[0].strip().lower() if candidate.splitlines() else ""
        if "company" in first_line and ("mail" in first_line or "email" in first_line):
            return candidate
    if matches:
        return matches[0].strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:csv|json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def strip_json_fence(text: str) -> str:
    """
    Entfernt Markdown-Code-Fences (```json ... ```) um einen JSON-String.
    """
    stripped = text.strip()
    matches = re.findall(r"```json\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if matches:
        return matches[0].strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json|csv)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def detect_dialect(text: str) -> csv.Dialect | type[csv.Dialect]:
    """
    Versucht den CSV-Dialekt (Trennzeichen etc.) automatisch zu erkennen.
    """
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        return DefaultCsvDialect


def find_field(row: dict[str, str], allowed_keys: set[str]) -> str | None:
    """
    Sucht in einem Dictionary nach einem Key, der (normalisiert) in der Menge der erlaubten Keys vorkommt.
    """
    for field in row:
        if field and normalize_key(field) in allowed_keys:
            return field
    return None


def verbose_log(enabled: bool, message: str) -> None:
    """
    Gibt eine Nachricht auf der Konsole aus, falls Verbose-Logging aktiviert ist.
    """
    if enabled:
        print(f"[VERBOSE] {message}")


_verbose = verbose_log
