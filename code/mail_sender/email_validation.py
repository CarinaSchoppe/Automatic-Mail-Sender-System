"""
Modul zur Validierung von E-Mail-Adressen.
Prüft die Syntax (Regex), DNS-Einträge (MX/A) und bietet optional eine SMTP-Prüfung (RCPT TO) an.
"""

from __future__ import annotations

import re
import smtplib
import socket
from dataclasses import dataclass

EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
DEFINITE_MAILBOX_REJECT_CODES = {550, 551, 553}


@dataclass(frozen=True)
class EmailValidationResult:
    """
    Ergebnisobjekt einer E-Mail-Validierung.
    """
    is_valid: bool
    reason: str = ""


def validate_email_address(
        email: str,
        verify_mailbox: bool = False,
        smtp_from_email: str = "postmaster@localhost",
        smtp_timeout: float = 8.0,
        skip_dns_check: bool = False,
) -> EmailValidationResult:
    """
    Führt eine mehrstufige Validierung einer E-Mail-Adresse durch.

    Args:
        email (str): Die zu prüfende Adresse.
        verify_mailbox (bool): Ob eine SMTP-Anfrage an den Mailserver gestellt werden soll.
        smtp_from_email (str): Absender-Adresse für die SMTP-Prüfung.
        smtp_timeout (float): Zeitlimit für die Netzwerk-Anfragen.
        skip_dns_check (bool): Wenn True, wird nur die Syntax geprüft.

    Returns:
        EmailValidationResult: Das Ergebnis der Prüfung.
    """
    normalized = email.strip().lower()
    if not EMAIL_PATTERN.match(normalized):
        return EmailValidationResult(False, "invalid email syntax")

    domain = normalized.rsplit("@", 1)[1]
    if domain.startswith("-") or domain.endswith("-") or ".." in domain:
        return EmailValidationResult(False, "invalid email domain syntax")

    if skip_dns_check:
        return EmailValidationResult(True)

    mx_hosts = _mail_exchange_hosts(domain)
    if not mx_hosts and not _domain_has_a_record(domain):
        return EmailValidationResult(False, "domain has no MX or A record")

    if verify_mailbox:
        probe = _probe_mailbox_exists(normalized, mx_hosts or [domain], smtp_from_email, smtp_timeout)
        if probe is not None:
            return probe

    return EmailValidationResult(True)


def _domain_accepts_mail(domain: str) -> bool:
    """Prüft, ob eine Domain per MX- oder A-Record grundsätzlich Mail annehmen kann."""
    return bool(_mail_exchange_hosts(domain)) or _domain_has_a_record(domain)


def _mail_exchange_hosts(domain: str) -> list[str]:
    """Liest MX-Hosts einer Domain sortiert nach Priorität aus."""
    try:
        import dns.resolver
        import dns.exception
    except ImportError:
        return []

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5
    resolver.timeout = 3

    try:
        answers = resolver.resolve(domain, "MX")
        hosts = [
            str(answer.exchange).strip(".")
            for answer in sorted(answers, key=lambda answer: int(getattr(answer, "preference", 0)))
            if str(answer.exchange).strip(".")
        ]
        return [host for host in hosts if host != "."]
    except Exception:
        return []


def _domain_has_a_record(domain: str) -> bool:
    """Prüft, ob die Domain wenigstens auf eine IP-Adresse auflöst."""
    try:
        socket.getaddrinfo(domain, None)
    except socket.gaierror:
        return False
    return True


def _probe_mailbox_exists(email: str, mx_hosts: list[str], smtp_from_email: str, timeout: float) -> EmailValidationResult | None:
    """Fragt bis zu drei Mailserver per RCPT TO nach eindeutigen Mailbox-Ablehnungen."""
    for host in mx_hosts[:3]:
        try:
            with smtplib.SMTP(host, 25, timeout=timeout) as smtp:
                smtp.ehlo_or_helo_if_needed()
                smtp.mail(smtp_from_email)
                code, message = smtp.rcpt(email)
        except (OSError, smtplib.SMTPException):
            continue
        except Exception:  # Fallback for unexpected socket or SMTP errors during probe
            continue

        if code in DEFINITE_MAILBOX_REJECT_CODES:
            reason = _decode_smtp_message(message) or f"mailbox rejected by {host} with SMTP {code}"
            return EmailValidationResult(False, reason)
        if 200 <= code < 300:
            return EmailValidationResult(True)

    return None


def _decode_smtp_message(message) -> str:
    """Wandelt eine SMTP-Antwort robust in lesbaren Text um."""
    if isinstance(message, bytes):
        return message.decode("utf-8", errors="replace").strip()
    return str(message or "").strip()
