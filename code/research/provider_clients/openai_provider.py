from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable

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
        load_env: Callable[[], object] = load_dotenv,
) -> str:
    load_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY before running OpenAI research.")

    try:
        from openai import OpenAI, RateLimitError
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install openai first: pip install -r requirements.txt") from exc

    client = OpenAI(api_key=api_key)
    _verbose(verbose, f"Uploading {len(attachment_paths)} attachment context file(s) to OpenAI.")
    uploaded_files = []
    with fake_txt_extensions(attachment_paths, verbose) as faked_paths:
        for path in faked_paths:
            _verbose(verbose, f"Uploading OpenAI context file: {path}.")
            with path.open("rb") as handle:
                uploaded_files.append(client.files.create(file=handle, purpose="user_data"))
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
    for attempt in range(max_retries):
        try:
            response = client.responses.create(  # type: ignore[call-overload]
                model=model,
                input=[{"role": "user", "content": content}],
                tools=[{"type": "web_search"}],
                tool_choice="auto",
                reasoning={"effort": openai_effort},
            )
            break
        except RateLimitError as e:
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
