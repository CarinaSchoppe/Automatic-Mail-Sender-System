from __future__ import annotations

import builtins
import socket
import sys
import types as py_types

from mail_sender import email_validation


def test_validate_email_address_rejects_bad_syntax() -> None:
    result = email_validation.validate_email_address("not-an-email")

    assert result.is_valid is False
    assert result.reason == "invalid email syntax"


def test_validate_email_address_rejects_bad_domain_syntax() -> None:
    result = email_validation.validate_email_address("person@bad..example.com")

    assert result.is_valid is False
    assert result.reason == "invalid email domain syntax"


def test_validate_email_address_accepts_domain_with_dns(monkeypatch) -> None:
    monkeypatch.setattr(email_validation, "_mail_exchange_hosts", lambda domain: ["mx.example.com"] if domain == "example.com" else [])

    result = email_validation.validate_email_address("Person@Example.com")

    assert result.is_valid is True
    assert result.reason == ""


def test_validate_email_address_rejects_domain_without_dns(monkeypatch) -> None:
    monkeypatch.setattr(email_validation, "_mail_exchange_hosts", lambda domain: [])
    monkeypatch.setattr(email_validation, "_domain_has_a_record", lambda domain: False)

    result = email_validation.validate_email_address("person@example.invalid")

    assert result.is_valid is False
    assert result.reason == "domain has no MX or A record"


def test_validate_email_address_skips_dns_when_requested() -> None:
    # No mocks needed as we skip the DNS part
    result = email_validation.validate_email_address("person@example.invalid", skip_dns_check=True)

    assert result.is_valid is True
    assert result.reason == ""


def test_domain_has_a_record_uses_socket(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda domain, port: [("ok",)])
    assert email_validation._domain_has_a_record("example.com") is True

    def fail(*_args, **_kwargs):
        raise socket.gaierror()

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert email_validation._domain_has_a_record("missing.invalid") is False


def test_domain_accepts_mail_falls_back_when_dns_package_is_missing(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "dns.resolver":
            raise ImportError("dns unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(email_validation, "_domain_has_a_record", lambda domain: domain == "example.com")

    assert email_validation._domain_accepts_mail("example.com") is True


def test_validate_email_address_can_probe_mailbox_rejects(monkeypatch) -> None:
    monkeypatch.setattr(email_validation, "_mail_exchange_hosts", lambda domain: ["mx.example.com"])
    monkeypatch.setattr(
        email_validation,
        "_probe_mailbox_exists",
        lambda email, hosts, from_email, timeout: email_validation.EmailValidationResult(False, "user unknown"),
    )

    result = email_validation.validate_email_address("missing@example.com", verify_mailbox=True)

    assert result.is_valid is False
    assert result.reason == "user unknown"


def test_probe_mailbox_accepts_definitive_smtp_responses(monkeypatch) -> None:
    def rcpt(email):
        return 550, "user unknown"

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("mx.example.com", 25, 3)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def ehlo_or_helo_if_needed(self):
            pass

        def mail(self, sender):
            pass

    monkeypatch.setattr(email_validation.smtplib, "SMTP", FakeSmtp)

    result = email_validation._probe_mailbox_exists(
        "missing@example.com",
        ["mx.example.com"],
        "sender@example.com",
        3,
    )

    assert result == email_validation.EmailValidationResult(False, "user unknown")


def test_domain_accepts_mail_uses_mx_and_falls_back_on_resolver_error(monkeypatch) -> None:
    class FakeAnswer:
        exchange = "mail.example.com."

    class FakeResolver:
        lifetime = 0
        timeout = 0

        @staticmethod
        def resolve(domain, record_type):
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
        @staticmethod
        def resolve(domain, record_type):
            raise RuntimeError("resolver down")

    fake_resolver_module.Resolver = BrokenResolver
    monkeypatch.setattr(email_validation, "_domain_has_a_record", lambda domain: domain == "example.com")

    assert email_validation._domain_accepts_mail("example.com") is True
