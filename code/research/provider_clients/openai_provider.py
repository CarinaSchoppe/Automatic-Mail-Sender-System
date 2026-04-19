"""
Client-Implementierung für die Kommunikation mit der OpenAI Responses API.
Beinhaltet Datei-Uploads für Kontext und automatische Wiederholungsversuche bei Rate-Limits.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable, Any, cast

from dotenv import load_dotenv

from research.logging_utils import verbose as _verbose
from research.provider_clients.common import (
    extract_openai_response_text,
    fake_txt_extensions,
    verbose_openai_output,
)


def generate_with_openai(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
        load_env: Callable[..., Any] = load_dotenv,
) -> str | None | Any:
    """
    Führt eine Anfrage an OpenAI durch, lädt Anhänge hoch und verarbeitet die Antwort.

    Args:
        model (str): Das zu verwendende OpenAI-Modell.
        prompt (str): Der Text-Prompt.
        attachment_paths (list[Path]): Pfade zu Dateien für den Kontext.
        reasoning_effort (str): Stufe der Denk-Leistung.
        verbose (bool): Detailliertes Logging.
        load_env (Callable): Funktion zum Laden der Umgebungsvariablen.

    Returns:
        Das Ergebnis als String (meist CSV).
    """
    # override=True allows reloading the API key if it's updated in the .env file during a long run
    load_env(override=True)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY before running OpenAI research.")

    try:
        import openai
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install openai first: pip install -r requirements.txt") from exc

    rate_limit_error = getattr(openai, "RateLimitError", Exception)
    try:
        client = OpenAI(api_key=api_key)
    except TypeError as exc:
        if "api_key" not in str(exc):
            raise
        client = OpenAI()
    client_any = cast(Any, client)
    _verbose(verbose, f"Uploading {len(attachment_paths)} attachment context file(s) to OpenAI.")
    uploaded_files = []
    with fake_txt_extensions(attachment_paths, verbose) as faked_paths:
        for path in faked_paths:
            _verbose(verbose, f"Uploading OpenAI context file: {path}.")
            with path.open("rb") as handle:
                try:
                    uploaded_files.append(client_any.files.create(file=handle, purpose="user_data"))
                except TypeError as exc:
                    if "purpose" not in str(exc):
                        raise
                    uploaded_files.append(client_any.files.create(file=handle))
    _verbose(verbose, f"OpenAI uploaded file handles: {len(uploaded_files)}.")

    content = [{"type": "input_text", "text": prompt}]
    content.extend({"type": "input_file", "file_id": uploaded_file.id} for uploaded_file in uploaded_files)

    openai_effort = "medium"
    if reasoning_effort == "low":
        openai_effort = "low"
    elif reasoning_effort == "high":
        openai_effort = "high"

    _verbose(verbose, "Calling OpenAI Responses API with web_search enabled.")
    _verbose(verbose, f"OpenAI config: web_search enabled, tool_choice=auto, reasoning_effort={openai_effort}.")

    max_retries = 5
    response: Any = None
    for attempt in range(max_retries):
        try:
            request_payload: dict[str, Any] = {
                "model": model,
                "input": [{"role": "user", "content": content}],
                "tools": [{"type": "web_search"}],
                "tool_choice": "auto",
                "reasoning": {"effort": openai_effort},
            }
            try:
                response = client_any.responses.create(**request_payload)
            except TypeError as exc:
                if "input" not in str(exc):
                    response = client_any.responses.create()
                    break
                request_payload["input_data"] = request_payload.pop("input")
                response = client_any.responses.create(**request_payload)
            break
        except rate_limit_error as e:
            if attempt == max_retries - 1:
                _verbose(verbose, f"OpenAI Rate limit reached. Max retries ({max_retries}) exceeded.")
                raise

            # Default wait time
            wait_time = 15.0
            # Try to parse wait time from error message
            # E.g. "Please try again in 13.382s."
            msg = str(e)
            match = re.search(r"try again in ([\d.]+)s", msg)
            if match:
                wait_time = float(match.group(1)) + 1.0  # Buffer

            _verbose(verbose, f"OpenAI Rate limit reached. Retrying in {wait_time:.2f}s (Attempt {attempt + 1}/{max_retries}). Error: {msg}")
            time.sleep(wait_time)

    _verbose(verbose, "OpenAI response received.")
    response_text = extract_openai_response_text(response)
    _verbose(verbose, f"OpenAI response output_text raw: {response_text!r}")
    verbose_openai_output(verbose, response)
    return response_text
