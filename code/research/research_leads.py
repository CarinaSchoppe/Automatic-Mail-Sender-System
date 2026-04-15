"""
Haupt-Pipeline für die KI-gestützte Lead-Recherche.
Verwaltet den Ablauf von der Prompt-Erstellung über den KI-Aufruf bis hin zum Parsen und Speichern der Ergebnisse.
Unterstützt Multi-Threading für parallele Anfragen.
"""

# Local imports intentionally come after the direct-script path bootstrap below.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import csv
import importlib
import os
import re
import sys
import threading
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import cast, Any

from dotenv import load_dotenv

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from mail_sender.attachments import list_attachments
from mail_sender.email_validation import validate_email_address
from mail_sender.modes import MODE_NAMES, MailMode, get_mode
from mail_sender.recipients import Recipient, list_recipient_files, read_recipients
from mail_sender.sent_log import read_logged_emails, read_logged_rows, read_known_output_emails
from research import parsing as _parsing
from research.providers import (
    generate_with_gemini as _gemini_generate,
    generate_with_ollama as _ollama_generate,
    generate_with_openai as _openai_generate,
)
from research import providers as _providers
from research import self_research as _self_research
from research.logging_utils import info as _info
from research.logging_utils import verbose as _verbose
from research.parsing import parse_recipients, normalize_company as _normalize_company
from research.types import RecipientSink, ResearchConfig
from research.self_research import (
    default_self_keywords as _default_self_keywords,
)

# Late import for prompts to avoid circular issues
mode_instructions = importlib.import_module(
    f"{__package__}.mode_instructions" if __package__ else "mode_instructions"
)

RESUME_ATTACHMENT_PATTERN = re.compile(
    r"(?:^|[\s._-])(cv|resume|lebenslauf|curriculum(?:[\s._-]+vitae)?)(?:$|[\s._-])",
    re.IGNORECASE,
)

EMAIL_KEYS = {"mail", "email", "recipient", "recipients", "target", "empfänger", "empfaenger"}
COMPANY_KEYS = {"company", "firma", "organisation", "organization", "name"}


def generate_with_provider(*args, **kwargs):
    """
    Delegiert den Aufruf zur Generierung von Leads an den entsprechenden Provider-Client.

    Args:
        *args: Variable Positionsargumente.
        **kwargs: Variable Schlüsselwortargumente.

    Returns:
        Das Ergebnis der Lead-Generierung (meist ein CSV-String).
    """
    return _providers.generate_with_provider(*args, **kwargs)


def generate_with_gemini(*args, **kwargs):
    """
    Delegiert den Aufruf zur Generierung von Leads spezifisch an Google Gemini.
    """
    return _gemini_generate(*args, **kwargs)


def generate_with_openai(*args, **kwargs):
    """
    Delegiert den Aufruf zur Generierung von Leads spezifisch an OpenAI.
    """
    return _openai_generate(*args, **kwargs)


def generate_with_ollama(*args, **kwargs):
    """
    Delegiert den Aufruf zur Generierung von Leads spezifisch an eine lokale Ollama-Instanz.
    """
    return _ollama_generate(*args, **kwargs)


_fake_txt_extensions = _providers.fake_txt_extensions
_verbose_gemini_candidates = _providers.verbose_gemini_candidates
_verbose_openai_output = _providers.verbose_openai_output
_parse_json_recipients = _parsing.parse_json_recipients
_detect_dialect = _parsing.detect_dialect
detect_dialect = _parsing.detect_dialect
_find_field = _parsing.find_field
_strip_csv_fence = _parsing.strip_csv_fence
_strip_json_fence = _parsing.strip_json_fence
_parse_headerless_csv_recipients = _parsing.parse_headerless_csv_recipients
DefaultCsvDialect = _parsing.DefaultCsvDialect


class ThreadSafeRecipientSink:
    """
    Ein thread-sicherer Container zum Sammeln von validierten Leads (Empfängern).
    Verhindert doppelte Einträge und bricht die Suche ab, sobald das Ziel erreicht ist.
    """
    def __init__(self, target_count: int, seen_emails: set[str], seen_companies: set[str], config: ResearchConfig):
        """
        Initialisiert den Sink mit Zielvorgaben und bereits bekannten Daten.

        Args:
            target_count (int): Anzahl der insgesamt gewünschten E-Mail-Adressen.
            seen_emails (set[str]): Menge der bereits kontaktierten E-Mails (Deduplizierung).
            seen_companies (set[str]): Menge der bereits recherchierten Firmen.
            config (ResearchConfig): Die aktuelle Recherche-Konfiguration.
        """
        self.target_count = target_count
        self.seen_emails = {email.lower() for email in seen_emails}
        self.seen_companies = {company for company in seen_companies if company}
        self.config = config
        self.recipients: list[Recipient] = []
        self.lock = threading.Lock()

    def add_recipient(self, recipient: Recipient) -> bool:
        """
        Versucht einen neuen Empfänger hinzuzufügen. Prüft auf Duplikate und Zielerreichung.

        Args:
            recipient (Recipient): Der gefundene Lead.

        Returns:
            bool: True, wenn das Gesamtziel (target_count) erreicht wurde, andernfalls False.
        """
        email_key = recipient.email.lower()
        company_key = _normalize_company(recipient.company)

        with self.lock:
            if len(self.recipients) >= self.target_count:
                return False
            if email_key in self.seen_emails:
                return False
            if company_key and company_key in self.seen_companies:
                return False

        # Validation outside of lock because it might be slow (SMTP/Network)
        # Using the imported function directly to ensure we pick up mocks
        try:
            val_func = validate_email_address
            validation = val_func(
                recipient.email,
                verify_mailbox=self.config.self_verify_email_smtp,
                smtp_timeout=self.config.self_request_timeout,
            )
            # Support both real and SimpleNamespace mocks
            is_valid = getattr(validation, "is_valid", False)
            reason = getattr(validation, "reason", "unknown")
        except OSError as e:  # pragma: no cover
            _verbose(self.config.verbose, f"Validation failed with exception for {recipient.email}: {e}")
            return False
        if not is_valid:
            _verbose(self.config.verbose, f"Recipient {recipient.email} rejected: {reason}")
            return False

        with self.lock:
            # Re-check inside lock after potentially slow validation
            if len(self.recipients) >= self.target_count:
                return False
            if email_key in self.seen_emails:
                return False
            if company_key and company_key in self.seen_companies:
                return False

            self.recipients.append(recipient)
            self.seen_emails.add(email_key)
            if company_key:
                self.seen_companies.add(company_key)
            return True

    def is_full(self) -> bool:
        """
        Prüft, ob das Sammlungsziel erreicht wurde.
        """
        with self.lock:
            return len(self.recipients) >= self.target_count

    def is_seen(self, email: str, company: str | None = None) -> bool:
        """
        Prüft, ob eine E-Mail oder Firma bereits in den bekannten Listen oder im aktuellen Durchlauf existiert.
        """
        email_key = email.lower()
        company_key = _normalize_company(company) if company else None
        with self.lock:
            if email_key in self.seen_emails:
                return True
            if company_key and company_key in self.seen_companies:
                return True
        return False


def _load_settings() -> dict:
    """
    Lädt die allgemeinen Einstellungen aus der settings.toml im Projekt-Wurzelverzeichnis.
    """
    settings_path = CODE_DIR.parent / "settings.toml"
    if not settings_path.exists():
        return {}
    try:
        with settings_path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    except Exception:  # Fallback for unexpected errors
        return {}


def default_config() -> ResearchConfig:
    """
    Erstellt eine Standard-Konfiguration basierend auf Umgebungsvariablen und der settings.toml Datei.
    """
    load_dotenv()
    settings = _load_settings()

    def _get(key: str, default):
        """Ermittelt Daten."""
        val = os.getenv(key)
        if val is not None:
            if isinstance(default, bool):
                return str(val).lower() in ("true", "1", "yes")
            if isinstance(default, int):
                return int(val)
            if isinstance(default, float):
                return float(val)
            if isinstance(default, tuple):
                return tuple(part.strip() for part in val.split("|") if part.strip())
            return val
        return settings.get(key, default)

    provider = cast(str, _get("RESEARCH_AI_PROVIDER", "gemini"))
    gemini_model = cast(str, _get("GEMINI_MODEL", "gemini-3-flash-preview"))
    openai_model = cast(str, _get("OPENAI_MODEL", "gpt-5.4-mini-2026-03-17"))
    ollama_model = cast(str, _get("OLLAMA_MODEL", "llama3.1:8b"))
    ollama_base_url = cast(str, _get("OLLAMA_BASE_URL", "http://localhost:11434"))

    # Mode name: check RESEARCH_MODE (env) then MODE (env or toml)
    mode_name = os.getenv("RESEARCH_MODE")
    if mode_name is None:
        mode_name = cast(str, _get("MODE", "PhD"))

    return ResearchConfig(
        provider=provider,
        mode_name=mode_name,
        gemini_model=gemini_model,
        openai_model=openai_model,
        ollama_model=ollama_model,
        ollama_base_url=ollama_base_url,
        model=_model_for_provider(provider, gemini_model, openai_model, ollama_model),
        min_companies=cast(int, _get("RESEARCH_MIN_COMPANIES", 15)),
        max_companies=cast(int, _get("RESEARCH_MAX_COMPANIES", 25)),
        person_emails_per_company=cast(int, _get("RESEARCH_PERSON_EMAILS_PER_COMPANY", 3)),
        base_dir=Path(cast(str, _get("RESEARCH_BASE_DIR", str(CODE_DIR.parent)))).resolve(),
        write_output=cast(bool, _get("RESEARCH_WRITE_OUTPUT", True)),
        verbose=cast(bool, _get("RESEARCH_VERBOSE", False)),
        upload_attachments=cast(bool, _get("RESEARCH_UPLOAD_ATTACHMENTS", True)),
        reasoning_effort=cast(str, _get("RESEARCH_REASONING_EFFORT", "middle")),
        send_target_count=cast(int, _get("SEND_TARGET_COUNT", 0)),
        max_iterations=cast(int, _get("SEND_TARGET_MAX_ROUNDS", 5)),
        parallel_threads=cast(int, _get("PARALLEL_THREADS", 3)),
        self_search_keywords=tuple(cast(list[str], _get("SELF_SEARCH_KEYWORDS", list(_default_self_keywords(mode_name))))),
        self_search_pages=cast(int, _get("SELF_SEARCH_PAGES", 1)),
        self_results_per_page=cast(int, _get("SELF_RESULTS_PER_PAGE", 10)),
        self_crawl_max_pages_per_site=cast(int, _get("SELF_CRAWL_MAX_PAGES_PER_SITE", 8)),
        self_crawl_depth=cast(int, _get("SELF_CRAWL_DEPTH", 2)),
        self_request_timeout=float(cast(float, _get("SELF_REQUEST_TIMEOUT", 10.0))),
        self_verify_email_smtp=cast(bool, _get("SELF_VERIFY_EMAIL_SMTP", False)),
    )


def main(argv: list[str] | None = None) -> int:
    """
    Haupteinstiegspunkt für das Recherche-Skript.
    Parst Argumente, führt die Recherche aus und gibt eine Zusammenfassung aus.
    """
    args_list = argv if argv is not None else sys.argv[1:]
    config = parse_args(args_list)
    try:
        output_path, recipients = run_research(config)
    except (RuntimeError, ValueError, FileNotFoundError, NotADirectoryError) as exc:
        print(f"Error: {exc}")
        return 1

    print(f"research mode: {config.mode_name}")
    print(f"New recipients: {len(recipients)}")
    if output_path:
        print(f"Output CSV: {output_path}")
    return 0


def parse_args(argv: list[str]) -> ResearchConfig:
    """
    Parst die Kommandozeilenargumente und erstellt ein ResearchConfig-Objekt.
    Kombiniert Standardwerte, Umgebungsvariablen und explizite CLI-Flags.
    """
    env_config = default_config()
    parser = argparse.ArgumentParser(description="research new lead CSV files with AI providers or self-hosted web scraping.")
    parser.add_argument("--provider", default=env_config.provider, choices=["gemini", "openai", "ollama", "self"], help="Research provider.")
    parser.add_argument("--mode", default=env_config.mode_name, choices=MODE_NAMES, help="research mode.")
    parser.add_argument("--gemini-model", default=env_config.gemini_model)
    parser.add_argument("--openai-model", default=env_config.openai_model)
    parser.add_argument("--ollama-model", default=env_config.ollama_model)
    parser.add_argument("--ollama-base-url", default=env_config.ollama_base_url)
    parser.add_argument("--min-companies", type=int, default=env_config.min_companies)
    parser.add_argument("--max-companies", type=int, default=env_config.max_companies)
    parser.add_argument("--person-emails-per-company", type=int, default=env_config.person_emails_per_company)
    parser.add_argument("--base-dir", default=str(env_config.base_dir))
    parser.add_argument("--no-write-output", action="store_true", help="Do not write the generated CSV file.")
    parser.add_argument("--no-upload-attachments", action="store_true", help="Do not upload CV/resume context files to the AI provider.")
    parser.add_argument("--send-target-count", type=int, default=env_config.send_target_count, help="Total target count for the send loop.")
    parser.add_argument("--max-iterations", type=int, default=env_config.max_iterations, help="Maximum number of research iterations (0 for unlimited).")
    parser.add_argument("--parallel-threads", type=int, default=env_config.parallel_threads, help="Maximum number of AI research requests to run in parallel.")
    parser.add_argument("--self-search-keyword", action="append", dest="self_search_keywords", help="Keyword/query for self web research. Can be used multiple times.")
    parser.add_argument("--self-search-pages", type=int, default=env_config.self_search_pages, help="Number of Google result pages to scan in self research.")
    parser.add_argument("--self-results-per-page", type=int, default=env_config.self_results_per_page, help="Expected search results per page in self research.")
    parser.add_argument("--self-crawl-max-pages-per-site", type=int, default=env_config.self_crawl_max_pages_per_site, help="Maximum same-site pages to crawl per result in self research.")
    parser.add_argument("--self-crawl-depth", type=int, default=env_config.self_crawl_depth, help="Maximum same-site link depth to crawl per result in self research.")
    parser.add_argument("--self-request-timeout", type=float, default=env_config.self_request_timeout, help="HTTP timeout in seconds for self research.")
    parser.add_argument("--self-verify-email-smtp", action="store_true", default=env_config.self_verify_email_smtp, help="Use optional SMTP mailbox probes for self-researched emails.")
    parser.add_argument("--reasoning-effort", default=env_config.reasoning_effort, choices=["low", "middle", "high"], help="AI reasoning effort.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed AI research logging.")
    args = parser.parse_args(argv)

    return ResearchConfig(
        provider=args.provider,
        mode_name=args.mode,
        gemini_model=args.gemini_model,
        openai_model=args.openai_model,
        ollama_model=args.ollama_model,
        ollama_base_url=args.ollama_base_url,
        model=_model_for_provider(args.provider, args.gemini_model, args.openai_model, args.ollama_model),
        min_companies=args.min_companies,
        max_companies=args.max_companies,
        person_emails_per_company=args.person_emails_per_company,
        base_dir=Path(args.base_dir).resolve(),
        write_output=env_config.write_output and not args.no_write_output,
        verbose=env_config.verbose or args.verbose,
        upload_attachments=env_config.upload_attachments and not args.no_upload_attachments,
        reasoning_effort=args.reasoning_effort,
        send_target_count=args.send_target_count,
        max_iterations=args.max_iterations,
        parallel_threads=args.parallel_threads,
        self_search_keywords=tuple(args.self_search_keywords or env_config.self_search_keywords),
        self_search_pages=args.self_search_pages,
        self_results_per_page=args.self_results_per_page,
        self_crawl_max_pages_per_site=args.self_crawl_max_pages_per_site,
        self_crawl_depth=args.self_crawl_depth,
        self_request_timeout=args.self_request_timeout,
        self_verify_email_smtp=args.self_verify_email_smtp,
    )


def run_research(config: ResearchConfig) -> tuple[Path | None, list[Recipient]]:
    """
    Führt einen kompletten Recherche-Durchlauf aus.
    Wählt zwischen KI-Providern (Gemini, OpenAI) und lokaler Recherche (self, Ollama).
    Verwaltet das Sammeln und Speichern der Ergebnisse.
    
    Args:
        config (ResearchConfig): Die Konfiguration für diesen Lauf.
        
    Returns:
        tuple[Path | None, list[Recipient]]: Pfad zur erstellten Datei und Liste der neuen Leads.
    """
    if config.min_companies < 1 or config.max_companies < config.min_companies:
        raise ValueError("Company limits must satisfy 1 <= min_companies <= max_companies.")
    if config.parallel_threads < 1:
        raise ValueError("parallel_threads must be at least 1.")
    if config.self_search_pages < 1:
        raise ValueError("self_search_pages must be at least 1.")
    if config.self_results_per_page < 1:
        raise ValueError("self_results_per_page must be at least 1.")
    if config.self_crawl_max_pages_per_site < 1:
        raise ValueError("self_crawl_max_pages_per_site must be at least 1.")
    if config.self_crawl_depth < 0:
        raise ValueError("self_crawl_depth must be at least 0.")

    _info(
        f"Starting AI research: mode={config.mode_name}, provider={config.provider}, "
        f"model={config.model}, reasoning={config.reasoning_effort}, target={config.min_companies}-{config.max_companies} companies."
    )
    _verbose(config.verbose, f"Base directory: {config.base_dir}")
    _verbose(config.verbose, f"AI provider: {config.provider}")
    _verbose(config.verbose, f"research mode setting: {config.mode_name}")
    _verbose(config.verbose, f"AI model: {config.model}")
    _verbose(config.verbose, f"Ollama base URL: {config.ollama_base_url}")
    _verbose(config.verbose, f"Reasoning effort: {config.reasoning_effort}")
    _verbose(config.verbose, f"Company target range: {config.min_companies}-{config.max_companies}")
    _verbose(config.verbose, f"Person emails per company target: {config.person_emails_per_company}")
    _verbose(config.verbose, f"Write output CSV: {config.write_output}")
    _verbose(config.verbose, f"Upload attachment context to AI provider: {config.upload_attachments}")
    _verbose(config.verbose, f"Parallel research threads: {config.parallel_threads}")
    _verbose(config.verbose, f"Self research keywords: {list(config.self_search_keywords)}")

    mode = get_mode(config.mode_name, config.base_dir)
    _info(f"Resolved mode: {mode.label}.")
    _verbose(config.verbose, f"Resolved mode: {mode.label}")
    _verbose(config.verbose, f"Mode input directory: {mode.recipients_dir}")
    _verbose(config.verbose, f"Mode attachment directory: {mode.attachments_dir}")
    _verbose(config.verbose, f"Mode output CSV log: {mode.log_path}")

    _info("Preparing CV/resume and sent-log context for AI upload.")
    attachments = list_research_context_files(mode, config.verbose) if config.upload_attachments else []
    if not config.upload_attachments:
        _info("Research context upload disabled; AI will use prompt, input context, and web search only.")
        _verbose(config.verbose, "Attachment upload disabled; the provider will use prompt, input context, and web search only.")
    if attachments:
        _info(f"Research context files queued: {len(attachments)}.")
        for attachment in attachments:
            _verbose(config.verbose, f"Attachment context queued for provider upload: {attachment}")
    elif config.upload_attachments:
        _info("No CV/resume or sent-log context files found for this mode.")
        _verbose(config.verbose, "No CV/resume or sent-log attachment context files found for this mode.")

    _info("Loading existing email and company exclusions from input files and output logs.")
    existing_emails = collect_existing_emails(config.base_dir, config.verbose)
    existing_companies = collect_mode_existing_companies(mode, config.verbose)
    _verbose(config.verbose, f"Existing email exclusions loaded: {len(existing_emails)}")
    _verbose(config.verbose, f"Existing company exclusions loaded for this mode: {len(existing_companies)}")

    _info("Reading mode-specific input context.")
    input_context = read_input_context(mode.recipients_dir, verbose=config.verbose)
    _verbose(config.verbose, f"Mode-specific input context characters: {len(input_context)}")

    if config.provider.strip().lower() == "self":
        recipients = run_self_research(config, mode, existing_emails, existing_companies)
        output_path = None
        if config.write_output:
            output_path = write_recipients_csv(mode.recipients_dir, mode.label, recipients)
            _info(f"Wrote self-research CSV: {output_path}.")
            _verbose(config.verbose, f"Wrote self-research CSV: {output_path}")
        else:
            _info("Research CSV writing is disabled; no output file was written.")
        _info("Self research finished successfully.")
        return output_path, recipients

    if config.provider.strip().lower() == "ollama":
        recipients = run_ollama_web_research(config, mode, existing_emails, existing_companies)
        output_path = None
        if config.write_output:
            output_path = write_recipients_csv(mode.recipients_dir, mode.label, recipients)
            _info(f"Wrote Ollama web-research CSV: {output_path}.")
            _verbose(config.verbose, f"Wrote Ollama web-research CSV: {output_path}")
        else:
            _info("Research CSV writing is disabled; no output file was written.")
        _info("Ollama web research finished successfully.")
        return output_path, recipients

    all_recipients: list[Recipient] = []
    seen_emails_in_run: set[str] = {email.lower() for email in existing_emails}
    seen_companies_in_run: set[str] = {company for company in existing_companies or set() if company}

    # We aim for roughly max_companies as the total target for this run,
    # or the global send_target_count if provided.
    target_count = config.send_target_count if config.send_target_count > 0 else config.max_companies
    max_iterations = config.max_iterations
    iteration = 0

    while len(all_recipients) < target_count:
        if 0 < max_iterations <= iteration:
            _info(f"Stopping research because max_iterations={max_iterations} was reached.")
            break

        remaining_target = target_count - len(all_recipients)
        batch_size = config.parallel_threads
        if max_iterations > 0:
            batch_size = min(batch_size, max_iterations - iteration)

        batch_start = iteration + 1
        iteration += batch_size

        _info(f"Progress: {len(all_recipients)}/{target_count} recipients found. {remaining_target} missing.")

        prompt = build_prompt(config, mode, seen_emails_in_run, seen_companies_in_run, input_context)
        _verbose(config.verbose, f"AI prompt characters: {len(prompt)}")

        _info(f"Calling AI provider with up to {batch_size} parallel request(s).")

        stop_event = threading.Event()
        batch_new_count = 0
        sink = ThreadSafeRecipientSink(target_count, seen_emails_in_run, seen_companies_in_run, config)

        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = {
                executor.submit(
                    _generate_and_process_response,
                    config, mode, prompt, attachments, sink, input_context, stop_event
                ): i
                for i in range(batch_size)
            }

            for future in as_completed(futures):
                if stop_event.is_set():
                    continue

                try:
                    thread_added = future.result()
                    batch_new_count += thread_added
                    if thread_added > 0:
                        _info(f"Added {thread_added} new recipients from AI response. Total found in run: {len(all_recipients) + len(sink.recipients)}/{target_count}.")

                    if sink.is_full():
                        _info(f"Target of {target_count} reached. Stopping batch.")
                        stop_event.set()
                except Exception as e:
                    _info(f"AI request failed in thread: {type(e).__name__}: {e}")

        batch_actually_added = 0
        for r in sink.recipients:
            email_key = r.email.lower()
            if email_key not in seen_emails_in_run:
                all_recipients.append(r)
                seen_emails_in_run.add(email_key)
                comp_key = _normalize_company(r.company)
                if comp_key:
                    seen_companies_in_run.add(comp_key)
                batch_actually_added += 1

        _info(f"New recipients added in this batch: {batch_actually_added}.")

        if batch_actually_added == 0:
            _info("No more new recipients found in this batch.")
            if batch_start == 1:
                raise RuntimeError("AI provider returned no new usable email addresses on the first attempt.")
            break

    recipients = all_recipients
    _info(f"Total usable new recipients found: {len(recipients)}.")
    _verbose(config.verbose, f"Total usable new recipients after {iteration} iteration(s): {len(recipients)}")

    output_path = None
    if config.write_output:
        output_path = write_recipients_csv(mode.recipients_dir, mode.label, recipients)
        _info(f"Wrote research CSV: {output_path}.")
        _verbose(config.verbose, f"Wrote research CSV: {output_path}")
    else:
        _info("Research CSV writing is disabled; no output file was written.")
        _verbose(config.verbose, "research CSV was not written because output writing is disabled.")
    _info("AI research finished successfully.")
    return output_path, recipients


def _generate_and_process_response(
        config: ResearchConfig,
        mode: MailMode,
        prompt: str,
        attachments: list[Path],
        sink: RecipientSink,
        input_context: str,
        stop_event: threading.Event | None = None,
) -> int:
    """
    Interne Worker-Methode: Generiert eine KI-Antwort und verarbeitet die darin 
    enthaltenen Leads sofort parallel im selben Thread.
    """
    if stop_event and stop_event.is_set():
        return 0
    if sink.is_full():
        return 0

    # We use a placeholder for existing_emails because the sink handles the actual checking.
    # However, _needs_retry needs it for a quick heuristic.
    raw_response = _generate_research_response(config, mode, prompt, attachments, set(), input_context, stop_event)
    if not raw_response:
        return 0

    _verbose(config.verbose, f"Raw AI response characters: {len(raw_response)}")

    # We parse without filters first, then let the sink decide.
    # To do this, we pass empty sets to parse_recipients.
    candidates = parse_recipients(raw_response, set(), set(), config.verbose)

    added_count = 0
    for cand in candidates:
        if stop_event and stop_event.is_set():
            break
        if sink.add_recipient(cand):
            added_count += 1
            if sink.is_full():
                if stop_event:
                    stop_event.set()
                break
    return added_count


def _generate_research_response(
        config: ResearchConfig,
        mode: MailMode,
        prompt: str,
        attachments: list[Path],
        existing_emails: set[str],
        input_context: str,
        stop_event: threading.Event | None = None,
) -> str | None | Any:
    """
    Kümmert sich um den eigentlichen KI-Aufruf inklusive Fehlerbehandlung und Retries.
    """
    if stop_event and stop_event.is_set():
        return ""

    raw_response = str(generate_with_provider(
        config.provider, config.model, prompt, attachments, config.reasoning_effort, config.verbose, config.ollama_base_url
    ))
    if stop_event and stop_event.is_set():
        return raw_response

    if _needs_retry(raw_response, existing_emails, config.verbose) and attachments:
        _info("AI response was not usable yet; retrying once without attachment uploads.")
        _verbose(config.verbose, "AI provider returned no usable CSV with attachment uploads; retrying once without attachment uploads.")
        if stop_event and stop_event.is_set():
            return raw_response

        raw_response = str(generate_with_provider(
            config.provider, config.model, prompt, [], config.reasoning_effort, config.verbose, config.ollama_base_url
        ))
    if stop_event and stop_event.is_set():
        return raw_response

    if _needs_retry(raw_response, existing_emails, config.verbose):
        retry_prompt = build_prompt(config, mode, set(), set(), input_context)
        _info("AI response still was not usable; retrying once with a smaller prompt.")
        _verbose(config.verbose, "AI provider still returned no usable CSV; retrying once with a smaller prompt and local post-filtering.")
        _verbose(config.verbose, f"Lite AI prompt characters: {len(retry_prompt)}")
        if stop_event and stop_event.is_set():
            return raw_response

        raw_response = str(generate_with_provider(
            config.provider, config.model, retry_prompt, [], config.reasoning_effort, config.verbose, config.ollama_base_url
        ))
    return raw_response


def run_self_research(
        config: ResearchConfig,
        mode: MailMode,
        existing_emails: set[str],
        existing_companies: set[str],
) -> list[Recipient]:
    """Compatibility wrapper around the self research base workflow."""
    return _self_research.run_self_research(config, mode, existing_emails, existing_companies)


def run_ollama_web_research(
        config: ResearchConfig,
        mode: MailMode,
        existing_emails: set[str],
        existing_companies: set[str],
) -> list[Recipient]:
    """Fuehrt aus Ollama-Ausgabe web Recherche."""
    return _self_research.run_ollama_web_research(config, mode, existing_emails, existing_companies)


def self_search_queries(config: ResearchConfig, mode: MailMode) -> list[str]:
    """Fuehrt die Logik fuer self_search_queries aus."""
    return _self_research.self_search_queries(config, mode)


def crawl_self_result_url(*args, **kwargs):
    """Compatibility wrapper around the self research crawling logic."""
    return _self_research.crawl_self_result_url(*args, **kwargs)


def _extract_google_result_urls(*args, **kwargs):
    """Compatibility wrapper for testing."""
    return _self_research._extract_google_result_urls(*args, **kwargs)


def collect_self_search_result_urls(*args, **kwargs):
    """Compatibility wrapper for testing."""
    return _self_research.collect_self_search_result_urls(*args, **kwargs)


def _fetch_text(*args, **kwargs):
    """Compatibility wrapper for testing."""
    return _self_research.fetch_text(*args, **kwargs)


def normalize_company(company: str) -> str:
    """Normalisiert Unternehmen."""
    return _parsing.normalize_company(company)

def list_resume_attachments(directory: Path, verbose: bool = False) -> list[Path]:
    """
    Listet alle Dateien in einem Verzeichnis auf, die nach Lebensläufen aussehen (CV, Resume).
    """
    all_attachments = list_attachments(directory)
    _verbose(verbose, f"Attachment files found before CV/resume filter: {len(all_attachments)}")
    resume_attachments = [
        path
        for path in all_attachments
        if RESUME_ATTACHMENT_PATTERN.search(path.stem)
    ]
    for path in all_attachments:
        _verbose(verbose, f"Attachment filter {'kept' if path in resume_attachments else 'skipped'}: {path.name}")
    return resume_attachments


def list_research_context_files(mode: MailMode, verbose: bool = False) -> list[Path]:
    """
    Sammelt Dateien, die der KI als Kontext mitgegeben werden sollen (CVs, Sent-Logs).
    """
    context_files = list_resume_attachments(mode.attachments_dir, verbose)
    if mode.log_path.exists():
        context_files.append(mode.log_path)
        _verbose(verbose, f"Sent-log context queued for provider upload: {mode.log_path}")
    else:
        _verbose(verbose, f"Sent-log context file does not exist yet and will not be uploaded: {mode.log_path}")
    return context_files


def _needs_retry(raw_response: str, existing_emails: set[str], verbose: bool = False) -> bool:
    """
    Prüft, ob die KI-Antwort unzureichend war und ein erneuter Versuch (Retry) sinnvoll ist.
    """
    if _is_model_error(raw_response, verbose):
        return True
    _verbose(verbose, "No Model error")
    try:
        return not parse_recipients(raw_response, existing_emails, verbose=verbose)
    except ValueError as error:
        _verbose(verbose, "Failed to parse CSV")
        _verbose(verbose, f"{error}")
        return True


def _is_model_error(raw_response: str, verbose: bool = False) -> bool:
    """Prueft model error."""
    if not raw_response or raw_response == "":
        return True

    text = raw_response.strip().lower()
    error_markers = [
        "encountered an error",
        "please try again",
        "unable to fulfill",
        "cannot fulfill",
    ]
    output = any(marker in text for marker in error_markers)
    if output:
        _verbose(verbose, f"AI provider returned an error: {text}")
    return output


def collect_existing_emails(base_dir: Path, verbose: bool = False) -> set[str]:
    """
    Sammelt alle bereits bekannten E-Mail-Adressen aus dem Output-Verzeichnis 
    und allen Input-Dateien aller Modi.
    """
    emails: set[str] = set()
    output_dir = base_dir / "output"

    # Load all emails from output logs (excluding invalid_mails.csv)
    logged = read_known_output_emails(output_dir)
    emails.update(logged)
    _verbose(verbose, f"Loaded {len(logged)} logged email exclusion(s) from {output_dir}.")

    # Load invalid emails
    invalid_path = output_dir / "invalid_mails.csv"
    if invalid_path.exists():
        invalid = read_logged_emails(invalid_path)
        emails.update(invalid)
        _verbose(verbose, f"Loaded {len(invalid)} invalid email exclusion(s) from {invalid_path}.")

    # Load from all input directories
    for mode_name in MODE_NAMES:
        mode = get_mode(mode_name, base_dir)
        recipient_files = list_recipient_files(mode.recipients_dir)
        for path in recipient_files:
            recipients = read_recipients(path)
            emails.update(recipient.email.lower() for recipient in recipients)
    return emails


def collect_mode_existing_companies(mode: MailMode, verbose: bool = False) -> set[str]:
    """
    Sammelt alle bereits kontaktierten Firmennamen für einen spezifischen Modus.
    """
    companies = {
        _normalize_company(row["company"])
        for row in read_logged_rows(mode.log_path)
        if _normalize_company(row["company"])
    }
    _verbose(verbose, f"Loaded {len(companies)} logged company exclusion(s) from {mode.log_path}.")
    recipient_files = list_recipient_files(mode.recipients_dir)
    for path in recipient_files:
        recipients = read_recipients(path)
        companies.update(_normalize_company(recipient.company) for recipient in recipients if _normalize_company(recipient.company))
        _verbose(verbose, f"Loaded company exclusions from input file: {path}.")
    return companies


def _is_verbose_log_enabled(verbose: bool) -> bool:
    """Prueft Verbose-Ausgabe Logdaten enabled."""
    return verbose


def read_input_context(directory: Path, max_chars: int = 6000, verbose: bool = False) -> str:
    """
    Liest vorhandene Lead-Dateien aus dem Input-Ordner ein, um sie der KI als Kontext zu geben.
    Kürzt den Text, falls er zu lang wird.
    """
    parts: list[str] = []
    files = list_recipient_files(directory)
    _verbose(verbose, f"Input context files found: {len(files)}.")
    for path in files:
        try:
            text = path.read_text(encoding="utf-8-sig")
            _verbose(verbose, f"Read input context file with utf-8-sig: {path}.")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
            _verbose(verbose, f"Read input context file with replacement decoding: {path}.")
        cleaned = text.strip()
        if cleaned:
            parts.append(f"File: {path.name}\n{cleaned}")
            _verbose(verbose, f"Added input context from {path.name}: {len(cleaned)} characters.")
        else:
            _verbose(verbose, f"Skipped empty input context file: {path.name}.")

    context = "\n\n".join(parts)
    if len(context) > max_chars:
        _verbose(verbose, f"Input context truncated from {len(context)} to {max_chars} characters.")
        return context[:max_chars].rstrip() + "\n...[truncated]"
    return context


def build_prompt(
        config: ResearchConfig,
        mode: MailMode,
        existing_emails: set[str],
        existing_companies: set[str] | None = None,
        input_context: str = "",
) -> str:
    """
    Erstellt den finalen KI-Prompt durch Kombination des Overseer-Templates 
    mit den modusspezifischen Anweisungen und dem aktuellen Kontext.
    """
    if isinstance(existing_companies, str) and not input_context:
        input_context = existing_companies
        existing_companies = None

    excluded = "\n".join(sorted(existing_emails)) or "(none)"
    excluded_companies = "\n".join(sorted(existing_companies or set())) or "(none)"
    input_reference = input_context.strip() or "(no mode-specific input files found)"

    contact_requirement = (
        f"- For PhD, include the general company contact email plus up to {config.person_emails_per_company} "
        "decision-maker work emails per company when public sources support them."
        if mode.label == "PhD"
        else "- For Freelance, one general or relevant contact email per company is enough. But 2 would be better!"
    )

    overseer_template = mode_instructions.instructions.get("Overseer", "")
    if not overseer_template:
        # Fallback to hardcoded if for some reason missing
        from mail_sender.prompts import DEFAULT_PROMPTS
        overseer_template = DEFAULT_PROMPTS["Overseer"]

    return overseer_template.format(
        MODE_LABEL=mode.label,
        TASK_INSTRUCTIONS=mode_instructions.instructions.get(mode.label, ""),
        MIN_COMPANIES=config.min_companies,
        MAX_COMPANIES=config.max_companies,
        CONTACT_REQUIREMENT=contact_requirement,
        EXCLUDED_EMAILS=excluded,
        EXCLUDED_COMPANIES=excluded_companies,
        INPUT_CONTEXT=input_reference
    )


def write_recipients_csv(directory: Path, mode_label: str, recipients: list[Recipient]) -> Path:
    """
    Speichert die gefundenen Leads in einer neuen CSV-Datei im Input-Verzeichnis des Modus.
    """
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_mode = mode_label.lower().replace(" ", "_")
    path = directory / f"research_{safe_mode}_{timestamp}.csv"

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["company", "mail", "source_url"])
        for recipient in recipients:
            writer.writerow([recipient.company, recipient.email, ""])
    return path


def _model_for_provider(provider: str, gemini_model: str, openai_model: str, ollama_model: str = "llama3.1:8b") -> str:
    """
    Hilfsfunktion zur Auswahl des Modellnamens basierend auf dem gewählten Provider.
    """
    normalized = provider.strip().lower()
    if normalized == "self":
        return "self"
    if normalized == "ollama":
        return os.getenv("OLLAMA_MODEL", ollama_model)
    if normalized == "openai":
        return os.getenv("OPENAI_MODEL", openai_model)
    return os.getenv("GEMINI_MODEL", gemini_model)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
