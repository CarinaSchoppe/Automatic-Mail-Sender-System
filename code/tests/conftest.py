"""Tests and helpers for tests/conftest.py."""

from __future__ import annotations

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
    (tmp_path / "templates/phd_spam_safe.txt").write_text("Subject: PhD safe {company}\n\nHello safe {company}", encoding="utf-8")
    (tmp_path / "templates/freelance_german_spam_safe.txt").write_text("Subject: DE safe {company}\n\nHallo safe {company}", encoding="utf-8")
    (tmp_path / "templates/freelance_english_spam_safe.txt").write_text("Subject: EN safe {company}\n\nHello safe {company}", encoding="utf-8")
    (tmp_path / "templates/signature.html").write_text(
        "<!DOCTYPE html><html><body><table><tr><td>Regards</td></tr><tr><td>Carina Sophie Schoppe</td></tr></table></body></html>",
        encoding="utf-8",
    )
    return tmp_path
