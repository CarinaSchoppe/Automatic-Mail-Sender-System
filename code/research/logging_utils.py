from __future__ import annotations


def verbose(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[VERBOSE] {message}")


def info(message: str) -> None:
    print(f"[INFO] {message}")
