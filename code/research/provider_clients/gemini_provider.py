"""
Client-Implementierung für die Kommunikation mit Google Gemini.
Unterstützt Datei-Uploads, Google Search Grounding und exponentielles Backoff bei API-Fehlern.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from research.logging_utils import verbose as _verbose
from research.provider_clients.common import (
    extract_gemini_response_text,
    fake_txt_extensions,
    verbose_gemini_candidates,
)

# Cache für Gemini-Clients, um Mehrfach-Initialisierung zu vermeiden (Thread-sicherer Zugriff)
_client_cache: dict[tuple[str, int], Any] = {}

_cache_lock = threading.Lock()


def _get_client(api_key: str) -> Any:
    from google import genai
    client_class = genai.Client
    cache_key = (api_key, id(client_class))
    with _cache_lock:
        if cache_key not in _client_cache:
            _client_cache[cache_key] = _create_client(client_class, api_key)
        return _client_cache[cache_key]


def _create_client(client_class: Any, api_key: str) -> Any:
    """Initializes the Gemini client while tolerating simple test doubles."""
    try:
        return client_class(api_key=api_key)
    except TypeError as exc:
        if "api_key" not in str(exc):
            raise
        return client_class()


def generate_with_gemini(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str | None | Any:
    """
    Führt eine Anfrage an Google Gemini durch, lädt Anhänge hoch und verarbeitet die Antwort.

    Args:
        model (str): Das zu verwendende Gemini-Modell.
        prompt (str): Der Text-Prompt.
        attachment_paths (list[Path]): Pfade zu Dateien für den Kontext.
        reasoning_effort (str): Stufe der Denk-Leistung (ThinkingLevel).
        verbose (bool): Detailliertes Logging.

    Returns:
        Das Ergebnis als String (meist CSV).
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY in .env before running research.")

    api_key = api_key.strip().strip("'").strip('"')

    # Maskiertes Logging des Keys zur Diagnose
    key_prefix = api_key[:4]
    key_suffix = api_key[-4:] if len(api_key) > 8 else ""
    key_type = "Standard API Key (starts with AIza)" if api_key.startswith("AIza") else "Likely a temporary/token Key (starts with AQ.)"
    _verbose(verbose, f"Using Gemini {key_type}: {key_prefix}...{key_suffix} (Length: {len(api_key)})")

    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install google-genai first: pip install -r requirements.txt") from exc
    errors = getattr(genai, "errors", None)
    types = getattr(genai, "types", None)
    if types is None:
        try:
            from google.genai import types as imported_types
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install google-genai first: pip install -r requirements.txt") from exc
        types = imported_types
    api_error_list: list[type[BaseException]] = []
    if errors:
        for err_name in ["APIError", "ClientError"]:
            err_cls = getattr(errors, err_name, None)
            if isinstance(err_cls, type) and issubclass(err_cls, BaseException):
                api_error_list.append(err_cls)

    if not api_error_list:
        api_error_list.append(Exception)

    api_error_classes: tuple[type[BaseException], ...] = tuple(api_error_list)

    try:
        client = _get_client(api_key)
    except Exception as exc:
        _verbose(verbose, f"Error initializing Gemini client: {exc}")
        # Fallback auf direkten Aufruf, falls der Cache-Mechanismus Probleme macht
        from google import genai
        client = _create_client(genai.Client, api_key)

    _verbose(verbose, f"Uploading {len(attachment_paths)} attachment context file(s) to Gemini.")
    uploaded_files = []

    # Da File-Uploads auch Authentifizierung brauchen, fangen wir Fehler hier ab
    try:
        with fake_txt_extensions(attachment_paths, verbose) as faked_paths:
            for path in faked_paths:
                _verbose(verbose, f"Uploading Gemini context file: {path}.")
                uploaded_files.append(client.files.upload(file=path))
        _verbose(verbose, f"Gemini uploaded file handles: {len(uploaded_files)}.")
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "unauthenticated" in msg:
            _verbose(verbose, f"Gemini Upload error: 401 UNAUTHENTICATED. The API key {key_prefix}... is invalid/expired. (Error: {e})")
        else:
            _verbose(verbose, f"Gemini Upload error: {e}")
        raise

    thinking_level = _thinking_level_for_effort(types, reasoning_effort)

    _verbose(verbose, "Calling Gemini with Google Search grounding enabled.")
    _verbose(
        verbose,
        f"Gemini config: google_search enabled, tool auto mode enabled, "
        f"thinking_level={_thinking_level_name(thinking_level)}, temperature=1",
    )

    max_retries = 5
    response: Any = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[prompt, *uploaded_files],  # type: ignore[arg-type]
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode=types.FunctionCallingConfigMode.AUTO,
                        ),
                        include_server_side_tool_invocations=True,
                    ),
                    thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
                    temperature=1,
                ),
            )
            break
        except api_error_classes as e:
            msg = str(e).lower()
            # If it's a rate limit error (429) or temporary server error (500, 503)
            is_retryable = "429" in msg or "quota" in msg or "exhausted" in msg or "500" in msg or "503" in msg

            # 401 is usually not retryable unless the key was just updated in .env
            # But we don't want to spam retries for a fundamentally broken key.
            # However, if the user sees the error and fixes .env, override=True will pick it up.

            if is_retryable and attempt < max_retries - 1:
                wait_time = (2 ** attempt) + 10.0  # Exponential backoff + fixed buffer
                _verbose(verbose, f"Gemini API error (retryable). Retrying in {wait_time:.2f}s (Attempt {attempt + 1}/{max_retries}). Error: {e}")
                time.sleep(wait_time)
                continue

            if "401" in msg or "unauthenticated" in msg:
                _verbose(verbose, f"Gemini API error: 401 UNAUTHENTICATED. "
                                  f"Hint: If the key starts with 'AQ.', it is likely a temporary access token that expires after 60 minutes. "
                                  f"Please get a permanent API key (starting with 'AIza') from https://aistudio.google.com/app/apikey "
                                  f"and update GEMINI_API_KEY in your .env file. "
                                  f"(Error: {e})")
            else:
                _verbose(verbose, f"Gemini API error (non-retryable or max retries). Error: {e}")
            raise

    _verbose(verbose, "Gemini response received.")
    response_text = extract_gemini_response_text(response)
    _verbose(verbose, f"Gemini response.text raw: {response_text!r}")
    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        _verbose(verbose, f"Gemini prompt_feedback: {prompt_feedback!r}")
    verbose_gemini_candidates(verbose, response)
    return response_text


def _thinking_level_for_effort(types_module: Any, reasoning_effort: str) -> Any:
    """Liest Gemini-ThinkingLevel-Werte dynamisch, damit SDK-Stubs nicht brechen."""
    thinking_levels = getattr(types_module, "ThinkingLevel")
    default_level = getattr(thinking_levels, "MEDIUM")
    level_name = {
        "low": "BRIEF",
        "middle": "MEDIUM",
        "high": "FULL",
    }.get(reasoning_effort, "MEDIUM")
    return getattr(thinking_levels, level_name, default_level)


def _thinking_level_name(thinking_level: Any) -> str:
    """Ermittelt den Lognamen eines dynamischen Gemini-ThinkingLevel-Werts."""
    return str(getattr(thinking_level, "name", thinking_level))
