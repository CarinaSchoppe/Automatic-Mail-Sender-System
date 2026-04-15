from __future__ import annotations

import contextlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from research.logging_utils import verbose as _verbose


@contextlib.contextmanager
def fake_txt_extensions(attachment_paths: list[Path], verbose: bool = False):
    """Yield upload paths, temporarily copying CSVs to .txt names for provider upload APIs."""
    temp_files: list[Path] = []
    temp_dirs: list[tempfile.TemporaryDirectory] = []
    new_paths: list[Path] = []
    try:
        for path in attachment_paths:
            if path.suffix.lower() == ".csv":
                temp_dir = tempfile.TemporaryDirectory(prefix="mailsender_upload_")
                temp_dirs.append(temp_dir)
                fake_path = Path(temp_dir.name) / (path.name + ".txt")
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
            except OSError:  # pragma: no cover
                pass
        for temp_dir in temp_dirs:
            temp_dir.cleanup()


def extract_gemini_response_text(response) -> str | None | Any:
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


def extract_openai_response_text(response) -> str | None | Any:
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


def verbose_openai_output(verbose: bool, response) -> None:
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


def verbose_gemini_candidates(verbose: bool, response) -> None:
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
