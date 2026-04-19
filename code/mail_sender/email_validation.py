"""
Module for validating email addresses.
Checks syntax (regex), DNS records (MX/A), and optionally offers an SMTP check (RCPT TO).
"""

from __future__ import annotations

import json
import re
import smtplib
import socket
import urllib.request
import uuid
from dataclasses import dataclass

EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
DEFINITE_MAILBOX_REJECT_CODES = {550, 551, 553}


@dataclass(frozen=True)
class EmailValidationResult:
    """
    Result object of an email validation.
    """
    is_valid: bool
    reason: str = ""


def validate_email_address(
        email: str,
        verify_mailbox: bool = False,
        smtp_from_email: str = "postmaster@localhost",
        smtp_timeout: float = 8.0,
        skip_dns_check: bool = False,
        require_mailbox_confirmation: bool = False,
        reject_catch_all: bool = False,
        external_service: str = "none",
        external_api_key: str = "",
) -> EmailValidationResult:
    """
    Performs a multi-stage validation of an email address.

    Args:
        email (str): The address to check.
        verify_mailbox (bool): Whether an SMTP request should be made to the mail server.
        smtp_from_email (str): Sender address for the SMTP check.
        smtp_timeout (float): Time limit for network requests.
        skip_dns_check (bool): If True, only the syntax is checked.
        require_mailbox_confirmation (bool): If True, unconfirmed mailboxes are rejected.
        reject_catch_all (bool): If True, domains accepting random recipients are rejected.
        external_service (str): "zerobounce", "neverbounce", or "none".
        external_api_key (str): API key for the external service.

    Returns:
        EmailValidationResult: The result of the check.
    """
    normalized = email.strip().lower()
    if not EMAIL_PATTERN.match(normalized):
        return EmailValidationResult(False, "invalid email syntax")

    domain = normalized.rsplit("@", 1)[1]
    if domain.startswith("-") or domain.endswith("-") or ".." in domain:
        return EmailValidationResult(False, "invalid email domain syntax")

    if skip_dns_check:
        return EmailValidationResult(True)

    # 1. External Service check (often more reliable/expensive, so maybe first or after syntax)
    if external_service != "none" and external_api_key:
        ext_res = _validate_external(normalized, external_service, external_api_key, smtp_timeout)
        if ext_res is not None:
            # If the external service gives a definitive answer, we might stop here
            if not ext_res.is_valid:
                return ext_res
            # If valid, we might still want to do local checks or trust it
            return ext_res

    # 2. DNS check
    mx_hosts = _mail_exchange_hosts(domain)
    if not mx_hosts and not _domain_has_a_record(domain):
        return EmailValidationResult(False, "domain has no MX or A record")

    if verify_mailbox or require_mailbox_confirmation or reject_catch_all:
        probe = _probe_mailbox_exists(normalized, mx_hosts or [domain], smtp_from_email, smtp_timeout)
        if probe is not None and not probe.is_valid:
            return probe
        if probe is not None and probe.is_valid and reject_catch_all:
            catch_all_probe = _probe_random_mailbox(domain, mx_hosts or [domain], smtp_from_email, smtp_timeout)
            if catch_all_probe is not None and catch_all_probe.is_valid:
                return EmailValidationResult(
                    False,
                    "domain accepts random mailboxes (catch-all); recipient existence cannot be confirmed",
                )
        if probe is not None:
            return probe
        if require_mailbox_confirmation:
            return EmailValidationResult(False, "mailbox could not be confirmed by SMTP")

    return EmailValidationResult(True)


def _domain_accepts_mail(domain: str) -> bool:
    """Checks if a domain can generally accept mail via MX or A record."""
    return bool(_mail_exchange_hosts(domain)) or _domain_has_a_record(domain)


def _mail_exchange_hosts(domain: str) -> list[str]:
    """Reads MX hosts of a domain sorted by priority."""
    try:
        import dns.resolver
        from dns.exception import DNSException
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
    except (DNSException, AttributeError, RuntimeError, TypeError, ValueError):
        return []


def _domain_has_a_record(domain: str) -> bool:
    """Checks if the domain resolves to at least one IP address."""
    try:
        socket.getaddrinfo(domain, None)
    except socket.gaierror:
        return False
    return True


def _probe_mailbox_exists(email: str, mx_hosts: list[str], smtp_from_email: str, timeout: float) -> EmailValidationResult | None:
    """Queries up to three mail servers via RCPT TO for definitive mailbox rejections."""
    for host in mx_hosts[:3]:
        try:
            with smtplib.SMTP(host, 25, timeout=timeout) as smtp:
                smtp.ehlo_or_helo_if_needed()
                smtp.mail(smtp_from_email)
                code, message = smtp.rcpt(email)
        except (OSError, TimeoutError, smtplib.SMTPException):
            continue

        if code in DEFINITE_MAILBOX_REJECT_CODES:
            reason = _decode_smtp_message(message) or f"mailbox rejected by {host} with SMTP {code}"
            return EmailValidationResult(False, reason)
        if 200 <= code < 300:
            return EmailValidationResult(True)

    return None


def _probe_random_mailbox(domain: str, mx_hosts: list[str], smtp_from_email: str, timeout: float) -> EmailValidationResult | None:
    """Checks whether a domain accepts an invented random local part."""
    random_email = f"mail-sender-validation-{uuid.uuid4().hex}@{domain}"
    return _probe_mailbox_exists(random_email, mx_hosts, smtp_from_email, timeout)


def _decode_smtp_message(message) -> str:
    """Robustly converts an SMTP response into readable text."""
    if isinstance(message, bytes):
        return message.decode("utf-8", errors="replace").strip()
    return str(message or "").strip()


def _validate_external(email: str, service: str, api_key: str, timeout: float) -> EmailValidationResult | None:
    """Uses an external API (ZeroBounce or NeverBounce) to validate the email."""
    if service == "zerobounce":
        return _validate_zerobounce(email, api_key, timeout)
    if service == "neverbounce":
        return _validate_neverbounce(email, api_key, timeout)
    return None


def _validate_zerobounce(email: str, api_key: str, timeout: float) -> EmailValidationResult | None:
    """Calls the ZeroBounce V2 API."""
    url = f"https://api.zerobounce.net/v2/validate?api_key={api_key}&email={email}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            status = data.get("status", "").lower()
            if status == "valid":
                return EmailValidationResult(True)
            if status in ("invalid", "do_not_mail", "spamtrap"):
                reason = data.get("sub_status", status)
                return EmailValidationResult(False, f"ZeroBounce: {reason}")
            # 'unknown' or 'catch-all' (if not rejected) could be handled here
    except Exception as e:
        # We don't want to fail the whole process if the API is down, 
        # but maybe we should log it. Returning None falls back to local checks.
        pass
    return None


def _validate_neverbounce(email: str, api_key: str, timeout: float) -> EmailValidationResult | None:
    """Calls the NeverBounce V4 API."""
    url = f"https://api.neverbounce.com/v4/single/check?key={api_key}&email={email}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            result = data.get("result", "").lower()
            if result == "valid":
                return EmailValidationResult(True)
            if result in ("invalid", "disposable", "spamtrap"):
                return EmailValidationResult(False, f"NeverBounce: {result}")
    except Exception:
        pass
    return None
