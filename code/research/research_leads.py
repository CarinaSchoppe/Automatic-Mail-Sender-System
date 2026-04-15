"""AI lead research pipeline with provider calls, context uploads, and local filters."""

# Local imports intentionally come after the direct-script path bootstrap below.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import contextlib
import csv
import html
import importlib
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
import urllib.error
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
from mail_sender.modes import MODE_NAMES, MailMode, get_mode
from mail_sender.recipients import COMPANY_KEYS
from mail_sender.recipients import EMAIL_KEYS
from mail_sender.recipients import Recipient
from mail_sender.recipients import list_recipient_files
from mail_sender.recipients import normalize_email
from mail_sender.recipients import normalize_key
from mail_sender.recipients import read_recipients
from mail_sender.email_validation import validate_email_address
from mail_sender.sent_log import read_logged_emails
from mail_sender.sent_log import read_logged_rows

mode_instructions = importlib.import_module(
    f"{__package__}.mode_instructions" if __package__ else "mode_instructions"
)

SOURCE_KEYS = {"source", "source-url", "sourceurl", "url", "website"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_EXTRACT_PATTERN = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
COMPANY_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")
HTML_TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
HTML_LINK_PATTERN = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
BAD_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf")
CONTACT_LINK_HINTS = ("contact", "about", "team", "people", "staff", "career", "impressum")
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MailSenderSystemResearch/1.0; +https://example.local)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
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
    reasoning_effort: str = "middle"
    send_target_count: int = 0
    max_iterations: int = 5
    parallel_threads: int = 1
    self_search_keywords: tuple[str, ...] = ()
    self_search_pages: int = 1
    self_results_per_page: int = 10
    self_crawl_max_pages_per_site: int = 8
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

    # Mode name: check RESEARCH_MODE (env) then MODE (env or toml)
    mode_name = os.getenv("RESEARCH_MODE")
    if mode_name is None:
        mode_name = _get("MODE", "PhD")

    return ResearchConfig(
        provider=provider,
        mode_name=mode_name,
        gemini_model=gemini_model,
        openai_model=openai_model,
        model=_model_for_provider(provider, gemini_model, openai_model),
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
        parallel_threads=_get("PARALLEL_THREADS", 5),
        self_search_keywords=tuple(_get("SELF_SEARCH_KEYWORDS", _default_self_keywords(mode_name))),
        self_search_pages=_get("SELF_SEARCH_PAGES", 1),
        self_results_per_page=_get("SELF_RESULTS_PER_PAGE", 10),
        self_crawl_max_pages_per_site=_get("SELF_CRAWL_MAX_PAGES_PER_SITE", 8),
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
    parser.add_argument("--provider", default=env_config.provider, choices=["gemini", "openai", "self"], help="Research provider.")
    parser.add_argument("--mode", default=env_config.mode_name, choices=MODE_NAMES, help="research mode.")
    parser.add_argument("--gemini-model", default=env_config.gemini_model)
    parser.add_argument("--openai-model", default=env_config.openai_model)
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
        model=_model_for_provider(args.provider, args.gemini_model, args.openai_model),
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

    _info(
        f"Starting AI research: mode={config.mode_name}, provider={config.provider}, "
        f"model={config.model}, reasoning={config.reasoning_effort}, target={config.min_companies}-{config.max_companies} companies."
    )
    _verbose(config.verbose, f"Base directory: {config.base_dir}")
    _verbose(config.verbose, f"AI provider: {config.provider}")
    _verbose(config.verbose, f"research mode setting: {config.mode_name}")
    _verbose(config.verbose, f"AI model: {config.model}")
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

        remaining_iterations = max_iterations - iteration if max_iterations > 0 else config.parallel_threads
        batch_size = max(1, min(config.parallel_threads, remaining_iterations))
        batch_start = iteration + 1
        iteration += batch_size
        if batch_start > 1:
            _info(f"Research batch starting at iteration {batch_start}: {len(all_recipients)}/{target_count} recipients found so far.")

        _info(f"Building {batch_size} AI research prompt(s).")
        prompt = build_prompt(config, mode, seen_emails_in_run, seen_companies_in_run, input_context)
        _verbose(config.verbose, f"AI prompt characters: {len(prompt)}")

        _info(f"Calling AI provider with {batch_size} parallel request(s); this can take a moment.")
        raw_responses = _generate_research_batch(config, mode, prompt, attachments, seen_emails_in_run, input_context, batch_size)

        _info("Parsing and filtering AI response batch.")
        batch_new_recipients = 0
        for raw_response in raw_responses:
            _verbose(config.verbose, f"Raw AI response characters: {len(raw_response)}")
            new_recipients = parse_recipients(raw_response, seen_emails_in_run, seen_companies_in_run, config.verbose)
            batch_new_recipients += len(new_recipients)
            for r in new_recipients:
                if len(all_recipients) >= target_count:
                    break
                all_recipients.append(r)
                seen_emails_in_run.add(r.email.lower())
                seen_companies_in_run.add(_normalize_company(r.company))

        _info(f"Usable new recipients found in this batch: {batch_new_recipients}.")

        if batch_new_recipients == 0:
            _info("No more new recipients found in this batch.")
            if batch_start == 1:
                raise RuntimeError("Gemini returned no new usable email addresses on the first attempt.")
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


def _generate_research_batch(
        config: ResearchConfig,
        mode: MailMode,
        prompt: str,
        attachments: list[Path],
        existing_emails: set[str],
        input_context: str,
        batch_size: int,
) -> list[str]:
    if batch_size == 1:
        return [_generate_research_response(config, mode, prompt, attachments, existing_emails, input_context)]

    responses: list[str] = [""] * batch_size
    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        futures = {
            executor.submit(_generate_research_response, config, mode, prompt, attachments, set(existing_emails), input_context): index
            for index in range(batch_size)
        }
        for future in as_completed(futures):
            responses[futures[future]] = future.result()
    return responses


def _generate_research_response(
        config: ResearchConfig,
        mode: MailMode,
        prompt: str,
        attachments: list[Path],
        existing_emails: set[str],
        input_context: str,
) -> str:
    raw_response = generate_with_provider(
        config.provider, config.model, prompt, attachments, config.reasoning_effort, config.verbose
    )
    if _needs_retry(raw_response, existing_emails, config.verbose) and attachments:
        _info("AI response was not usable yet; retrying once without CV/resume uploads.")
        _verbose(config.verbose, "AI provider returned no usable CSV with attachment uploads; retrying once without attachment uploads.")
        raw_response = generate_with_provider(
            config.provider, config.model, prompt, [], config.reasoning_effort, config.verbose
        )
    if _needs_retry(raw_response, existing_emails, config.verbose):
        retry_prompt = build_prompt(config, mode, set(), set(), input_context)
        _info("AI response still was not usable; retrying once with a smaller exclusion prompt.")
        _verbose(config.verbose, "AI provider still returned no usable CSV; retrying once with a smaller prompt and local post-filtering.")
        _verbose(config.verbose, f"Lite AI prompt characters: {len(retry_prompt)}")
        raw_response = generate_with_provider(
            config.provider, config.model, retry_prompt, [], config.reasoning_effort, config.verbose
        )
    return raw_response


def run_self_research(
        config: ResearchConfig,
        mode: MailMode,
        existing_emails: set[str],
        existing_companies: set[str],
) -> list[Recipient]:
    """Run local web-search/crawl research and return centrally deduplicated recipients."""
    target_count = config.send_target_count if config.send_target_count > 0 else config.max_companies
    seen_emails = {email.lower() for email in existing_emails}
    seen_companies = {company for company in existing_companies if company}
    recipients: list[Recipient] = []

    queries = _self_search_queries(config, mode)
    _info(
        f"Starting self research with {len(queries)} keyword(s), "
        f"{config.self_search_pages} search page(s), {config.parallel_threads} worker(s)."
    )
    result_urls = collect_self_search_result_urls(config, queries)
    _info(f"Self research search result URLs found: {len(result_urls)}.")

    if not result_urls:
        raise RuntimeError("Self research found no search result URLs.")

    with ThreadPoolExecutor(max_workers=min(config.parallel_threads, len(result_urls))) as executor:
        futures = {
            executor.submit(crawl_self_result_url, config, url): url
            for url in result_urls
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                candidates = future.result()
            except Exception as exc:
                _verbose(config.verbose, f"Self research crawl failed for {url}: {exc}")
                continue

            for candidate in candidates:
                if len(recipients) >= target_count:
                    break
                email_key = candidate.email.lower()
                company_key = _normalize_company(candidate.company)
                if email_key in seen_emails:
                    _verbose(config.verbose, f"Self candidate skipped because email already exists: {candidate.email}")
                    continue
                if company_key and company_key in seen_companies:
                    _verbose(config.verbose, f"Self candidate skipped because company already exists: {candidate.company}")
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
                _verbose(config.verbose, f"Self candidate accepted: {candidate.company} <{candidate.email}>")

            if len(recipients) >= target_count:
                break

    if not recipients:
        raise RuntimeError("Self research found no new usable email addresses.")

    _info(f"Self research usable recipients found: {len(recipients)}.")
    return recipients


def collect_self_search_result_urls(config: ResearchConfig, queries: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for query in queries:
        for page in range(config.self_search_pages):
            start = page * config.self_results_per_page
            search_url = _google_search_url(query, start)
            _verbose(config.verbose, f"Self research search page: {search_url}")
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


def crawl_self_result_url(config: ResearchConfig, start_url: str) -> list[Recipient]:
    to_visit = [start_url]
    visited: set[str] = set()
    same_site_limit = config.self_crawl_max_pages_per_site
    candidates: list[Recipient] = []
    base_netloc = urllib.parse.urlparse(start_url).netloc.lower().removeprefix("www.")

    while to_visit and len(visited) < same_site_limit:
        url = to_visit.pop(0)
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

        for link in _extract_relevant_same_site_links(url, page_text, base_netloc):
            if _normalize_url_for_dedupe(link) not in visited and link not in to_visit:
                to_visit.append(link)

    return candidates


def _self_search_queries(config: ResearchConfig, mode: MailMode) -> list[str]:
    keywords = [keyword.strip() for keyword in config.self_search_keywords if keyword.strip()]
    if not keywords:
        keywords = list(_default_self_keywords(mode.label))
    return keywords


def _default_self_keywords(mode_name: str) -> tuple[str, ...]:
    normalized = mode_name.strip().lower()
    if normalized == "phd":
        return (
            '"industry phd" "contact" email Australia',
            '"research partnership" "contact" email Australia',
            '"innovation" "university partnership" email Australia',
        )
    if normalized == "freelance_english":
        return (
            '"freelance lecturer" "contact" email',
            '"online trainer" "contact" email',
            '"AI trainer" "contact" email',
        )
    return (
        '"AVGS" "Dozent" email',
        '"Weiterbildung" "Dozent" email',
        '"Bildungsträger" "Kontakt" email',
    )


def _google_search_url(query: str, start: int) -> str:
    params = urllib.parse.urlencode({"q": query, "num": "10", "start": str(start), "hl": "en"})
    return f"https://www.google.com/search?{params}"


def _fetch_text(url: str, timeout: float, verbose: bool) -> str:
    try:
        request = urllib.request.Request(url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type and content_type:
                _verbose(verbose, f"Skipping non-text response from {url}: {content_type}")
                return ""
            raw = response.read(1_500_000)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _verbose(verbose, f"Fetch failed for {url}: {exc}")
        return ""

    return raw.decode("utf-8", errors="replace")


def _extract_google_result_urls(html_text: str) -> list[str]:
    urls: list[str] = []
    for href in HTML_LINK_PATTERN.findall(html_text):
        decoded = html.unescape(href)
        if decoded.startswith("/url?"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(decoded).query)
            target = query.get("q", [""])[0]
        elif decoded.startswith("http"):
            target = decoded
        else:
            continue
        if target.startswith("http"):
            urls.append(target)
    return urls


def _extract_relevant_same_site_links(current_url: str, html_text: str, base_netloc: str) -> list[str]:
    links: list[str] = []
    for href in HTML_LINK_PATTERN.findall(html_text):
        target = urllib.parse.urljoin(current_url, html.unescape(href))
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower().removeprefix("www.") != base_netloc:
            continue
        path = parsed.path.lower()
        if any(hint in path for hint in CONTACT_LINK_HINTS):
            links.append(target)
    return links


def _extract_emails_from_text(text: str) -> list[str]:
    emails = []
    seen = set()
    cleaned_text = html.unescape(text).replace("[at]", "@").replace("(at)", "@").replace(" at ", "@")
    for match in EMAIL_EXTRACT_PATTERN.findall(cleaned_text):
        email = normalize_email(match).strip(".,;:()[]<>").lower()
        if email.endswith(BAD_EMAIL_SUFFIXES) or email in seen:
            continue
        seen.add(email)
        emails.append(email)
    return emails


def _company_from_page(url: str, page_text: str) -> str:
    title_match = HTML_TITLE_PATTERN.search(page_text)
    if title_match:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(title_match.group(1)))).strip()
        if title:
            return title[:120]
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.lower().removeprefix("www.")


def _normalize_url_for_dedupe(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        "",
        parsed.query,
        "",
    ))


def _is_blocked_result_url(url: str) -> bool:
    netloc = urllib.parse.urlparse(url).netloc.lower()
    blocked = ("google.", "youtube.", "facebook.", "instagram.", "linkedin.", "twitter.", "x.com")
    return any(domain in netloc for domain in blocked)


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
    from mail_sender.sent_log import read_known_output_emails, read_logged_emails
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


def _normalize_company(company: str) -> str:
    return COMPANY_NORMALIZE_PATTERN.sub("", company.strip().lower())


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
    """Build the provider prompt while preserving compatibility with older call sites."""
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

    return f"""
    You are a careful B2B lead researcher.

    Use medium-to-high reasoning for the research. Use web search, the mode-specific input context,
    any uploaded attachment context if provided, and any available tools you need. Use tools automatically
    whenever they help verify public source URLs or email addresses.

    Mode: {mode.label}

    Task:
    {mode_instructions.instructions[mode.label]}

    Requirements:
    - Find leads from {config.min_companies} to {config.max_companies} relevant companies.
    - Do not include any email address already listed in the exclusion list.
    - Do not search for or return a company if the company name or email address already appears in the mode-specific sent CSV list, uploaded sent-log file, or exclusions.
    - Use the mode-specific input CSV/TXT context only as background for fit and targeting.
    - Prefer official company websites and publicly visible work email addresses.
    - Only include an email address if it is explicitly shown on a public webpage.
    - Do not invent, infer, guess, or pattern-generate email addresses.
    - Do not include contact forms without an email address.
    - Do not include placeholder or assumed addresses unless that exact address is publicly shown.
    {contact_requirement}
    - Include the exact public source URL where the email was found.
    - If you cannot verify enough emails, return fewer rows instead of guessing.

    Output format:
    - Return valid CSV only.
    - CSV header must be exactly:
      company,mail,source_url
    - Use one row per email address.
    - If multiple emails are found for one company, repeat the company name on separate rows.
    - If no results are found, return only the header.
    - Do not return markdown, explanations, JSON, or Python lists.

    Existing email exclusion list:
    {excluded}

    Existing company exclusion list for this mode:
    {excluded_companies}

    Mode-specific input CSV/TXT context:
    {input_reference}
    """.strip()


def generate_with_provider(
        provider: str,
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str:
    normalized = provider.strip().lower()
    if normalized == "gemini":
        return generate_with_gemini(model, prompt, attachment_paths, reasoning_effort, verbose)
    if normalized == "openai":
        return generate_with_openai(model, prompt, attachment_paths, reasoning_effort, verbose)
    raise ValueError("Unknown research provider. Use gemini, openai, or self.")


def generate_with_gemini(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY before running research.")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - depends on optional local package state
        raise RuntimeError("Install google-genai first: pip install -r requirements.txt") from exc

    client = genai.Client(api_key=api_key)
    _verbose(verbose, f"Uploading {len(attachment_paths)} attachment context file(s) to Gemini.")
    uploaded_files = []
    with _fake_txt_extensions(attachment_paths, verbose) as faked_paths:
        for path in faked_paths:
            _verbose(verbose, f"Uploading Gemini context file: {path}.")
            uploaded_files.append(client.files.upload(file=path))
    _verbose(verbose, f"Gemini uploaded file handles: {len(uploaded_files)}.")

    # Map reasoning effort to Gemini thinking level
    thinking_level = types.ThinkingLevel.MEDIUM
    if reasoning_effort == "low":
        thinking_level = types.ThinkingLevel.BRIEF
    elif reasoning_effort == "high":
        thinking_level = types.ThinkingLevel.FULL

    _verbose(verbose, "Calling Gemini with Google Search grounding enabled.")
    _verbose(
        verbose,
        f"Gemini config: google_search enabled, tool auto mode enabled, "
        f"thinking_level={thinking_level.name}, temperature=0.3."
    )
    response = client.models.generate_content(
        model=model,
        contents=[prompt, *uploaded_files],  # type: ignore[arg-type]
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.AUTO,
                ),
                include_server_side_tool_invocations=True,
            ),
            thinking_config=types.ThinkingConfig(
                thinking_level=thinking_level,
            ),
            temperature=0.3,
        ),
    )
    _verbose(verbose, "Gemini response received.")
    response_text = _extract_response_text(response)
    _verbose(verbose, f"Gemini response.text raw: {response_text!r}")
    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        _verbose(verbose, f"Gemini prompt_feedback: {prompt_feedback!r}")
    _verbose_gemini_candidates(verbose, response)
    return response_text


def generate_with_openai(
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        reasoning_effort: str = "middle",
        verbose: bool = False,
) -> str:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY before running OpenAI research.")

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - depends on optional local package state
        raise RuntimeError("Install openai first: pip install -r requirements.txt") from exc

    client = OpenAI(api_key=api_key)
    _verbose(verbose, f"Uploading {len(attachment_paths)} attachment context file(s) to OpenAI.")
    uploaded_files = []
    with _fake_txt_extensions(attachment_paths, verbose) as faked_paths:
        for path in faked_paths:
            _verbose(verbose, f"Uploading OpenAI context file: {path}.")
            with path.open("rb") as handle:
                uploaded_files.append(client.files.create(file=handle, purpose="user_data"))
    _verbose(verbose, f"OpenAI uploaded file handles: {len(uploaded_files)}.")

    content = [{"type": "input_text", "text": prompt}]
    content.extend({"type": "input_file", "file_id": uploaded_file.id} for uploaded_file in uploaded_files)

    # Map reasoning effort to OpenAI reasoning effort
    openai_effort = "medium"
    if reasoning_effort == "low":
        openai_effort = "low"
    elif reasoning_effort == "high":
        openai_effort = "high"

    _verbose(verbose, "Calling OpenAI Responses API with web_search enabled.")
    _verbose(verbose, f"OpenAI config: web_search enabled, tool_choice=auto, reasoning_effort={openai_effort}.")
    response = client.responses.create(  # type: ignore[call-overload]
        model=model,
        input=[
            {
                "role": "user",
                "content": content,
            }
        ],
        tools=[{"type": "web_search"}],
        tool_choice="auto",
        reasoning={
            "effort": openai_effort
        },
    )
    _verbose(verbose, "OpenAI response received.")
    response_text = _extract_openai_response_text(response)
    _verbose(verbose, f"OpenAI response output_text raw: {response_text!r}")
    _verbose_openai_output(verbose, response)
    return response_text


@contextlib.contextmanager
def _fake_txt_extensions(attachment_paths: list[Path], verbose: bool = False):
    """Temporary copy .csv files to .txt for upload to avoid MIME type issues."""
    temp_files: list[Path] = []
    new_paths: list[Path] = []
    try:
        for path in attachment_paths:
            if path.suffix.lower() == ".csv":
                temp_dir = Path(tempfile.gettempdir())
                # Copy with .txt extension to the system's temp directory
                fake_path = temp_dir / (path.name + ".txt")
                _verbose(verbose, f"Faking extension for AI upload: {path.name} -> {fake_path.name}")
                shutil.copy2(path, fake_path)
                temp_files.append(fake_path)
                new_paths.append(fake_path)
            else:
                new_paths.append(path)
        yield new_paths
    finally:
        for temp_file in temp_files:
            try:
                temp_file.unlink(missing_ok=True)
            except Exception:  # pragma: no cover
                pass


def _extract_openai_response_text(response) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    texts: list[str] = []
    for output_item in getattr(response, "output", None) or []:
        for content_item in getattr(output_item, "content", None) or []:
            text = getattr(content_item, "text", None)
            if text:
                texts.append(text)
    return "\n".join(texts)


def _verbose_openai_output(verbose: bool, response) -> None:
    if not verbose:
        return
    output_items = getattr(response, "output", None) or []
    if not output_items:
        _verbose(verbose, "OpenAI output items: none")
        return

    _verbose(verbose, f"OpenAI output items: {len(output_items)}")
    for index, output_item in enumerate(output_items, start=1):
        item_type = getattr(output_item, "type", None)
        status = getattr(output_item, "status", None)
        _verbose(verbose, f"OpenAI output item {index} type: {item_type!r}")
        _verbose(verbose, f"OpenAI output item {index} status: {status!r}")


def _extract_response_text(response) -> str:
    direct_text = getattr(response, "text", None)
    if direct_text:
        return direct_text

    texts: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                texts.append(part_text)
    return "\n".join(texts)


def _verbose(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[VERBOSE] {message}")


def _info(message: str) -> None:
    print(f"[INFO] {message}")


def _verbose_gemini_candidates(verbose: bool, response) -> None:
    if not verbose:
        return

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        _verbose(verbose, "Gemini candidates: none")
        return

    _verbose(verbose, f"Gemini candidates: {len(candidates)}")
    for index, candidate in enumerate(candidates, start=1):
        finish_reason = getattr(candidate, "finish_reason", None)
        safety_ratings = getattr(candidate, "safety_ratings", None)
        _verbose(verbose, f"Gemini candidate {index} finish_reason: {finish_reason!r}")
        _verbose(verbose, f"Gemini candidate {index} safety_ratings: {safety_ratings!r}")
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if parts:
            for part_index, part in enumerate(parts, start=1):
                part_text = getattr(part, "text", None)
                _verbose(verbose, f"Gemini candidate {index} part {part_index} text: {part_text!r}")
        else:
            _verbose(verbose, f"Gemini candidate {index} content parts: none")


def parse_recipients(
        raw_response: str,
        existing_emails: set[str],
        existing_companies: set[str] | None = None,
        verbose: bool = False,
) -> list[Recipient]:
    """Parse AI output into recipients and apply local email/company exclusion filters."""
    if isinstance(existing_companies, bool):
        verbose = existing_companies
        existing_companies = None
    _verbose(verbose, f"Parsing AI response with {len(raw_response)} character(s).")
    csv_text = _strip_csv_fence(raw_response)
    _verbose(verbose, f"CSV candidate text length after fence stripping: {len(csv_text)}.")
    rows = list(csv.DictReader(csv_text.splitlines(), dialect=_detect_dialect(csv_text))) if csv_text.strip() else []
    _verbose(verbose, f"CSV DictReader row count: {len(rows)}.")
    if rows:
        company_field = _find_field(rows[0], COMPANY_KEYS)
        email_field = _find_field(rows[0], EMAIL_KEYS)
        _verbose(verbose, f"Detected CSV fields: company={company_field!r}, email={email_field!r}.")
        if company_field and email_field:
            source_field = _find_field(rows[0], SOURCE_KEYS)
            _verbose(verbose, f"Detected CSV source field: {source_field!r}.")
            recipients = _extract_from_rows(rows, company_field, email_field, existing_emails, existing_companies, source_field, verbose)
            _verbose(verbose, f"Parsed CSV recipients: {len(recipients)}")
            return recipients

    recipients = _parse_headerless_csv_recipients(csv_text, existing_emails, existing_companies, verbose)
    if recipients:
        _verbose(verbose, f"Parsed headerless CSV recipients: {len(recipients)}")
        return recipients

    recipients = _parse_json_recipients(raw_response, existing_emails, existing_companies, verbose)
    if recipients:
        _verbose(verbose, f"Parsed JSON recipients: {len(recipients)}")
        return recipients

    _verbose(verbose, "No recipients could be parsed from AI response.")
    return []


def _parse_headerless_csv_recipients(
        raw_text: str,
        existing_emails: set[str],
        existing_companies: set[str] | None = None,
        verbose: bool = False,
) -> list[Recipient]:
    if isinstance(existing_companies, bool):
        verbose = existing_companies
        existing_companies = None
    text = raw_text.strip().strip("'\"`").replace("\\n", "\n")
    if not text:
        _verbose(verbose, "Headerless CSV parser skipped empty text.")
        return []

    try:
        rows = list(csv.reader(text.splitlines(), dialect=_detect_dialect(text)))
    except csv.Error:
        _verbose(verbose, "Headerless CSV parser failed to read CSV rows.")
        return []

    _verbose(verbose, f"Headerless CSV row count: {len(rows)}.")
    parsed_rows: list[dict[str, str]] = []
    for row in rows:
        cells = [cell.strip().strip("'\"`") for cell in row if cell.strip()]
        if len(cells) < 2:
            _verbose(verbose, f"Headerless CSV row skipped because it has fewer than 2 cells: {row!r}.")
            continue
        email = cells[-1]
        company = ", ".join(cells[:-1]).strip()
        parsed_rows.append({"company": company, "mail": email})

    return _extract_from_rows(parsed_rows, "company", "mail", existing_emails, existing_companies, verbose=verbose)


def _parse_json_recipients(
        raw_response: str,
        existing_emails: set[str],
        existing_companies: set[str] | None = None,
        verbose: bool = False,
) -> list[Recipient]:
    if isinstance(existing_companies, bool):
        verbose = existing_companies
        existing_companies = None
    payload_text = _strip_json_fence(raw_response)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        _verbose(verbose, "JSON parser skipped response because it is not valid JSON.")
        return []

    if isinstance(payload, dict):
        lead_rows = payload.get("leads", [])
    elif isinstance(payload, list):
        lead_rows = payload
    else:
        _verbose(verbose, f"JSON parser skipped unsupported payload type: {type(payload).__name__}.")
        return []

    _verbose(verbose, f"JSON lead row count: {len(lead_rows)}.")
    rows: list[dict[str, str]] = []
    for lead in lead_rows:
        if not isinstance(lead, dict):
            continue
        company = str(lead.get("company", "")).strip()
        emails = lead.get("emails", lead.get("mail", lead.get("email", "")))
        email_values = emails if isinstance(emails, list) else [emails]
        sources = lead.get("source_urls", lead.get("source_url", lead.get("source", "")))
        source_values = sources if isinstance(sources, list) else [sources]
        source = str(source_values[0]) if source_values else ""
        for email in email_values:
            rows.append({"company": company, "mail": str(email), "source_url": source})

    return _extract_from_rows(rows, "company", "mail", existing_emails, existing_companies, "source_url", verbose)


def _extract_from_rows(
        rows: list[dict[str, str]],
        company_field: str,
        email_field: str,
        existing_emails: set[str],
        existing_companies: set[str] | None = None,
        source_field: str | None = None,
        verbose: bool = False,
) -> list[Recipient]:
    recipients: list[Recipient] = []
    seen_emails = {email.lower() for email in existing_emails}
    seen_companies = {company for company in existing_companies or set() if company}

    for row in rows:
        company = str(row.get(company_field, "")).strip()
        company_key = _normalize_company(company)
        email = normalize_email(str(row.get(email_field, ""))).lower()
        source_url = str(row.get(source_field, "")).strip() if source_field else ""
        if not company or not email:
            _verbose(verbose, f"Recipient row skipped because company or email is missing: {row!r}.")
            continue
        if source_field and not source_url:
            _verbose(verbose, f"Recipient row skipped because source URL is missing: {row!r}.")
            continue
        if company_key in seen_companies:
            _verbose(verbose, f"Recipient row skipped because company already exists for this mode: {company}.")
            continue
        if email in seen_emails or not EMAIL_PATTERN.match(email):
            reason = "duplicate/existing" if email in seen_emails else "invalid email format"
            _verbose(verbose, f"Recipient row skipped because of {reason}: {email}.")
            continue

        recipients.append(Recipient(email=email, company=company))
        seen_emails.add(email)
        _verbose(verbose, f"Recipient row accepted: {company} <{email}>.")

    return recipients


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


def _strip_csv_fence(text: str) -> str:
    stripped = text.strip()
    matches = re.findall(r"```csv\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    for match in matches:
        candidate = match.strip()
        first_line = candidate.splitlines()[0].strip().lower() if candidate.splitlines() else ""
        if "company" in first_line and ("mail" in first_line or "email" in first_line):
            return candidate
    if matches:
        return matches[0].strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:csv|json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    matches = re.findall(r"```json\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if matches:
        return matches[0].strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json|csv)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


class DefaultCsvDialect(csv.Dialect):
    """Standard CSV dialect (equivalent to Excel) without using the Excel name."""
    delimiter = ','
    quotechar = '"'
    doublequote = True
    skipinitialspace = False
    lineterminator = '\r\n'
    quoting = csv.QUOTE_MINIMAL


def _detect_dialect(text: str) -> csv.Dialect | type[csv.Dialect]:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        return DefaultCsvDialect


def _find_field(row: dict[str, str], allowed_keys: set[str]) -> str | None:
    for field in row:
        if not field:
            continue
        if normalize_key(field) in allowed_keys:
            return field
    return None


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


def _model_for_provider(provider: str, gemini_model: str, openai_model: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "self":
        return "self"
    if normalized == "openai":
        return os.getenv("OPENAI_MODEL", openai_model)
    return os.getenv("GEMINI_MODEL", gemini_model)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
