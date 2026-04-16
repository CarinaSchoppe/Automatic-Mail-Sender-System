"""Tests and helpers for tests/conftest.py."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

# Global mocks for external providers if not installed
if importlib.util.find_spec("openai") is None:
    mock_openai = MagicMock()
    mock_openai.RateLimitError = type("RateLimitError", (Exception,), {})
    sys.modules["openai"] = mock_openai

if importlib.util.find_spec("google.genai") is None:
    mock_google = MagicMock()
    sys.modules["google"] = MagicMock()
    sys.modules["google.genai"] = mock_google

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Encapsulates the helper step project."""
    for directory in [
        "input/PhD",
        "input/Freelance_German",
        "input/Freelance_English",
        "attachments/PhD",
        "attachments/Freelance_German",
        "attachments/Freelance_English",
        "templates",
        "output",
    ]:
        (tmp_path / directory).mkdir(parents=True)

    (tmp_path / "templates/phd.txt").write_text("Subject: PhD {company}\n\nHello {company}", encoding="utf-8")
    (tmp_path / "templates/freelance_german.txt").write_text("Subject: DE {company}\n\nHallo {company}", encoding="utf-8")
    (tmp_path / "templates/freelance_english.txt").write_text("Subject: EN {company}\n\nHello {company}", encoding="utf-8")
    (tmp_path / "templates/signature.txt").write_text("Regards\n{IMAGE}", encoding="utf-8")
    (tmp_path / "templates/signature-logo.png").write_bytes(PNG_BYTES)

    return tmp_path
