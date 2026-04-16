"""
Hilfsfunktionen für das Logging innerhalb der Recherche-Pipeline.
Ermöglicht einheitliche Ausgaben für Info- und Verbose-Level.
"""

from __future__ import annotations

import threading

# Lokaler Speicher für thread-spezifische Informationen (z. B. eine Thread-ID).
_thread_context = threading.local()


def set_thread_id(thread_id: int | str | None) -> None:
    """Setzt die Thread-ID für den aktuellen Thread."""
    _thread_context.thread_id = thread_id


def get_thread_id() -> str:
    """Liefert die aktuelle Thread-ID als String-Präfix, falls vorhanden."""
    tid = getattr(_thread_context, "thread_id", None)
    return f"[Thread-{tid}] " if tid is not None else ""


def verbose(enabled: bool, message: str) -> None:
    """
    Gibt eine detaillierte Protokollnachricht aus, falls das Verbose-Logging aktiviert ist.
    Inkludiert automatisch die Thread-ID, falls im aktuellen Thread gesetzt.
    """
    if enabled:
        print(f"{get_thread_id()}[VERBOSE] {message}")


def info(message: str) -> None:
    """
    Gibt eine allgemeine Informationsnachricht aus.
    Inkludiert automatisch die Thread-ID, falls im aktuellen Thread gesetzt.
    """
    print(f"{get_thread_id()}[INFO] {message}")
