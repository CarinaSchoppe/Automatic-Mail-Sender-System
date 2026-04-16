"""Tests and helpers for tests/test_provider_clients.py."""

from __future__ import annotations

import types

from research.provider_clients.common import extract_gemini_response_text, extract_openai_response_text
from research.providers import generate_with_provider


def test_provider_router_dispatches_to_provider_clients(monkeypatch) -> None:
    """Checks behavior for provider router dispatches to provider clients."""
    calls = []
    monkeypatch.setattr(
        "research.providers.generate_with_gemini",
        lambda model, prompt, attachments, reasoning_effort="middle", verbose=False: calls.append(("gemini", model)) or "g",
    )
    monkeypatch.setattr(
        "research.providers.generate_with_openai",
        lambda model, prompt, attachments, reasoning_effort="middle", verbose=False: calls.append(("openai", model)) or "o",
    )
    monkeypatch.setattr(
        "research.providers.generate_with_ollama",
        lambda model, prompt, base_url="http://localhost:11434", verbose=False: calls.append(("ollama", model, base_url)) or "l",
    )

    assert generate_with_provider("gemini", "gm", "prompt", []) == "g"
    assert generate_with_provider("openai", "om", "prompt", []) == "o"
    assert generate_with_provider("ollama", "lm", "prompt", [], ollama_base_url="http://local") == "l"
    assert calls == [("gemini", "gm"), ("openai", "om"), ("ollama", "lm", "http://local")]


def test_provider_common_extracts_nested_response_text() -> None:
    """Checks behavior for provider common extracts nested response text."""
    gemini_response = types.SimpleNamespace(
        text="",
        candidates=[
            types.SimpleNamespace(
                content=types.SimpleNamespace(parts=[types.SimpleNamespace(text="company,mail")])
            )
        ],
    )
    openai_response = types.SimpleNamespace(
        output_text="",
        output=[
            types.SimpleNamespace(
                content=[types.SimpleNamespace(text="company,mail")]
            )
        ],
    )

    assert extract_gemini_response_text(gemini_response) == "company,mail"
    assert extract_openai_response_text(openai_response) == "company,mail"
