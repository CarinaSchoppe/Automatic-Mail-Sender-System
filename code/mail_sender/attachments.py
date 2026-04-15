"""
Hilfsmodul zum Auflisten von Dateianhängen in einem Verzeichnis.
"""

from __future__ import annotations

from pathlib import Path


def list_attachments(directory: Path) -> list[Path]:
    """
    Sammelt alle Dateien in einem Verzeichnis (rekursiv) für den Versand.
    Ignoriert .gitkeep-Dateien.

    Args:
        directory (Path): Der Pfad zum Ordner mit den Anhängen.

    Returns:
        list[Path]: Eine Liste der gefundenen Dateien.
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
