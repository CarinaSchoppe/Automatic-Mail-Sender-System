"""
Hilfsfunktionen für das Logging innerhalb der Recherche-Pipeline.
Ermöglicht einheitliche Ausgaben für Info- und Verbose-Level.
"""

from __future__ import annotations


def verbose(enabled: bool, message: str) -> None:
    """
    Gibt eine detaillierte Protokollnachricht aus, falls das Verbose-Logging aktiviert ist.
    
    Args:
        enabled (bool): Ob die Nachricht ausgegeben werden soll.
        message (str): Die auszugebende Nachricht.
    """
    if enabled:
        print(f"[VERBOSE] {message}")


def info(message: str) -> None:
    """
    Gibt eine allgemeine Informationsnachricht aus.
    
    Args:
        message (str): Die auszugebende Nachricht.
    """
    print(f"[INFO] {message}")
