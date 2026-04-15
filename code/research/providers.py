from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from research.logging_utils import verbose as _verbose


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


def generate_with_ollama(
        model: str,
        prompt: str,
        base_url: str = "http://localhost:11434",
        verbose: bool = False,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    url = f"{base_url.rstrip('/')}/api/generate"
    _verbose(verbose, f"Calling Ollama local model at {url} with model={model}.")
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Ollama request failed. Is Ollama running at {base_url}? {exc}") from exc

    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama returned invalid JSON.") from exc

    if data.get("error"):
        raise RuntimeError(f"Ollama returned an error: {data['error']}")
    text = str(data.get("response", ""))
    _verbose(verbose, f"Ollama response characters: {len(text)}")
    return text


def generate_with_gemini(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY before running research.")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install google-genai first: pip install -r requirements.txt") from exc

    client = genai.Client(api_key=api_key)
    _verbose(verbose, f"Uploading {len(attachment_paths)} attachment context file(s) to Gemini.")
    uploaded_files = []
    with _fake_txt_extensions(attachment_paths, verbose) as faked_paths:
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
        f"thinking_level={thinking_level.name}, temperature=0.3."
    )
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
    _verbose(verbose, "Gemini response received.")
    response_text = _extract_response_text(response)
    _verbose(verbose, f"Gemini response.text raw: {response_text!r}")
    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        _verbose(verbose, f"Gemini prompt_feedback: {prompt_feedback!r}")
    _verbose_gemini_candidates(verbose, response)
    return response_text


def generate_with_openai(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY before running OpenAI research.")

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install openai first: pip install -r requirements.txt") from exc

    client = OpenAI(api_key=api_key)
    _verbose(verbose, f"Uploading {len(attachment_paths)} attachment context file(s) to OpenAI.")
    uploaded_files = []
    with _fake_txt_extensions(attachment_paths, verbose) as faked_paths:
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
    response = client.responses.create(  # type: ignore[call-overload]
        model=model,
        input=[{"role": "user", "content": content}],
        tools=[{"type": "web_search"}],
        tool_choice="auto",
        reasoning={"effort": openai_effort},
    )
    _verbose(verbose, "OpenAI response received.")
    response_text = _extract_openai_response_text(response)
    _verbose(verbose, f"OpenAI response output_text raw: {response_text!r}")
    _verbose_openai_output(verbose, response)
    return response_text


@contextlib.contextmanager
def _fake_txt_extensions(attachment_paths: list[Path], verbose: bool = False):
    temp_files: list[Path] = []
    new_paths: list[Path] = []
    try:
        for path in attachment_paths:
            if path.suffix.lower() == ".csv":
                fake_path = Path(tempfile.gettempdir()) / (path.name + ".txt")
                _verbose(verbose, f"Faking extension for AI upload: {path.name} -> {fake_path.name}")
                shutil.copy2(path, fake_path)
                temp_files.append(fake_path)
                new_paths.append(fake_path)
            else:
                new_paths.append(path)
        yield new_paths
    finally:
        for temp_file in temp_files:
            try:
                temp_file.unlink(missing_ok=True)
            except Exception:  # pragma: no cover
                pass


def _extract_openai_response_text(response) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    texts: list[str] = []
    for output_item in getattr(response, "output", None) or []:
        for content_item in getattr(output_item, "content", None) or []:
            text = getattr(content_item, "text", None)
            if text:
                texts.append(text)
    return "\n".join(texts)


def _extract_response_text(response) -> str:
    direct_text = getattr(response, "text", None)
    if direct_text:
        return direct_text

    texts: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                texts.append(part_text)
    return "\n".join(texts)


def _verbose_openai_output(verbose: bool, response) -> None:
    if not verbose:
        return
    output_items = getattr(response, "output", None) or []
    if not output_items:
        _verbose(verbose, "OpenAI output items: none")
        return

    _verbose(verbose, f"OpenAI output items: {len(output_items)}")
    for index, output_item in enumerate(output_items, start=1):
        _verbose(verbose, f"OpenAI output item {index} type: {getattr(output_item, 'type', None)!r}")
        _verbose(verbose, f"OpenAI output item {index} status: {getattr(output_item, 'status', None)!r}")


def _verbose_gemini_candidates(verbose: bool, response) -> None:
    if not verbose:
        return

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        _verbose(verbose, "Gemini candidates: none")
        return

    _verbose(verbose, f"Gemini candidates: {len(candidates)}")
    for index, candidate in enumerate(candidates, start=1):
        _verbose(verbose, f"Gemini candidate {index} finish_reason: {getattr(candidate, 'finish_reason', None)!r}")
        _verbose(verbose, f"Gemini candidate {index} safety_ratings: {getattr(candidate, 'safety_ratings', None)!r}")
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if parts:
            for part_index, part in enumerate(parts, start=1):
                _verbose(verbose, f"Gemini candidate {index} part {part_index} text: {getattr(part, 'text', None)!r}")
        else:
            _verbose(verbose, f"Gemini candidate {index} content parts: none")
