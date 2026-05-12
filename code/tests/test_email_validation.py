"""Tests and helpers for tests/test_email_validation.py."""

from __future__ import annotations

import builtins
import socket
import sys
import types as py_types

from mail_sender import email_validation


def test_validate_email_address_rejects_bad_syntax() -> None:
    """Checks behavior for validate email address rejects bad syntax."""
    result = email_validation.validate_email_address("not-an-email")

    assert result.is_valid is False
    assert result.reason == "invalid email syntax"


def test_validate_email_address_rejects_bad_domain_syntax() -> None:
    """Checks behavior for validate email address rejects bad domain syntax."""
    result = email_validation.validate_email_address("person@bad..example.com")

    assert result.is_valid is False
    assert result.reason == "invalid email domain syntax"


def test_validate_email_address_accepts_domain_with_dns(monkeypatch) -> None:
    """Checks behavior for validate email address accepts domain with dns."""
    monkeypatch.setattr(email_validation, "_mail_exchange_hosts", lambda domain: ["mx.example.com"] if domain == "example.com" else [])

    result = email_validation.validate_email_address("Person@Example.com")

    assert result.is_valid is True
    assert result.reason == ""


def test_validate_email_address_rejects_domain_without_dns(monkeypatch) -> None:
    """Checks behavior for validate email address rejects domain without dns."""
    monkeypatch.setattr(email_validation, "_mail_exchange_hosts", lambda domain: [])
    monkeypatch.setattr(email_validation, "_domain_has_a_record", lambda domain: False)

    result = email_validation.validate_email_address("person@example.invalid")

    assert result.is_valid is False
    assert result.reason == "domain has no MX or A record"


def test_validate_email_address_skips_dns_when_requested() -> None:
    # No mocks needed as we skip the DNS part
    """Prueft das Verhalten fuer validate email address skips dns when requested."""
    result = email_validation.validate_email_address("person@example.invalid", skip_dns_check=True)

    assert result.is_valid is True
    assert result.reason == ""


def test_domain_has_a_record_uses_socket(monkeypatch) -> None:
    """Prueft das Verhalten fuer domain has a record uses socket."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda domain, port: [("ok",)])
    assert email_validation._domain_has_a_record("example.com") is True

    def fail(*_args, **_kwargs):
        """Kapselt den Hilfsschritt fail."""
        raise socket.gaierror()

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert email_validation._domain_has_a_record("missing.invalid") is False


def test_domain_accepts_mail_falls_back_when_dns_package_is_missing(monkeypatch) -> None:
    """Prueft das Verhalten fuer domain accepts mail falls back when dns package is missing."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        """Kapselt den Hilfsschritt fake_import."""
        if name == "dns.resolver":
            raise ImportError("dns unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(email_validation, "_domain_has_a_record", lambda domain: domain == "example.com")

    assert email_validation._domain_accepts_mail("example.com") is True


def test_validate_email_address_can_probe_mailbox_rejects(monkeypatch) -> None:
    """Prueft das Verhalten fuer validate email address can probe mailbox rejects."""
    monkeypatch.setattr(email_validation, "_mail_exchange_hosts", lambda domain: ["mx.example.com"])
    monkeypatch.setattr(
        email_validation,
        "_probe_mailbox_exists",
        lambda email, hosts, from_email, timeout: email_validation.EmailValidationResult(False, "user unknown"),
    )

    result = email_validation.validate_email_address("missing@example.com", verify_mailbox=True)

    assert result.is_valid is False
    assert result.reason == "user unknown"


def test_validate_email_address_can_require_positive_smtp_confirmation(monkeypatch) -> None:
    """Checks that strict validation rejects inconclusive SMTP mailbox probes."""
    monkeypatch.setattr(email_validation, "_mail_exchange_hosts", lambda domain: ["mx.example.com"])
    monkeypatch.setattr(email_validation, "_probe_mailbox_exists", lambda *args: None)

    result = email_validation.validate_email_address(
        "person@example.com",
        require_mailbox_confirmation=True,
    )

    assert result.is_valid is False
    assert result.reason == "mailbox could not be confirmed by SMTP"


def test_validate_email_address_can_reject_catch_all_domains(monkeypatch) -> None:
    """Checks that catch-all domains are rejected in conservative mode."""
    monkeypatch.setattr(email_validation, "_mail_exchange_hosts", lambda domain: ["mx.example.com"])
    monkeypatch.setattr(
        email_validation,
        "_probe_mailbox_exists",
        lambda *args: email_validation.EmailValidationResult(True),
    )

    result = email_validation.validate_email_address(
        "person@example.com",
        verify_mailbox=True,
        reject_catch_all=True,
    )

    assert result.is_valid is False
    assert result.reason == "domain accepts random mailboxes (catch-all); recipient existence cannot be confirmed"


def test_probe_mailbox_accepts_definitive_smtp_responses(monkeypatch) -> None:
    """Prueft das Verhalten fuer probe mailbox accepts definitive smtp responses."""

    class FakeSmtp:
        """Dokumentiert die Test- oder Hilfsklasse FakeSmtp."""

        def __init__(self, host, port, timeout):
            """Initialisiert oder verwaltet das Testobjekt."""
            assert (host, port, timeout) == ("mx.example.com", 25, 3)

        def __enter__(self):
            """Initialisiert oder verwaltet das Testobjekt."""
            return self

        def __exit__(self, exc_type, exc, traceback):
            """Initialisiert oder verwaltet das Testobjekt."""
            return None

        def ehlo_or_helo_if_needed(self):
            """Kapselt den Hilfsschritt ehlo_or_helo_if_needed."""
            pass

        def mail(self, sender):
            """Kapselt den Hilfsschritt mail."""
            pass

        @staticmethod
        def rcpt(email):
            """Simuliert eine endgueltige SMTP-Mailbox-Ablehnung."""
            assert email == "missing@example.com"
            return 550, "user unknown"

    monkeypatch.setattr(email_validation.smtplib, "SMTP", FakeSmtp)

    result = email_validation._probe_mailbox_exists(
        "missing@example.com",
        ["mx.example.com"],
        "sender@example.com",
        3,
    )

    assert result == email_validation.EmailValidationResult(False, "user unknown")


def test_domain_accepts_mail_uses_mx_and_falls_back_on_resolver_error(monkeypatch) -> None:
    """Prueft das Verhalten fuer domain accepts mail uses mx and falls back on resolver error."""

    class FakeAnswer:
        """Dokumentiert die Test- oder Hilfsklasse FakeAnswer."""
        exchange = "mail.example.com."

    class FakeResolver:
        """Dokumentiert die Test- oder Hilfsklasse FakeResolver."""
        lifetime = 0
        timeout = 0

        @staticmethod
        def resolve(domain, record_type):
            """Kapselt den Hilfsschritt resolve."""
            assert domain == "example.com"
            assert record_type == "MX"
            return [FakeAnswer()]

    fake_resolver_module = py_types.ModuleType("dns.resolver")
    fake_resolver_module.Resolver = FakeResolver
    fake_dns_module = py_types.ModuleType("dns")
    fake_dns_module.resolver = fake_resolver_module
    monkeypatch.setitem(sys.modules, "dns", fake_dns_module)
    monkeypatch.setitem(sys.modules, "dns.resolver", fake_resolver_module)

    assert email_validation._domain_accepts_mail("example.com") is True

    class BrokenResolver(FakeResolver):
        """Dokumentiert die Test- oder Hilfsklasse BrokenResolver."""

        @staticmethod
        def resolve(domain, record_type):
            """Kapselt den Hilfsschritt resolve."""
            raise RuntimeError("resolver down")

    fake_resolver_module.Resolver = BrokenResolver
    monkeypatch.setattr(email_validation, "_domain_has_a_record", lambda domain: domain == "example.com")

    assert email_validation._domain_accepts_mail("example.com") is True


def test_validate_email_address_runs_external_service_when_dns_check_is_skipped(monkeypatch):
    """Checks that skip_dns_check does not disable selected external validation."""
    from mail_sender.email_validation import validate_email_address

    calls = []

    def fake_external(email, service, api_key, timeout, reject_catch_all):
        calls.append((email, service, api_key, timeout, reject_catch_all))
        return email_validation.EmailValidationResult(False, "NeverBounce: invalid")

    monkeypatch.setattr(email_validation, "_validate_external", fake_external)

    res = validate_email_address(
        "invalid@example.com",
        skip_dns_check=True,
        external_service="neverbounce",
        external_api_key="never-key",
    )

    assert res.is_valid is False
    assert res.reason == "NeverBounce: invalid"
    assert calls == [("invalid@example.com", "neverbounce", "never-key", 8.0, False)]


def test_validate_email_address_uses_external_neverbounce(monkeypatch):
    """Checks that NeverBounce API is called when configured."""
    from mail_sender.email_validation import validate_email_address
    import json
    import urllib.parse
    import urllib.request

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def read(self):
            return json.dumps(self.data).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def mock_urlopen(url, timeout=None):
        if "neverbounce.com" in url:
            email = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("email", [""])[0]
            if email == "invalid@example.com":
                return FakeResponse({"result": "invalid"})
            if email == "disposable@example.com":
                return FakeResponse({"result": "disposable"})
            if email == "spamtrap@example.com":
                return FakeResponse({"result": "spamtrap"})
            if email == "catchall@example.com":
                return FakeResponse({"result": "catchall"})
            if email == "unknown@example.com":
                return FakeResponse({"result": "unknown"})
            if email == "error@example.com":
                return FakeResponse({"status": "error", "message": "Invalid API key"})
            return FakeResponse({"result": "valid"})
        return FakeResponse({"result": "valid"})

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = validate_email_address(
        "invalid@example.com",
        external_service="neverbounce",
        external_api_key="fake_key"
    )
    assert res.is_valid is False
    assert "NeverBounce: invalid" in res.reason

    res = validate_email_address(
        "disposable@example.com",
        external_service="neverbounce",
        external_api_key="fake_key"
    )
    assert res.is_valid is False
    assert "NeverBounce: disposable" in res.reason

    for address, reason in (
            ("spamtrap@example.com", "NeverBounce: spamtrap"),
            ("catchall@example.com", "NeverBounce: catchall"),
            ("unknown@example.com", "NeverBounce: unknown"),
            ("error@example.com", "NeverBounce API error: Invalid API key"),
    ):
        res = validate_email_address(
            address,
            external_service="neverbounce",
            external_api_key="fake_key",
        )
        assert res.is_valid is False
        assert reason in res.reason
