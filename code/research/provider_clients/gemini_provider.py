from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Any

from dotenv import load_dotenv

from research.logging_utils import verbose as _verbose
from research.provider_clients.common import (
    extract_gemini_response_text,
    fake_txt_extensions,
    verbose_gemini_candidates,
)


def generate_with_gemini(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
        load_env: Callable[[], object] = load_dotenv,
) -> str | None | Any:
    global response
    load_env()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY before running research.")

    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install google-genai first: pip install -r requirements.txt") from exc

    client = genai.Client(api_key=api_key)
    _verbose(verbose, f"Uploading {len(attachment_paths)} attachment context file(s) to Gemini.")
    uploaded_files = []
    with fake_txt_extensions(attachment_paths, verbose) as faked_paths:
        for path in faked_paths:
            _verbose(verbose, f"Uploading Gemini context file: {path}.")
            uploaded_files.append(client.files.upload(file=path))
    _verbose(verbose, f"Gemini uploaded file handles: {len(uploaded_files)}.")

    thinking_level = types.ThinkingLevel.MEDIUM
    if reasoning_effort == "low":
        thinking_level = types.ThinkingLevel.BRIEF
    elif reasoning_effort == "high":
        thinking_level = types.ThinkingLevel.FULL

    _verbose(verbose, "Calling Gemini with Google Search grounding enabled.")
    _verbose(
        verbose,
        f"Gemini config: google_search enabled, tool auto mode enabled, "
        f"thinking_level={thinking_level.name}, temperature=0.3.",
    )

    max_retries = 5
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
                    temperature=0.3,
                ),
            )
            break
        except (errors.APIError, errors.ClientError) as e:
            msg = str(e).lower()
            # If it's a rate limit error (429) or temporary server error (500, 503)
            is_retryable = "429" in msg or "quota" in msg or "exhausted" in msg or "500" in msg or "503" in msg

            if is_retryable and attempt < max_retries - 1:
                wait_time = (2 ** attempt) + 10.0  # Exponential backoff + fixed buffer
                _verbose(verbose, f"Gemini API error (retryable). Retrying in {wait_time:.2f}s (Attempt {attempt + 1}/{max_retries}). Error: {e}")
                time.sleep(wait_time)
                continue

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
