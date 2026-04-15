from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from research.provider_clients.common import (
    extract_gemini_response_text as _extract_response_text,
)
from research.provider_clients.common import (
    extract_openai_response_text as _extract_openai_response_text,
)
from research.provider_clients.common import fake_txt_extensions as _fake_txt_extensions
from research.provider_clients.common import verbose_gemini_candidates as _verbose_gemini_candidates
from research.provider_clients.common import verbose_openai_output as _verbose_openai_output
from research.provider_clients.gemini_provider import generate_with_gemini as _gemini_generate
from research.provider_clients.ollama_provider import generate_with_ollama
from research.provider_clients.openai_provider import generate_with_openai as _openai_generate

__all__ = [
    "_extract_response_text",
    "_extract_openai_response_text",
    "_fake_txt_extensions",
    "_verbose_gemini_candidates",
    "_verbose_openai_output",
    "generate_with_provider",
    "generate_with_gemini",
    "generate_with_openai",
    "generate_with_ollama",
]


def generate_with_provider(
        provider: str,
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
        ollama_base_url: str | None = None,
) -> str:
    normalized = provider.strip().lower()
    if normalized == "gemini":
        return generate_with_gemini(model, prompt, attachment_paths, reasoning_effort, verbose)
    if normalized == "openai":
        return generate_with_openai(model, prompt, attachment_paths, reasoning_effort, verbose)
    if normalized == "ollama":
        return generate_with_ollama(model, prompt, ollama_base_url or "http://localhost:11434", verbose)
    raise ValueError("Unknown research provider. Use gemini, openai, ollama, or self.")


def generate_with_gemini(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str:
    return _gemini_generate(model, prompt, attachment_paths, reasoning_effort, verbose, load_dotenv)


def generate_with_openai(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str:
    return _openai_generate(model, prompt, attachment_paths, reasoning_effort, verbose, load_dotenv)
