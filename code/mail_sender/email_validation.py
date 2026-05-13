"""
Module for validating email addresses.
Checks syntax (regex), DNS records (MX/A), and optionally offers an SMTP check (RCPT TO).
"""

from __future__ import annotations

import json
import re
import smtplib
import socket
import urllib.parse
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
DEFINITE_MAILBOX_REJECT_CODES = {550, 551, 553}
NEVERBOUNCE_MAX_ATTEMPTS = 2


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
    skip_dns_check (bool): If True, skips MX/A DNS checks but still runs external validation when configured.
        require_mailbox_confirmation (bool): If True, unconfirmed mailboxes are rejected.
        reject_catch_all (bool): If True, domains accepting random recipients are rejected.
        external_service (str): "neverbounce" or "none".
        external_api_key (str): API key for the external service.

    Returns:
        EmailValidationResult: The result of the check.
        :param skip_dns_check:
        :param require_mailbox_confirmation:
        :param reject_catch_all:
        :param external_service:
        :param external_api_key:
    """
    normalized = email.strip().lower()
    if not EMAIL_PATTERN.match(normalized):
        return EmailValidationResult(False, "invalid email syntax")

    domain = normalized.rsplit("@", 1)[1]
    if domain.startswith("-") or domain.endswith("-") or ".." in domain:
        return EmailValidationResult(False, "invalid email domain syntax")

    # 1. DNS check
    mx_hosts = _mail_exchange_hosts(domain)
    if not skip_dns_check and not mx_hosts and not _domain_has_a_record(domain):
        return EmailValidationResult(False, "domain has no MX or A record")

    # 2. External service check after syntax and MX/A checks.
    if external_service != "none" and external_api_key:
        print(f"[VERBOSE] Using external validation service: {external_service} for {normalized}")
        ext_res = _validate_external(normalized, external_service, external_api_key, smtp_timeout, reject_catch_all)
        if ext_res is not None:
            if not ext_res.is_valid:
                print(f"[VERBOSE] External service {external_service} rejected {normalized}: {ext_res.reason}")
                return ext_res
            print(f"[VERBOSE] External service {external_service} confirmed {normalized} as valid.")
        else:
            print(f"[VERBOSE] External service {external_service} returned unknown result or error; falling back to local checks.")

    if skip_dns_check:
        return EmailValidationResult(True)

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


def validate_email_addresses_with_neverbounce(
        emails: list[str],
        api_key: str,
        request_timeout: float = 15.0,
) -> dict[str, EmailValidationResult]:
    """
    Validates final filtered recipients sequentially through NeverBounce single checks.

    The caller is expected to pass only the final deduplicated emails that are still
    eligible for sending. Every returned key is a normalized lower-case email address.
    """
    normalized_emails = [email.strip().lower() for email in emails if email.strip()]
    if not normalized_emails:
        return {}

    results: dict[str, EmailValidationResult] = {}
    for email in normalized_emails:
        result = _validate_neverbounce(email, api_key, request_timeout)
        results[email] = result or EmailValidationResult(False, "NeverBounce: missing result")
    return results


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


def _read_json_response(request: urllib.request.Request, timeout: float) -> dict:
    """Open an HTTP request and decode the JSON body."""
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _validate_external(email: str, service: str, api_key: str, timeout: float, reject_catch_all: bool = False) -> EmailValidationResult | None:
    """Uses NeverBounce to validate the email."""
    if service == "neverbounce":
        return _validate_neverbounce(email, api_key, timeout, reject_catch_all)
    return None


def _validate_neverbounce(email: str, api_key: str, timeout: float, reject_catch_all: bool = False) -> EmailValidationResult | None:
    """Calls the NeverBounce V4 API."""
    query = urllib.parse.urlencode({"key": api_key, "email": email})
    url = f"https://api.neverbounce.com/v4.2/single/check?{query}"
    last_timeout: BaseException | None = None
    for attempt in range(1, NEVERBOUNCE_MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                if data.get("status") == "error":
                    message = data.get("message", "unknown error")
                    print(f"[ERROR] NeverBounce API error: {message}")
                    return EmailValidationResult(False, f"NeverBounce API error: {message}")

                result = data.get("result", "").lower()
                validation = _neverbounce_result_to_validation(result)
                if result in {"catchall", "catch-all"} and reject_catch_all:
                    return EmailValidationResult(False, "NeverBounce: catchall (rejected by settings)")
                return validation

        except Exception as e:
            if _is_timeout_error(e) and attempt < NEVERBOUNCE_MAX_ATTEMPTS:
                last_timeout = e
                print(f"[WARN] NeverBounce timeout for {email}; retrying once.")
                continue
            print(f"[ERROR] NeverBounce connection failed: {e}")
            return EmailValidationResult(False, f"NeverBounce connection failed: {e}")

    if last_timeout is not None:
        print(f"[ERROR] NeverBounce connection failed: {last_timeout}")
        return EmailValidationResult(False, f"NeverBounce connection failed: {last_timeout}")
    return EmailValidationResult(False, "NeverBounce: empty response")


def _is_timeout_error(exc: BaseException) -> bool:
    """Return True for timeout exceptions raised directly or wrapped by urllib."""
    if isinstance(exc, TimeoutError | socket.timeout):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return isinstance(reason, TimeoutError | socket.timeout)
    return False


def _neverbounce_result_to_validation(result: str) -> EmailValidationResult:
    """Map a NeverBounce result code to the sender's strict valid-or-invalid policy."""
    normalized = result.strip().lower()
    if normalized in {"valid", "catchall", "catch-all"}:
        return EmailValidationResult(True)
    if not normalized:
        return EmailValidationResult(False, "NeverBounce: empty result")
    return EmailValidationResult(False, f"NeverBounce: {normalized}")
