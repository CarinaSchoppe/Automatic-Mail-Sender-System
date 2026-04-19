"""
Central interface for selecting and calling various AI providers.
Supports Google Gemini, OpenAI, and local Ollama instances.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research.provider_clients.common import (
    extract_gemini_response_text,
    extract_openai_response_text,
    fake_txt_extensions,
    verbose_gemini_candidates,
    verbose_openai_output,
)
from research.provider_clients.gemini_provider import generate_with_gemini as _gemini_generate
from research.provider_clients.ollama_provider import generate_with_ollama
from research.provider_clients.openai_provider import generate_with_openai as _openai_generate

__all__ = [
    "extract_gemini_response_text",
    "extract_openai_response_text",
    "fake_txt_extensions",
    "verbose_gemini_candidates",
    "verbose_openai_output",
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
) -> str | None | Any:
    """
    Selects the corresponding AI service based on the 'provider'.

    Args:
        provider (str): The name of the provider (gemini, openai, ollama).
        model (str): The AI model to use.
        prompt (str): The instructions for the AI.
        attachment_paths (list[Path]): List of file paths to upload as context.
        reasoning_effort (str): The desired level of reasoning effort (low, middle, high).
        verbose (bool): Whether to output detailed logs.
        ollama_base_url (str | None): Optional URL for local Ollama instances.

    Returns:
        The result of the generation (usually a string or CSV content).
    """
    normalized = provider.strip().lower()
    if normalized == "gemini":
        return generate_with_gemini(
            model,
            prompt,
            attachment_paths,
            reasoning_effort=reasoning_effort,
            verbose=verbose,
        )
    if normalized == "openai":
        return generate_with_openai(
            model,
            prompt,
            attachment_paths,
            reasoning_effort=reasoning_effort,
            verbose=verbose,
        )
    if normalized == "ollama":
        return generate_with_ollama(
            model,
            prompt,
            ollama_base_url or "http://localhost:11434",
            verbose=verbose,
        )
    raise ValueError("Unknown research provider. Use gemini, openai, ollama, or self.")


def generate_with_gemini(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str | None | Any:
    """
    Specific call for the Google Gemini provider.
    """
    return _gemini_generate(model, prompt, attachment_paths, reasoning_effort, verbose)


def generate_with_openai(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str | None | Any:
    """
    Specific call for the OpenAI provider.
    """
    return _openai_generate(model, prompt, attachment_paths, reasoning_effort, verbose)
