"""
Definition von zentralen Datenstrukturen und Protokollen für die Recherche-Pipeline.
Ermöglicht eine konsistente Konfigurationsübergabe und abstrakte Ergebnissammler.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from mail_sender.recipients import Recipient
from mail_sender.validation_policy import EXTERNAL_VALIDATION_DISABLED, VALIDATION_STAGE_RESEARCH


@dataclass(frozen=True)
class ResearchConfig:
    """
    Bündelt alle Parameter für einen Recherche-Durchlauf.
    Inklusive Provider-Einstellungen, Limits, Threading und Crawling-Optionen.
    """
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
    research_context_delivery: str = "upload_files"
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
    external_validation_service: str = EXTERNAL_VALIDATION_DISABLED
    external_validation_api_key: str = ""
    external_validation_stage: str = VALIDATION_STAGE_RESEARCH


@runtime_checkable
class RecipientSink(Protocol):
    """
    Schnittstellen-Definition für Objekte, die gefundene Leads (Recipient) sammeln.
    Ermöglicht eine Entkoppelung zwischen der Suche (Crawler/KI) und der Speicherung.
    """

    lock: Any
    recipients: list[Recipient]
    target_count: int

    def add_recipient(self, recipient: Recipient, thread_id: int | None = None) -> bool:
        """
        Fügt einen Empfänger hinzu.
        Gibt True zurück, wenn dieser akzeptiert wurde und noch im Zielbereich liegt.
        """
        ...

    def is_full(self) -> bool:
        """Gibt True zurück, wenn das Gesamtziel an Empfängern erreicht wurde."""
        ...
