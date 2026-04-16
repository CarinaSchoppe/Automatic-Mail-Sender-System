"""
Utility functions for logging within the research pipeline.
Provides unified output for info and verbose levels.
"""

from __future__ import annotations

import threading

# Local storage for thread-specific information (e.g., a thread ID).
_thread_context = threading.local()


def set_thread_id(thread_id: int | str | None) -> None:
    """Sets the thread ID for the current thread."""
    _thread_context.thread_id = thread_id


def get_thread_id() -> str:
    """Returns the current thread ID as a string prefix, if available."""
    tid = getattr(_thread_context, "thread_id", None)
    return f"[Thread-{tid}] " if tid is not None else ""


def verbose(enabled: bool, message: str) -> None:
    """
    Prints a detailed log message if verbose logging is enabled.
    Automatically includes the thread ID if set in the current thread.
    """
    if enabled:
        print(f"{get_thread_id()}[VERBOSE] {message}")


def info(message: str) -> None:
    """
    Prints a general information message.
    Automatically includes the thread ID if set in the current thread.
    """
    print(f"{get_thread_id()}[INFO] {message}")
