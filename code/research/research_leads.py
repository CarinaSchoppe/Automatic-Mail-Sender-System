"""AI lead research pipeline with provider calls, context uploads, and local filters."""

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
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from mail_sender.attachments import list_attachments
from mail_sender.email_validation import validate_email_address
from mail_sender.modes import MODE_NAMES, MailMode, get_mode
from mail_sender.recipients import COMPANY_KEYS as COMPANY_KEYS
from mail_sender.recipients import EMAIL_KEYS as EMAIL_KEYS
from mail_sender.recipients import Recipient
from mail_sender.recipients import list_recipient_files
from mail_sender.recipients import normalize_key as normalize_key
from mail_sender.recipients import read_recipients
from mail_sender.sent_log import read_logged_emails
from mail_sender.sent_log import read_logged_rows
from research import parsing as _parsing
from research import providers as _providers
from research import self_research as _self_research
from research.logging_utils import info as _info
from research.logging_utils import verbose as _verbose
from research.parsing import DefaultCsvDialect as DefaultCsvDialect
from research.parsing import _detect_dialect
from research.parsing import _find_field as _find_field
from research.parsing import _parse_json_recipients as _parse_json_recipients
from research.parsing import _strip_csv_fence as _strip_csv_fence
from research.parsing import _strip_json_fence as _strip_json_fence
from research.parsing import normalize_company as _normalize_company
from research.parsing import parse_recipients
from research.providers import _fake_txt_extensions as _fake_txt_extensions
from research.providers import _verbose_gemini_candidates as _verbose_gemini_candidates
from research.providers import _verbose_openai_output as _verbose_openai_output
from research.self_research import _company_from_page
from research.self_research import _extract_emails_from_text
from research.self_research import _extract_google_result_urls
from research.self_research import _extract_relevant_same_site_links
from research.self_research import _fetch_text
from research.self_research import _is_blocked_result_url
from research.self_research import _normalize_url_for_dedupe
from research.self_research import default_self_keywords as _default_self_keywords

mode_instructions = importlib.import_module(
    f"{__package__}.mode_instructions" if __package__ else "mode_instructions"
)

RESUME_ATTACHMENT_PATTERN = re.compile(
    r"(?:^|[\s._-])(cv|resume|lebenslauf|curriculum(?:[\s._-]+vitae)?)(?:$|[\s._-])",
    re.IGNORECASE,
)


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


def _load_settings() -> dict:
    settings_path = CODE_DIR.parent / "settings.toml"
    if not settings_path.exists():
        return {}
    try:
        with settings_path.open("rb") as handle:
            return tomllib.load(handle)
    except Exception:
        return {}


def default_config() -> ResearchConfig:
    load_dotenv()
    settings = _load_settings()

    def _get(key: str, default):
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

    provider = _get("RESEARCH_AI_PROVIDER", "gemini")
    gemini_model = _get("GEMINI_MODEL", "gemini-3-flash-preview")
    openai_model = _get("OPENAI_MODEL", "gpt-5.4-mini-2026-03-17")
    ollama_model = _get("OLLAMA_MODEL", "llama3.1:8b")
    ollama_base_url = _get("OLLAMA_BASE_URL", "http://localhost:11434")

    # Mode name: check RESEARCH_MODE (env) then MODE (env or toml)
    mode_name = os.getenv("RESEARCH_MODE")
    if mode_name is None:
        mode_name = _get("MODE", "PhD")

    return ResearchConfig(
        provider=provider,
        mode_name=mode_name,
        gemini_model=gemini_model,
        openai_model=openai_model,
        ollama_model=ollama_model,
        ollama_base_url=ollama_base_url,
        model=_model_for_provider(provider, gemini_model, openai_model, ollama_model),
        min_companies=_get("RESEARCH_MIN_COMPANIES", 15),
        max_companies=_get("RESEARCH_MAX_COMPANIES", 25),
        person_emails_per_company=_get("RESEARCH_PERSON_EMAILS_PER_COMPANY", 3),
        base_dir=_env_path("RESEARCH_BASE_DIR", CODE_DIR.parent),
        write_output=_get("RESEARCH_WRITE_OUTPUT", True),
        verbose=_get("RESEARCH_VERBOSE", False),
        upload_attachments=_get("RESEARCH_UPLOAD_ATTACHMENTS", True),
        reasoning_effort=_get("RESEARCH_REASONING_EFFORT", "middle"),
        send_target_count=_get("SEND_TARGET_COUNT", 0),
        max_iterations=_get("SEND_TARGET_MAX_ROUNDS", 5),
        parallel_threads=_get("PARALLEL_THREADS", 3),
        self_search_keywords=tuple(_get("SELF_SEARCH_KEYWORDS", _default_self_keywords(mode_name))),
        self_search_pages=_get("SELF_SEARCH_PAGES", 1),
        self_results_per_page=_get("SELF_RESULTS_PER_PAGE", 10),
        self_crawl_max_pages_per_site=_get("SELF_CRAWL_MAX_PAGES_PER_SITE", 8),
        self_crawl_depth=_get("SELF_CRAWL_DEPTH", 2),
        self_request_timeout=float(_get("SELF_REQUEST_TIMEOUT", 10.0)),
        self_verify_email_smtp=_get("SELF_VERIFY_EMAIL_SMTP", False),
    )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    config = parse_args(argv)
    try:
        output_path, recipients = run_research(config)
    except (RuntimeError, ValueError, FileNotFoundError, NotADirectoryError) as exc:
        print(f"Error: {exc}")
        return 1

    print(f"research mode: {config.mode_name}")
    print(f"New recipients: {len(recipients)}")
    print(f"Output CSV: {output_path if output_path else 'not written'}")
    return 0


def parse_args(argv: list[str]) -> ResearchConfig:
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
    """Run one AI research pass and return the optional CSV path plus usable recipients."""
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
        if max_iterations > 0 and iteration >= max_iterations:
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
        
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = {
                executor.submit(
                    _generate_research_response, 
                    config, mode, prompt, attachments, set(seen_emails_in_run), input_context, stop_event
                ): i 
                for i in range(batch_size)
            }
            
            for future in as_completed(futures):
                if stop_event.is_set():
                    continue
                    
                try:
                    raw_response = future.result()
                    if not raw_response:
                        continue
                        
                    _verbose(config.verbose, f"Raw AI response characters: {len(raw_response)}")
                    new_recipients = parse_recipients(raw_response, seen_emails_in_run, seen_companies_in_run, config.verbose)
                    
                    thread_added = 0
                    for r in new_recipients:
                        if len(all_recipients) >= target_count:
                            stop_event.set()
                            break
                        all_recipients.append(r)
                        seen_emails_in_run.add(r.email.lower())
                        seen_companies_in_run.add(_normalize_company(r.company))
                        thread_added += 1
                        batch_new_count += 1
                    
                    if thread_added > 0:
                        _info(f"Added {thread_added} new recipients from AI response. Total: {len(all_recipients)}/{target_count}.")
                    
                    if len(all_recipients) >= target_count:
                        _info(f"Target of {target_count} reached. Stopping batch.")
                        stop_event.set()
                except Exception as e:
                    _info(f"AI request failed in thread: {e}")

        _info(f"New recipients found in this batch: {batch_new_count}.")

        if batch_new_count == 0:
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


def _generate_research_response(
        config: ResearchConfig,
        mode: MailMode,
        prompt: str,
        attachments: list[Path],
        existing_emails: set[str],
        input_context: str,
        stop_event: threading.Event | None = None,
) -> str:
    if stop_event and stop_event.is_set():
        return ""

    raw_response = generate_with_provider(
        config.provider, config.model, prompt, attachments, config.reasoning_effort, config.verbose, config.ollama_base_url
    )
    if stop_event and stop_event.is_set():
        return raw_response

    if _needs_retry(raw_response, existing_emails, config.verbose) and attachments:
        _info("AI response was not usable yet; retrying once without CV/resume uploads.")
        _verbose(config.verbose, "AI provider returned no usable CSV with attachment uploads; retrying once without attachment uploads.")
        if stop_event and stop_event.is_set():
            return raw_response

        raw_response = generate_with_provider(
            config.provider, config.model, prompt, [], config.reasoning_effort, config.verbose, config.ollama_base_url
        )
    if stop_event and stop_event.is_set():
        return raw_response

    if _needs_retry(raw_response, existing_emails, config.verbose):
        retry_prompt = build_prompt(config, mode, set(), set(), input_context)
        _info("AI response still was not usable; retrying once with a smaller exclusion prompt.")
        _verbose(config.verbose, "AI provider still returned no usable CSV; retrying once with a smaller prompt and local post-filtering.")
        _verbose(config.verbose, f"Lite AI prompt characters: {len(retry_prompt)}")
        if stop_event and stop_event.is_set():
            return raw_response

        raw_response = generate_with_provider(
            config.provider, config.model, retry_prompt, [], config.reasoning_effort, config.verbose, config.ollama_base_url
        )
    return raw_response


def run_self_research(
        config: ResearchConfig,
        mode: MailMode,
        existing_emails: set[str],
        existing_companies: set[str],
) -> list[Recipient]:
    """Compatibility wrapper around the self research base workflow."""
    target_count = config.send_target_count if config.send_target_count > 0 else config.max_companies
    seen_emails = {email.lower() for email in existing_emails}
    seen_companies = {company for company in existing_companies if company}
    recipients: list[Recipient] = []

    queries = _self_search_queries(config, mode)
    result_urls = collect_self_search_result_urls(config, queries)
    if not result_urls:
        raise RuntimeError("Self research found no search result URLs.")

    _info(f"Starting self-research crawl on {len(result_urls)} site(s) with target={target_count}.")
    stop_event = threading.Event()
    with ThreadPoolExecutor(max_workers=min(config.parallel_threads, len(result_urls))) as executor:
        futures = {executor.submit(crawl_self_result_url, config, url, stop_event): url for url in result_urls}
        for future in as_completed(futures):
            if len(recipients) >= target_count:
                stop_event.set()
                break

            try:
                candidates = future.result()
            except Exception as exc:
                _verbose(config.verbose, f"Self research crawl failed for {futures[future]}: {exc}")
                continue

            thread_added = 0
            for candidate in candidates:
                if len(recipients) >= target_count:
                    break
                email_key = candidate.email.lower()
                company_key = _normalize_company(candidate.company)
                if email_key in seen_emails or (company_key and company_key in seen_companies):
                    continue
                validation = validate_email_address(
                    candidate.email,
                    verify_mailbox=config.self_verify_email_smtp,
                    smtp_timeout=config.self_request_timeout,
                )
                if not validation.is_valid:
                    _verbose(config.verbose, f"Self candidate skipped by validation: {candidate.email} | {validation.reason}")
                    continue
                recipients.append(candidate)
                seen_emails.add(email_key)
                if company_key:
                    seen_companies.add(company_key)
                thread_added += 1

            if thread_added > 0:
                _info(f"Self-research found {thread_added} new recipients. Progress: {len(recipients)}/{target_count}.")

            if len(recipients) >= target_count:
                _info(f"Self-research target of {target_count} reached.")
                break

    if not recipients:
        raise RuntimeError("Self research found no new usable email addresses.")
    return recipients


def run_ollama_web_research(
        config: ResearchConfig,
        mode: MailMode,
        existing_emails: set[str],
        existing_companies: set[str],
) -> list[Recipient]:
    candidates = run_self_research(config, mode, existing_emails, existing_companies)
    target_count = config.send_target_count or config.max_companies
    if len(candidates) >= target_count:
        _info(f"Ollama web research: target reached via crawl ({len(candidates)} candidates). Skipping AI filtering.")
        return candidates[:target_count]

    _info(f"Ollama web research: filtering {len(candidates)} candidates via AI model {config.model}.")
    prompt = _self_research.build_ollama_web_research_prompt(config, mode, _self_research._recipients_to_csv_text(candidates))
    raw_response = generate_with_ollama(config.model, prompt, config.ollama_base_url, config.verbose)
    recipients = parse_recipients(raw_response, existing_emails, existing_companies, config.verbose)

    final_recipients = recipients if recipients else candidates
    _info(f"Ollama web research finished. Found {len(final_recipients)} usable recipients.")
    return final_recipients[:target_count]


def collect_self_search_result_urls(config: ResearchConfig, queries: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for query in queries:
        for page in range(config.self_search_pages):
            start = page * config.self_results_per_page
            search_url = _self_research._google_search_url(query, start)
            html_text = _fetch_text(search_url, config.self_request_timeout, config.verbose)
            if not html_text:
                continue
            for result_url in _extract_google_result_urls(html_text):
                normalized = _normalize_url_for_dedupe(result_url)
                if normalized in seen or _is_blocked_result_url(result_url):
                    continue
                seen.add(normalized)
                urls.append(result_url)
    return urls


def crawl_self_result_url(config: ResearchConfig, start_url: str, stop_event: threading.Event | None = None) -> list[Recipient]:
    to_visit = [(start_url, 0)]
    visited: set[str] = set()
    candidates: list[Recipient] = []
    base_netloc = urllib.parse.urlparse(start_url).netloc.lower().removeprefix("www.")

    while to_visit and len(visited) < config.self_crawl_max_pages_per_site:
        if stop_event and stop_event.is_set():
            break
        url, depth = to_visit.pop(0)
        normalized = _normalize_url_for_dedupe(url)
        if normalized in visited:
            continue
        visited.add(normalized)
        page_text = _fetch_text(url, config.self_request_timeout, config.verbose)
        if not page_text:
            continue
        company = _company_from_page(url, page_text)
        for email in _extract_emails_from_text(page_text):
            candidates.append(Recipient(email=email, company=company))
        if depth >= config.self_crawl_depth:
            continue
        queued_urls = {queued_url for queued_url, _ in to_visit}
        for link in _extract_relevant_same_site_links(url, page_text, base_netloc):
            if _normalize_url_for_dedupe(link) not in visited and link not in queued_urls:
                to_visit.append((link, depth + 1))
    return candidates


def _self_search_queries(config: ResearchConfig, mode: MailMode) -> list[str]:
    keywords = [keyword.strip() for keyword in config.self_search_keywords if keyword.strip()]
    return keywords or list(_default_self_keywords(mode.label))


def list_resume_attachments(directory: Path, verbose: bool = False) -> list[Path]:
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
    """Return the files safe to upload as research context for the selected mode."""
    context_files = list_resume_attachments(mode.attachments_dir, verbose)
    if mode.log_path.exists():
        context_files.append(mode.log_path)
        _verbose(verbose, f"Sent-log context queued for provider upload: {mode.log_path}")
    else:
        _verbose(verbose, f"Sent-log context file does not exist yet and will not be uploaded: {mode.log_path}")
    return context_files


def _needs_retry(raw_response: str, existing_emails: set[str], verbose: bool = False) -> bool:
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
    emails: set[str] = set()
    output_dir = base_dir / "output"
    
    # Load all emails from output logs (excluding invalid_mails.csv)
    from mail_sender.sent_log import read_known_output_emails
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
        _verbose(verbose, f"Found {len(recipient_files)} existing input file(s) for exclusion scan in {mode.recipients_dir}.")
        for path in recipient_files:
            recipients = read_recipients(path)
            emails.update(recipient.email.lower() for recipient in recipients)
            _verbose(verbose, f"Loaded {len(recipients)} existing recipient email exclusion(s) from {path}.")
    return emails


def collect_mode_existing_companies(mode: MailMode, verbose: bool = False) -> set[str]:
    """Collect normalized company names already present in this mode's logs and inputs."""
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


def read_input_context(directory: Path, max_chars: int = 6000, verbose: bool = False) -> str:
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
    """Build the provider prompt using the Overseer template."""
    from research import mode_instructions

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


def generate_with_provider(
        provider: str,
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
        ollama_base_url: str | None = None,
) -> str:
    normalized = provider.strip().lower()
    if normalized == "gemini":
        return generate_with_gemini(model, prompt, attachment_paths, reasoning_effort, verbose)
    if normalized == "openai":
        return generate_with_openai(model, prompt, attachment_paths, reasoning_effort, verbose)
    if normalized == "ollama":
        return generate_with_ollama(model, prompt, ollama_base_url or "http://localhost:11434", verbose)
    raise ValueError("Unknown research provider. Use gemini, openai, ollama, or self.")


def generate_with_gemini(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str:
    _providers.load_dotenv = load_dotenv
    return _providers.generate_with_gemini(model, prompt, attachment_paths, reasoning_effort, verbose)


def generate_with_openai(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str:
    _providers.load_dotenv = load_dotenv
    return _providers.generate_with_openai(model, prompt, attachment_paths, reasoning_effort, verbose)


def generate_with_ollama(
        model: str,
        prompt: str,
        base_url: str = "http://localhost:11434",
        verbose: bool = False,
) -> str:
    return _providers.generate_with_ollama(model, prompt, base_url, verbose)


def _parse_headerless_csv_recipients(
        raw_text: str,
        existing_emails: set[str],
        existing_companies: set[str] | None = None,
        verbose: bool = False,
) -> list[Recipient]:
    original = _parsing._detect_dialect
    _parsing._detect_dialect = _detect_dialect
    try:
        return _parsing._parse_headerless_csv_recipients(raw_text, existing_emails, existing_companies, verbose)
    finally:
        _parsing._detect_dialect = original


def write_recipients_csv(directory: Path, mode_label: str, recipients: list[Recipient]) -> Path:
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


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default.resolve()
    return Path(value).resolve()


def _model_for_provider(provider: str, gemini_model: str, openai_model: str, ollama_model: str = "llama3.1:8b") -> str:
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


