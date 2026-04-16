"""
Utility module for listing file attachments in a directory.
"""

from __future__ import annotations

from pathlib import Path


def list_attachments(directory: Path) -> list[Path]:
    """
    Collects all files in a directory (recursively) for sending.
    Ignores .gitkeep files.

    Args:
        directory (Path): The path to the folder containing the attachments.

    Returns:
        list[Path]: A list of found files.
    """
    if not directory.exists():
        raise FileNotFoundError(f"Attachment directory not found: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Attachment path is not a directory: {directory}")

    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    )
