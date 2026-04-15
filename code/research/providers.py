"""
Zentrale Schnittstelle zur Auswahl und zum Aufruf verschiedener KI-Provider.
Unterstützt Google Gemini, OpenAI und lokale Ollama-Instanzen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv

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
    Wählt basierend auf dem 'provider' den entsprechenden KI-Dienst aus.
    
    Args:
        provider (str): Der Name des Providers (gemini, openai, ollama).
        model (str): Das zu verwendende KI-Modell.
        prompt (str): Die Anweisungen für die KI.
        attachment_paths (list[Path]): Liste von Dateipfaden, die als Kontext hochgeladen werden sollen.
        reasoning_effort (str): Die gewünschte Stufe der Denk-Leistung (low, middle, high).
        verbose (bool): Ob detaillierte Logs ausgegeben werden sollen.
        ollama_base_url (str | None): Optionale URL für lokale Ollama-Instanzen.
        
    Returns:
        Das Ergebnis der Generierung (meist ein String oder CSV-Inhalt).
    """
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
) -> str | None | Any:
    """
    Spezifischer Aufruf für den Google Gemini Provider.
    """
    return _gemini_generate(model, prompt, attachment_paths, reasoning_effort, verbose, load_dotenv)


def generate_with_openai(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str | None | Any:
    """
    Spezifischer Aufruf für den OpenAI Provider.
    """
    return _openai_generate(model, prompt, attachment_paths, reasoning_effort, verbose, load_dotenv)
