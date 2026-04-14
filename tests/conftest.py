from __future__ import annotations

import base64
from pathlib import Path

import pytest


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
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
