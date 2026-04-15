from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from mail_sender.recipients import Recipient


@dataclass(frozen=True)
class ResearchConfig:
    provider: str
    mode_name: str
    model: str
    min_companies: int
    max_companies: int
    person_emails_per_company: int
    base_dir: Path
    write_output: bool
    verbose: bool
    upload_attachments: bool
    gemini_model: str
    openai_model: str
    ollama_model: str = "llama3.1:8b"
    ollama_base_url: str = "http://localhost:11434"
    reasoning_effort: str = "middle"
    send_target_count: int = 0
    max_iterations: int = 5
    parallel_threads: int = 1
    self_search_keywords: tuple[str, ...] = ()
    self_search_pages: int = 1
    self_results_per_page: int = 10
    self_crawl_max_pages_per_site: int = 8
    self_crawl_depth: int = 2
    self_request_timeout: float = 10.0
    self_verify_email_smtp: bool = False


@runtime_checkable
class RecipientSink(Protocol):
    def add_recipient(self, recipient: Recipient) -> bool:
        """Add recipient and return True if it was accepted (new and within target)."""
        ...

    def is_full(self) -> bool:
        """Return True if target reached."""
        ...
