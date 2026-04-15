from __future__ import annotations

import re
import smtplib
import socket
from dataclasses import dataclass

EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
DEFINITE_MAILBOX_REJECT_CODES = {550, 551, 553}


@dataclass(frozen=True)
class EmailValidationResult:
    is_valid: bool
    reason: str = ""


def validate_email_address(
        email: str,
        verify_mailbox: bool = False,
        smtp_from_email: str = "postmaster@localhost",
        smtp_timeout: float = 8.0,
) -> EmailValidationResult:
    normalized = email.strip().lower()
    if not EMAIL_PATTERN.match(normalized):
        return EmailValidationResult(False, "invalid email syntax")

    domain = normalized.rsplit("@", 1)[1]
    if domain.startswith("-") or domain.endswith("-") or ".." in domain:
        return EmailValidationResult(False, "invalid email domain syntax")
    mx_hosts = _mail_exchange_hosts(domain)
    if not mx_hosts and not _domain_has_a_record(domain):
        return EmailValidationResult(False, "domain has no MX or A record")

    if verify_mailbox:
        probe = _probe_mailbox_exists(normalized, mx_hosts or [domain], smtp_from_email, smtp_timeout)
        if probe is not None:
            return probe

    return EmailValidationResult(True)


def _domain_accepts_mail(domain: str) -> bool:
    return bool(_mail_exchange_hosts(domain)) or _domain_has_a_record(domain)


def _mail_exchange_hosts(domain: str) -> list[str]:
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
    except dns.exception.DNSException:
        return []


def _domain_has_a_record(domain: str) -> bool:
    try:
        socket.getaddrinfo(domain, None)
    except socket.gaierror:
        return False
    return True


def _probe_mailbox_exists(email: str, mx_hosts: list[str], smtp_from_email: str, timeout: float) -> EmailValidationResult | None:
    for host in mx_hosts[:3]:
        try:
            with smtplib.SMTP(host, 25, timeout=timeout) as smtp:
                smtp.ehlo_or_helo_if_needed()
                smtp.mail(smtp_from_email)
                code, message = smtp.rcpt(email)
        except (OSError, smtplib.SMTPException):
            continue

        if code in DEFINITE_MAILBOX_REJECT_CODES:
            reason = _decode_smtp_message(message) or f"mailbox rejected by {host} with SMTP {code}"
            return EmailValidationResult(False, reason)
        if 200 <= code < 300:
            return EmailValidationResult(True)

    return None


def _decode_smtp_message(message) -> str:
    if isinstance(message, bytes):
        return message.decode("utf-8", errors="replace").strip()
    return str(message or "").strip()
