from __future__ import annotations

import re
import socket
from dataclasses import dataclass


EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)


@dataclass(frozen=True)
class EmailValidationResult:
    is_valid: bool
    reason: str = ""


def validate_email_address(email: str) -> EmailValidationResult:
    normalized = email.strip().lower()
    if not EMAIL_PATTERN.match(normalized):
        return EmailValidationResult(False, "invalid email syntax")

    domain = normalized.rsplit("@", 1)[1]
    if domain.startswith("-") or domain.endswith("-") or ".." in domain:
        return EmailValidationResult(False, "invalid email domain syntax")
    if not _domain_accepts_mail(domain):
        return EmailValidationResult(False, "domain has no MX or A record")

    return EmailValidationResult(True)


def _domain_accepts_mail(domain: str) -> bool:
    try:
        import dns.resolver
    except ImportError:
        return _domain_has_a_record(domain)

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5
    resolver.timeout = 3

    try:
        answers = resolver.resolve(domain, "MX")
        if any(str(answer.exchange).strip(".") for answer in answers):
            return True
    except Exception:
        pass

    return _domain_has_a_record(domain)


def _domain_has_a_record(domain: str) -> bool:
    try:
        socket.getaddrinfo(domain, None)
    except socket.gaierror:
        return False
    return True
