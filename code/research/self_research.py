from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from mail_sender.email_validation import validate_email_address
from mail_sender.modes import MailMode
from mail_sender.recipients import Recipient, normalize_email
from research import mode_instructions
from research.logging_utils import info as _info
from research.logging_utils import verbose as _verbose
from research.parsing import normalize_company, parse_recipients
from research.providers import generate_with_ollama

EMAIL_EXTRACT_PATTERN = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
HTML_TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
HTML_LINK_PATTERN = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
BAD_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf")
CONTACT_LINK_HINTS = ("contact", "about", "team", "people", "staff", "career", "impressum")
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MailSenderSystemResearch/1.0; +https://example.local)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def run_self_research(
        config,
        mode: MailMode,
        existing_emails: set[str],
        existing_companies: set[str],
) -> list[Recipient]:
    """Run local search/crawl research and return centrally deduplicated recipients."""
    target_count = config.send_target_count if config.send_target_count > 0 else config.max_companies
    seen_emails = {email.lower() for email in existing_emails}
    seen_companies = {company for company in existing_companies if company}
    recipients: list[Recipient] = []

    queries = _self_search_queries(config, mode)
    _info(
        f"Starting self research with {len(queries)} keyword(s), "
        f"{config.self_search_pages} search page(s), crawl depth {config.self_crawl_depth}, "
        f"{config.parallel_threads} worker(s)."
    )
    result_urls = collect_self_search_result_urls(config, queries)
    _info(f"Self research search result URLs found: {len(result_urls)}.")

    if not result_urls:
        raise RuntimeError("Self research found no search result URLs.")

    with ThreadPoolExecutor(max_workers=min(config.parallel_threads, len(result_urls))) as executor:
        futures = {executor.submit(crawl_self_result_url, config, url): url for url in result_urls}
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
                company_key = normalize_company(candidate.company)
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


def run_ollama_web_research(
        config,
        mode: MailMode,
        existing_emails: set[str],
        existing_companies: set[str],
) -> list[Recipient]:
    """Use local crawling for web context, then a local Ollama model to filter CSV output."""
    candidates = run_self_research(config, mode, existing_emails, existing_companies)
    prompt = build_ollama_web_research_prompt(config, mode, _recipients_to_csv_text(candidates))
    raw_response = generate_with_ollama(config.model, prompt, config.ollama_base_url, config.verbose)
    recipients = parse_recipients(raw_response, existing_emails, existing_companies, config.verbose)
    target_count = config.send_target_count or config.max_companies
    if recipients:
        return recipients[:target_count]

    _info("Ollama did not return usable CSV from web candidates; using locally crawled candidates.")
    return candidates[:target_count]


def build_ollama_web_research_prompt(config, mode: MailMode, candidate_csv: str) -> str:
    return f"""
    You are filtering web-researched email leads for mode {mode.label}.

    Keep only relevant recipients for this task:
    {mode_instructions.instructions[mode.label]}

    Rules:
    - Use only rows from the candidate CSV.
    - Do not invent companies, emails, or source URLs.
    - Prefer public company contact addresses over personal addresses unless the mode needs named contacts.
    - Return valid CSV only.
    - CSV header must be exactly:
      company,mail,source_url
    - Return at most {config.send_target_count or config.max_companies} rows.

    Candidate CSV from local web crawling:
    {candidate_csv}
    """.strip()


def collect_self_search_result_urls(config, queries: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for query in queries:
        for page in range(config.self_search_pages):
            search_url = _google_search_url(query, page * config.self_results_per_page)
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


def crawl_self_result_url(config, start_url: str) -> list[Recipient]:
    to_visit = [(start_url, 0)]
    visited: set[str] = set()
    candidates: list[Recipient] = []
    base_netloc = urllib.parse.urlparse(start_url).netloc.lower().removeprefix("www.")

    while to_visit and len(visited) < config.self_crawl_max_pages_per_site:
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


def _self_search_queries(config, mode: MailMode) -> list[str]:
    keywords = [keyword.strip() for keyword in config.self_search_keywords if keyword.strip()]
    if not keywords:
        keywords = list(default_self_keywords(mode.label))
    return keywords


def default_self_keywords(mode_name: str) -> tuple[str, ...]:
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
    hinted_links: list[str] = []
    other_links: list[str] = []
    seen: set[str] = set()
    for href in HTML_LINK_PATTERN.findall(html_text):
        target = urllib.parse.urljoin(current_url, html.unescape(href))
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower().removeprefix("www.") != base_netloc:
            continue
        normalized = _normalize_url_for_dedupe(target)
        if normalized in seen or _looks_like_asset_url(parsed.path):
            continue
        seen.add(normalized)
        path = parsed.path.lower()
        if any(hint in path for hint in CONTACT_LINK_HINTS):
            hinted_links.append(target)
        else:
            other_links.append(target)
    return hinted_links + other_links


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
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


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


def _looks_like_asset_url(path: str) -> bool:
    return path.lower().endswith((
        ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
        ".pdf", ".zip", ".rar", ".7z", ".mp4", ".mp3", ".woff", ".woff2", ".ttf",
    ))


def _is_blocked_result_url(url: str) -> bool:
    netloc = urllib.parse.urlparse(url).netloc.lower()
    blocked = ("google.", "youtube.", "facebook.", "instagram.", "linkedin.", "twitter.", "x.com")
    return any(domain in netloc for domain in blocked)


def _recipients_to_csv_text(recipients: list[Recipient]) -> str:
    lines = ["company,mail,source_url"]
    for recipient in recipients:
        lines.append(f"{_csv_cell(recipient.company)},{_csv_cell(recipient.email)},self-crawl")
    return "\n".join(lines)


def _csv_cell(value: str) -> str:
    if any(char in value for char in [",", '"', "\n", "\r"]):
        return '"' + value.replace('"', '""') + '"'
    return value
