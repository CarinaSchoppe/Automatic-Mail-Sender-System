"""
Main pipeline for AI-powered lead research.
Manages the process from prompt creation and AI calls to parsing and saving results.
Supports multi-threading for parallel requests.
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
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
from pathlib import Path
from typing import cast, Any

from dotenv import load_dotenv

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from mail_sender.attachments import list_attachments
from mail_sender.email_validation import validate_email_address
from mail_sender.modes import MailMode, get_available_mode_names, get_mode
from mail_sender.recipients import Recipient, list_recipient_files, read_recipients
from mail_sender.sent_log import append_invalid_email, read_logged_emails, read_logged_rows, read_known_output_emails
from mail_sender.validation_policy import (
    EXTERNAL_VALIDATION_DISABLED,
    EXTERNAL_VALIDATION_SERVICES,
    EXTERNAL_VALIDATION_STAGES,
    NEVERBOUNCE_API_KEY,
    NEVERBOUNCE_SERVICE,
    VALIDATION_STAGE_RESEARCH,
    normalize_validation_service,
    normalize_validation_stage,
)
from research import parsing as _parsing
from research.providers import (
    generate_with_gemini as _gemini_generate,
    generate_with_ollama as _ollama_generate,
    generate_with_openai as _openai_generate,
)
from research import providers as _providers
from research import self_research as _self_research
from research.logging_utils import info as _info, set_thread_id as _set_thread_id
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

EMAIL_KEYS = {"mail", "email", "recipient", "recipients", "target", "recipient", "receiver"}
COMPANY_KEYS = {"company", "firm", "organization", "organization", "name"}
PROVIDER_PREFIXES = ("gemini", "openai", "ollama", "self")
RESEARCH_CONTEXT_DELIVERY_CHOICES = ("upload_files", "paste_in_prompt")
OLLAMA_MODEL_PREFIXES = (
    "llama",
    "mistral",
    "mixtral",
    "qwen",
    "deepseek",
    "phi",
    "gemma",
    "codellama",
    "nomic",
    "starcoder",
    "vicuna",
    "orca",
    "yi",
    "granite",
    "devstral",
)


def generate_with_provider(*args, **kwargs):
    """
    Delegates the call to generate leads to the corresponding provider client.

    Args:
        *args: Variable positional arguments.
        **kwargs: Variable keyword arguments.

    Returns:
        The lead generation result (usually a CSV string).
    """
    return _providers.generate_with_provider(*args, **kwargs)


def generate_with_gemini(*args, **kwargs):
    """
    Delegates the call to generate leads specifically to Google Gemini.
    """
    return _gemini_generate(*args, **kwargs)


def generate_with_openai(*args, **kwargs):
    """
    Delegates the call to generate leads specifically to OpenAI.
    """
    return _openai_generate(*args, **kwargs)


def generate_with_ollama(*args, **kwargs):
    """
    Delegates the call to generate leads specifically to a local Ollama instance.
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
    A thread-safe container for collecting validated leads (recipients).
    Prevents duplicate entries and stops the search once the target is reached.
    """

    def __init__(
            self,
            target_count: int,
            seen_emails: set[str],
            seen_companies: set[str],
            config: ResearchConfig,
            mode: MailMode,
            global_target_count: int | None = None,
            initial_count: int = 0,
    ):
        """
        Initializes the sink with targets and already known data.

        Args:
            target_count (int): Number of desired email addresses for this specific batch/sink.
            seen_emails (set[str]): Set of already contacted emails (deduplication).
            seen_companies (set[str]): Set of already researched companies.
            config (ResearchConfig): The current research configuration.
            mode (MailMode): The current email mode (for storage paths).
            global_target_count (int): The total target across all batches.
            initial_count (int): Number of leads already found in previous batches.
        """
        self.target_count = target_count
        self.global_target_count = target_count if global_target_count is None else global_target_count
        self.initial_count = initial_count
        self.seen_emails = {email.lower() for email in seen_emails}
        self.seen_companies = {company for company in seen_companies if company}
        self.config = config
        self.mode = mode
        self.recipients: list[Recipient] = []
        self.lock = threading.RLock()
        self.thread_files: dict[int | None, Path] = {}

    def _get_thread_file(self, thread_id: int | None) -> Path | None:
        """
        Returns the path to the CSV file for a specific thread.
        Creates the file and header if not already done.
        """
        if not self.config.write_output:
            return None

        with self.lock:
            if thread_id in self.thread_files:
                return self.thread_files[thread_id]

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            safe_mode = self.mode.label.lower().replace(" ", "_")
            thread_suffix = f"_T{thread_id}" if thread_id is not None else ""

            filename = f"leads_{safe_mode}_{timestamp}{thread_suffix}_{unique_id}.csv"
            path = self.mode.recipients_dir / filename

            try:
                self.mode.recipients_dir.mkdir(parents=True, exist_ok=True)
                with path.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["company", "mail", "source_url"])
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                self.thread_files[thread_id] = path
                return path
            except OSError as e:
                _verbose(self.config.verbose, f"Could not create thread-specific lead file {path}: {e}")
                return None

    def add_recipient(self, recipient: Recipient, thread_id: int | None = None) -> bool:
        """
        Attempts to add a new recipient. Checks for duplicates and target achievement.
        Writes the recipient immediately to a thread-specific CSV file upon success.

        Args:
            recipient (Recipient): The found lead.
            thread_id (int, optional): The ID of the calling thread for separate files.

        Returns:
            bool: True if the total target (target_count) has been reached, otherwise False.
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
                external_service=(
                    self.config.external_validation_service
                    if self.config.external_validation_stage == VALIDATION_STAGE_RESEARCH
                    else EXTERNAL_VALIDATION_DISABLED
                ),
                external_api_key=(
                    self.config.external_validation_api_key
                    if self.config.external_validation_stage == VALIDATION_STAGE_RESEARCH
                    else ""
                ),
            )
            # Support both real and SimpleNamespace mocks
            is_valid = getattr(validation, "is_valid", False)
            reason = getattr(validation, "reason", "unknown")
        except OSError as e:  # pragma: no cover
            _verbose(self.config.verbose, f"Validation failed with exception for {recipient.email}: {e}")
            return False
        if not is_valid:
            _verbose(self.config.verbose, f"Recipient {recipient.email} rejected: {reason}")
            if (
                    self.config.external_validation_service == NEVERBOUNCE_SERVICE
                    and self.config.external_validation_stage == VALIDATION_STAGE_RESEARCH
                    and str(reason).startswith("NeverBounce:")
            ):
                append_invalid_email(self.mode.log_path.parent / "invalid_mails.csv", recipient, str(reason))
                _verbose(self.config.verbose, f"NeverBounce rejected research lead {recipient.email}; logged to invalid_mails.csv.")
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

            total_found = self.initial_count + len(self.recipients)
            missing_count = max(0, self.global_target_count - total_found)

            _verbose(self.config.verbose, f"Accepted {recipient.email}: {total_found}/{self.global_target_count} found, {missing_count} missing.")

            # Instant save to CSV
            thread_file = self._get_thread_file(thread_id)
            if thread_file:
                try:
                    with thread_file.open("a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow([recipient.company, recipient.email, recipient.source_url])
                        f.flush()
                        try:
                            os.fsync(f.fileno())
                        except OSError:
                            pass
                except OSError as e:
                    _verbose(self.config.verbose, f"Instant save failed for {recipient.email}: {e}")

            return True

    def target_status(self) -> tuple[int, int, int]:
        """Returns current global target progress as current, missing, target."""
        with self.lock:
            total_found = self.initial_count + len(self.recipients)
            missing_count = max(0, self.global_target_count - total_found)
            return total_found, missing_count, self.global_target_count

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
    Loads general settings from settings.toml in the project root directory.
    """
    settings_path = CODE_DIR.parent / "settings.toml"
    if not settings_path.exists():
        return {}
    try:
        with settings_path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def provider_and_model_from_research_model(research_model: str, fallback_provider: str = "gemini") -> tuple[str, str]:
    """
    Derives the provider from one user-facing RESEARCH_MODEL value.
    Prefixes like openai:gpt-5.4 or ollama:llama3.1:8b force the provider.
    """
    raw_model = str(research_model or "").strip()
    if not raw_model:
        return fallback_provider.strip().lower() or "gemini", raw_model

    lowered = raw_model.lower()
    prefix, separator, rest = raw_model.partition(":")
    if separator and prefix.lower() in PROVIDER_PREFIXES:
        provider = prefix.lower()
        model = rest.strip()
        return provider, "self" if provider == "self" else model

    if lowered == "self":
        return "self", "self"
    if lowered.startswith("gemini"):
        return "gemini", raw_model
    if lowered.startswith(("gpt", "chatgpt", "o1", "o3", "o4", "o5")):
        return "openai", raw_model
    if ":" in raw_model or lowered.startswith(OLLAMA_MODEL_PREFIXES):
        return "ollama", raw_model
    return fallback_provider.strip().lower() or "gemini", raw_model


_provider_and_model_from_research_model = provider_and_model_from_research_model


def _legacy_model_for_provider(provider: str, gemini_model: str, openai_model: str, ollama_model: str = "llama3.1:8b") -> str:
    """Returns the old provider-specific model value for compatibility."""
    normalized = provider.strip().lower()
    if normalized == "self":
        return "self"
    if normalized == "ollama":
        return os.getenv("OLLAMA_MODEL", ollama_model)
    if normalized == "openai":
        return os.getenv("OPENAI_MODEL", openai_model)
    return os.getenv("GEMINI_MODEL", gemini_model)


def default_config() -> ResearchConfig:
    """
    Creates a standard configuration based on environment variables and the settings.toml file.
    """
    load_dotenv()
    settings = _load_settings()

    def _get(key: str, default):
        """Retrieves data."""
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

    legacy_provider = cast(str, _get("RESEARCH_AI_PROVIDER", "gemini"))
    gemini_model = cast(str, _get("GEMINI_MODEL", "gemini-3-flash-preview"))
    openai_model = cast(str, _get("OPENAI_MODEL", "gpt-5.4-mini-2026-03-17"))
    ollama_model = cast(str, _get("OLLAMA_MODEL", "llama3.1:8b"))
    research_model = cast(str, _get("RESEARCH_MODEL", ""))
    if research_model:
        provider, model = provider_and_model_from_research_model(research_model, legacy_provider)
    else:
        provider = legacy_provider
        model = _legacy_model_for_provider(provider, gemini_model, openai_model, ollama_model)
    if provider == "gemini":
        gemini_model = model
    elif provider == "openai":
        openai_model = model
    elif provider == "ollama":
        ollama_model = model
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
        model=model,
        min_companies=cast(int, _get("RESEARCH_MIN_COMPANIES", 15)),
        max_companies=cast(int, _get("RESEARCH_MAX_COMPANIES", 25)),
        person_emails_per_company=cast(int, _get("RESEARCH_PERSON_EMAILS_PER_COMPANY", 3)),
        base_dir=Path(cast(str, _get("RESEARCH_BASE_DIR", str(CODE_DIR.parent)))).resolve(),
        write_output=cast(bool, _get("RESEARCH_WRITE_OUTPUT", True)),
        verbose=cast(bool, _get("RESEARCH_VERBOSE", False)),
        upload_attachments=cast(bool, _get("RESEARCH_UPLOAD_ATTACHMENTS", True)),
        research_context_delivery=cast(str, _get("RESEARCH_CONTEXT_DELIVERY", "upload_files")),
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
        external_validation_service=normalize_validation_service(
            cast(str, _get("EXTERNAL_VALIDATION_SERVICE", EXTERNAL_VALIDATION_DISABLED)),
        ),
        external_validation_api_key=os.getenv(NEVERBOUNCE_API_KEY, "").strip(),
        external_validation_stage=normalize_validation_stage(
            cast(str, _get("EXTERNAL_VALIDATION_STAGE", VALIDATION_STAGE_RESEARCH)),
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """
    Main entry point for the research script.
    Parses arguments, executes research, and prints a summary.
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
    Parses command-line arguments and creates a ResearchConfig object.
    Combines default values, environment variables, and explicit CLI flags.
    """
    env_config = default_config()
    parser = argparse.ArgumentParser(description="research new lead CSV files with AI providers or self-hosted web scraping.")
    parser.add_argument("--provider", default=None, choices=["gemini", "openai", "ollama", "self"], help="Research provider. Usually inferred from --model.")
    parser.add_argument("--mode", default=env_config.mode_name, help="Research mode. Use any built-in or custom task mode.")
    parser.add_argument("--model", default=None, help="Research model. Provider is inferred from the model name or an optional provider: prefix.")
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
    parser.add_argument(
        "--research-context-delivery",
        default=env_config.research_context_delivery,
        choices=RESEARCH_CONTEXT_DELIVERY_CHOICES,
        help="How known sent/invalid/input context is provided: upload_files or paste_in_prompt.",
    )
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
    parser.add_argument("--external-validation-service", default=env_config.external_validation_service, choices=EXTERNAL_VALIDATION_SERVICES, help="External validation service for research leads before saving.")
    parser.add_argument("--external-validation-api-key", default=env_config.external_validation_api_key, help="API key for the selected external research validation service.")
    parser.add_argument("--external-validation-stage", default=env_config.external_validation_stage, choices=EXTERNAL_VALIDATION_STAGES, help="Run NeverBounce during research before saving or during mail sending before each send.")
    parser.add_argument("--reasoning-effort", default=env_config.reasoning_effort, choices=["low", "middle", "high"], help="AI reasoning effort.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed AI research logging.")
    args = parser.parse_args(argv)

    selected_provider = args.provider or env_config.provider
    if args.model:
        selected_provider, selected_model = provider_and_model_from_research_model(args.model, selected_provider)
    elif args.provider:
        selected_model = _legacy_model_for_provider(args.provider, args.gemini_model, args.openai_model, args.ollama_model)
    else:
        selected_model = env_config.model

    if selected_provider == "gemini":
        args.gemini_model = selected_model
    elif selected_provider == "openai":
        args.openai_model = selected_model
    elif selected_provider == "ollama":
        args.ollama_model = selected_model

    return ResearchConfig(
        provider=selected_provider,
        mode_name=args.mode,
        gemini_model=args.gemini_model,
        openai_model=args.openai_model,
        ollama_model=args.ollama_model,
        ollama_base_url=args.ollama_base_url,
        model=selected_model,
        min_companies=args.min_companies,
        max_companies=args.max_companies,
        person_emails_per_company=args.person_emails_per_company,
        base_dir=Path(args.base_dir).resolve(),
        write_output=env_config.write_output and not args.no_write_output,
        verbose=env_config.verbose or args.verbose,
        upload_attachments=env_config.upload_attachments and not args.no_upload_attachments,
        research_context_delivery=args.research_context_delivery,
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
        external_validation_service=args.external_validation_service,
        external_validation_api_key=args.external_validation_api_key,
        external_validation_stage=args.external_validation_stage,
    )


def run_research(config: ResearchConfig) -> tuple[Path | None, list[Recipient]]:
    """
    Executes a complete research run.
    Chooses between AI providers (Gemini, OpenAI) and local research (self, Ollama).
    Manages collection and storage of results.
    
    Args:
        config (ResearchConfig): The configuration for this run.
        
    Returns:
        tuple[Path | None, list[Recipient]]: Path to the created file and list of new leads.
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
    if (
            config.external_validation_service == NEVERBOUNCE_SERVICE
            and config.external_validation_stage == VALIDATION_STAGE_RESEARCH
            and not config.external_validation_api_key
    ):
        raise ValueError("NEVERBOUNCE_API_KEY is required when EXTERNAL_VALIDATION_SERVICE=neverbounce for research.")

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
    _verbose(config.verbose, f"Research context delivery: {config.research_context_delivery}")
    _verbose(config.verbose, f"Parallel research threads: {config.parallel_threads}")
    _verbose(config.verbose, f"Research external validation: {config.external_validation_service} at {config.external_validation_stage}")
    _verbose(config.verbose, f"Self research keywords: {list(config.self_search_keywords)}")

    mode = get_mode(config.mode_name, config.base_dir)
    _info(f"Resolved mode: {mode.label}.")
    _verbose(config.verbose, f"Resolved mode: {mode.label}")
    _verbose(config.verbose, f"Mode input directory: {mode.recipients_dir}")
    _verbose(config.verbose, f"Mode attachment directory: {mode.attachments_dir}")
    _verbose(config.verbose, f"Mode output CSV log: {mode.log_path}")

    if config.research_context_delivery not in RESEARCH_CONTEXT_DELIVERY_CHOICES:
        raise ValueError(
            "research_context_delivery must be one of: "
            + ", ".join(RESEARCH_CONTEXT_DELIVERY_CHOICES)
        )

    _info(f"Preparing research context via {config.research_context_delivery}.")
    attachments = (
        list_research_context_files(mode, config.verbose)
        if config.upload_attachments and config.research_context_delivery == "upload_files"
        else []
    )
    if not config.upload_attachments:
        _info("Research context upload disabled; AI will use prompt, input context, and web search only.")
        _verbose(config.verbose, "Attachment upload disabled; the provider will use prompt, input context, and web search only.")
    elif config.research_context_delivery == "paste_in_prompt":
        _info("Known sent/invalid/input context will be pasted directly into the AI prompt.")
        _verbose(config.verbose, "Research context delivery paste_in_prompt selected; no context files will be uploaded.")
    if attachments:
        _info(f"Research context files queued: {len(attachments)}.")
        for attachment in attachments:
            _verbose(config.verbose, f"Attachment context queued for provider upload: {attachment}")
    elif config.upload_attachments and config.research_context_delivery == "upload_files":
        _info("No CV/resume or known sent/invalid context files found for this mode.")
        _verbose(config.verbose, "No CV/resume or known sent/invalid attachment context files found for this mode.")

    _info("Loading existing email and company exclusions from input files and output logs.")
    existing_emails = collect_existing_emails(config.base_dir, config.verbose)
    existing_companies = collect_mode_existing_companies(mode, config.verbose)
    context_counts = count_known_context_rows(config.base_dir)
    _verbose(config.verbose, f"Existing email exclusions loaded: {len(existing_emails)}")
    _verbose(config.verbose, f"Existing company exclusions loaded for this mode: {len(existing_companies)}")
    _verbose(
        config.verbose,
        "Known context row counts: "
        f"{context_counts['sent']} sent mail(s), "
        f"{context_counts['invalid']} invalid mail(s), "
        f"{context_counts['input']} input mail(s).",
    )

    _info("Reading mode-specific input context.")
    input_context = read_input_context(mode.recipients_dir, verbose=config.verbose)
    if config.upload_attachments and config.research_context_delivery == "paste_in_prompt":
        known_context = read_known_exclusion_context(config.base_dir, mode, verbose=config.verbose)
        if known_context:
            input_context = "\n\n".join(part for part in [input_context, known_context] if part.strip())
            _info("Known sent/invalid/input context pasted into the AI prompt.")
            _verbose(config.verbose, f"Known pasted exclusion context characters: {len(known_context)}")
    _verbose(config.verbose, f"Mode-specific input context characters: {len(input_context)}")

    if config.provider.strip().lower() == "self":
        target_count = config.send_target_count if config.send_target_count > 0 else config.max_companies
        sink = ThreadSafeRecipientSink(
            target_count,
            existing_emails,
            existing_companies,
            config,
            mode,
            global_target_count=target_count,
            initial_count=0
        )
        recipients = run_self_research(config, mode, existing_emails, existing_companies, sink=sink)
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
        target_count = config.send_target_count if config.send_target_count > 0 else config.max_companies
        sink = ThreadSafeRecipientSink(
            target_count,
            existing_emails,
            existing_companies,
            config,
            mode,
            global_target_count=target_count,
            initial_count=0
        )
        recipients = run_ollama_web_research(config, mode, existing_emails, existing_companies, sink=sink)
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
        _verbose(
            config.verbose,
            "Built AI prompt with known context: "
            f"{context_counts['sent']} sent mail(s), "
            f"{context_counts['invalid']} invalid mail(s), "
            f"{context_counts['input']} input mail(s), "
            f"{len(seen_emails_in_run)} email exclusion(s), "
            f"{len(seen_companies_in_run)} company exclusion(s).",
        )
        _verbose(config.verbose, f"AI prompt characters: {len(prompt)}")
        _verbose(config.verbose, f"Built AI prompt message:\n{prompt}")

        _info(f"Calling AI provider with up to {batch_size} parallel request(s).")

        stop_event = threading.Event()
        batch_new_count = 0
        sink = ThreadSafeRecipientSink(
            remaining_target,
            seen_emails_in_run,
            seen_companies_in_run,
            config,
            mode,
            global_target_count=target_count,
            initial_count=len(all_recipients)
        )

        executor = ThreadPoolExecutor(max_workers=batch_size)
        try:
            futures = {
                executor.submit(
                    _generate_and_process_response,
                    config, mode, prompt, attachments, sink, input_context, stop_event, i, context_counts
                ): i
                for i in range(batch_size)
            }

            pending = set(futures)
            while pending and not stop_event.is_set():
                done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                for future in done:
                    try:
                        thread_added = future.result()
                        batch_new_count += thread_added
                        if thread_added > 0:
                            _info(f"Added {thread_added} new recipients from AI response. Total found in run: {len(all_recipients) + len(sink.recipients)}/{target_count}.")

                        if sink.is_full():
                            _info(f"Target of {target_count} reached. Stopping batch.")
                            stop_event.set()
                    except (OSError, RuntimeError, ValueError) as e:
                        _info(f"AI request failed in thread: {type(e).__name__}: {e}")

            if stop_event.is_set():
                _info("Hard cut: target reached, proceeding without waiting for remaining AI requests.")

        finally:
            # shutdown(wait=False) prevents waiting for running threads when exiting the try/finally.
            # However, if we are using the context manager 'with ThreadPoolExecutor', it would still wait.
            # So we use a manual try-finally to ensure we can control the wait behavior.
            executor.shutdown(wait=False)

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
        thread_id: int | None = None,
        context_counts: dict[str, int] | None = None,
) -> int:
    """
    Internal worker method: Generates an AI response and processes the contained 
    leads immediately in parallel in the same thread.
    """
    if stop_event and stop_event.is_set():
        return 0
    if sink.is_full():
        return 0

    thread_label = thread_id if thread_id is not None else "X"
    _set_thread_id(f"Thread-{thread_label}")
    _info("Starting new search analysis...")
    counts = context_counts or {"sent": 0, "invalid": 0, "input": 0}
    _verbose(
        config.verbose,
        f"Thread {thread_label} sending AI prompt with known context: "
        f"{counts.get('sent', 0)} sent/valid mail(s), "
        f"{counts.get('invalid', 0)} invalid mail(s), "
        f"{counts.get('input', 0)} input mail(s).",
    )
    _verbose(config.verbose, f"Thread {thread_label} AI prompt sent:\n{prompt}")
    # We use a placeholder for existing_emails because the sink handles the actual checking.
    # However, _needs_retry needs it for a quick heuristic.
    raw_response = _generate_research_response(config, prompt, attachments, set(), stop_event)
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
        if sink.add_recipient(cand, thread_id=thread_id):
            added_count += 1
            if sink.is_full():
                if stop_event:
                    stop_event.set()
                break

    with sink.lock:
        current_total = len(sink.recipients)
        target = sink.target_count
        missing = max(0, target - current_total)

    if hasattr(sink, "target_status"):
        global_total, global_missing, global_target = sink.target_status()
    else:
        global_total, global_missing, global_target = current_total, missing, target
    _info(
        f"Thread {thread_label} added {added_count} new email(s) to the global target list. "
        f"The global target list now has {global_total} email(s); "
        f"{global_missing} still missing to reach target {global_target}."
    )

    _info(f"Parsed {len(candidates)} candidates, added {added_count} new. Total: {current_total}/{target}, missing: {missing}")
    return added_count


def _generate_research_response(
        config: ResearchConfig,
        prompt: str,
        attachments: list[Path],
        existing_emails: set[str],
        stop_event: threading.Event | None = None,
) -> str | None | Any:
    """
    Handles the actual AI call including error handling and retries.
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
        retry_prompt = prompt
        _info("AI response still was not usable; retrying once with a smaller prompt that keeps the same exclusions.")
        _verbose(config.verbose, "AI provider still returned no usable CSV; retrying once without attachments while keeping the same exclusions.")
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
        sink: RecipientSink | None = None,
) -> list[Recipient]:
    """Compatibility wrapper around the self research base workflow."""
    if sink is None:
        target_count = config.send_target_count if config.send_target_count > 0 else config.max_companies
        sink = ThreadSafeRecipientSink(target_count, existing_emails, existing_companies, config, mode)
    return _self_research.run_self_research(config, mode, existing_emails, existing_companies, sink=sink)


def run_ollama_web_research(
        config: ResearchConfig,
        mode: MailMode,
        existing_emails: set[str],
        existing_companies: set[str],
        sink: RecipientSink | None = None,
) -> list[Recipient]:
    """Fuehrt aus Ollama-Ausgabe web Recherche."""
    if sink is None:
        target_count = config.send_target_count if config.send_target_count > 0 else config.max_companies
        sink = ThreadSafeRecipientSink(target_count, existing_emails, existing_companies, config, mode)
    return _self_research.run_ollama_web_research(config, mode, existing_emails, existing_companies, sink=sink)


def self_search_queries(config: ResearchConfig, mode: MailMode) -> list[str]:
    """Fuehrt die Logik fuer self_search_queries aus."""
    return _self_research.self_search_queries(config, mode)


def crawl_self_result_url(*args, **kwargs):
    """Compatibility wrapper around the self research crawling logic."""
    return _self_research.crawl_self_result_url(*args, **kwargs)


def _extract_google_result_urls(*args, **kwargs):
    """Compatibility wrapper for testing."""
    return _self_research.extract_google_result_urls(*args, **kwargs)


def collect_self_search_result_urls(*args, **kwargs):
    """Compatibility wrapper for testing."""
    return _self_research.collect_self_search_result_urls(*args, **kwargs)


def _fetch_text(*args, **kwargs):
    """Compatibility wrapper for testing."""
    return _self_research.fetch_text(*args, **kwargs)


def normalize_company(company: str) -> str:
    """Normalizes company names."""
    return _parsing.normalize_company(company)


def list_resume_attachments(directory: Path, verbose: bool = False) -> list[Path]:
    """
    Lists all files in a directory that look like resumes (CV, Resume).
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


def _base_dir_from_mode(mode: MailMode) -> Path:
    """Returns the project base directory for a resolved mail mode."""
    return mode.recipients_dir.parent.parent


def _list_output_context_files(output_dir: Path) -> list[Path]:
    """Lists sent and invalid CSV logs that describe already known recipients."""
    if not output_dir.exists():
        return []
    return sorted(path for path in output_dir.glob("*.csv") if path.is_file())


def list_research_context_files(mode: MailMode, verbose: bool = False) -> list[Path]:
    """
    Collects files that should be provided to the AI as context.
    """
    context_files = list_resume_attachments(mode.attachments_dir, verbose)
    output_files = _list_output_context_files(_base_dir_from_mode(mode) / "output")
    context_files.extend(output_files)
    if output_files:
        _verbose(verbose, f"Known sent/invalid output context files queued for provider upload: {len(output_files)}.")
    elif not mode.log_path.exists():
        _verbose(verbose, f"Sent-log context file does not exist yet and will not be uploaded: {mode.log_path}")
    return context_files


def _needs_retry(raw_response: str, existing_emails: set[str], verbose: bool = False) -> bool:
    """
    Checks if the AI response was insufficient and if a retry makes sense.
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
    """Checks for model error."""
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
    Collects all already known email addresses from the output directory
    and all input files of all modes.
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
    for mode_name in get_available_mode_names(base_dir):
        mode = get_mode(mode_name, base_dir)
        recipient_files = list_recipient_files(mode.recipients_dir)
        for path in recipient_files:
            recipients = read_recipients(path)
            emails.update(recipient.email.lower() for recipient in recipients)
    return emails


def count_known_context_rows(base_dir: Path) -> dict[str, int]:
    """
    Counts known sent, invalid, and input recipient rows used as AI context.
    """
    output_dir = base_dir / "output"
    sent_count = 0
    invalid_count = 0
    for path in _list_output_context_files(output_dir):
        row_count = len(read_logged_rows(path))
        if path.name.lower() == "invalid_mails.csv":
            invalid_count += row_count
        else:
            sent_count += row_count

    input_count = 0
    for path in _list_all_input_context_files(base_dir):
        input_count += len(read_recipients(path))

    return {"sent": sent_count, "invalid": invalid_count, "input": input_count}


def collect_mode_existing_companies(mode: MailMode, verbose: bool = False) -> set[str]:
    """
    Collects already known company names from output logs and input files.
    """
    companies: set[str] = set()
    base_dir = _base_dir_from_mode(mode)
    for path in _list_output_context_files(base_dir / "output"):
        before = len(companies)
        companies.update(
            _normalize_company(row["company"])
            for row in read_logged_rows(path)
            if _normalize_company(row["company"])
        )
        _verbose(verbose, f"Loaded {len(companies) - before} logged company exclusion(s) from {path}.")

    for mode_name in get_available_mode_names(base_dir):
        input_mode = get_mode(mode_name, base_dir)
        recipient_files = list_recipient_files(input_mode.recipients_dir)
        for path in recipient_files:
            recipients = read_recipients(path)
            companies.update(
                _normalize_company(recipient.company)
                for recipient in recipients
                if _normalize_company(recipient.company)
            )
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


def _read_context_text(path: Path, verbose: bool = False) -> str:
    """Reads a context file with tolerant text decoding."""
    try:
        text = path.read_text(encoding="utf-8-sig")
        _verbose(verbose, f"Read context file with utf-8-sig: {path}.")
        return text
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
        _verbose(verbose, f"Read context file with replacement decoding: {path}.")
        return text


def _list_all_input_context_files(base_dir: Path) -> list[Path]:
    """Lists recipient CSV/TXT files from every configured mode."""
    files: list[Path] = []
    seen: set[Path] = set()
    for mode_name in get_available_mode_names(base_dir):
        mode = get_mode(mode_name, base_dir)
        for path in list_recipient_files(mode.recipients_dir):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(path)
    return sorted(files)


def read_known_exclusion_context(
        base_dir: Path,
        mode: MailMode,
        max_chars: int | None = None,
        verbose: bool = False,
) -> str:
    """
    Builds prompt-ready context from sent logs, invalid logs, and existing inputs.
    """
    context_files = _list_output_context_files(base_dir / "output") + _list_all_input_context_files(base_dir)
    parts = [
        "DIESE INHALTE WURDEN BEREITS GEFUNDEN; DIESE UNTERNEHMEN UND MAILS NICHT AUSSUCHEN.",
        f"Active mode: {mode.label}",
    ]
    for path in context_files:
        text = _read_context_text(path, verbose).strip()
        if text:
            parts.append(f"File: {path.relative_to(base_dir) if path.is_relative_to(base_dir) else path}\n{text}")
            _verbose(verbose, f"Added known exclusion context from {path}: {len(text)} characters.")

    if len(parts) == 2:
        return ""

    context = "\n\n".join(parts)
    if max_chars is not None and len(context) > max_chars:
        _verbose(verbose, f"Known exclusion context truncated from {len(context)} to {max_chars} characters.")
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
            writer.writerow([recipient.company, recipient.email, recipient.source_url])
    return path


def _model_for_provider(provider: str, gemini_model: str, openai_model: str, ollama_model: str = "llama3.1:8b") -> str:
    """
    Compatibility helper for old tests and CLI callers that still pass provider-specific models.
    """
    return _legacy_model_for_provider(provider, gemini_model, openai_model, ollama_model)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
