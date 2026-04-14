from __future__ import annotations

from pathlib import Path


def list_attachments(directory: Path) -> list[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Attachment directory not found: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Attachment path is not a directory: {directory}")

    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    )
