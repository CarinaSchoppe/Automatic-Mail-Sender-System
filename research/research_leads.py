from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from mail_sender.attachments import list_attachments
from mail_sender.modes import MODE_NAMES, MailMode, get_mode
from mail_sender.recipients import COMPANY_KEYS
from mail_sender.recipients import EMAIL_KEYS
from mail_sender.recipients import Recipient
from mail_sender.recipients import list_recipient_files
from mail_sender.recipients import normalize_email
from mail_sender.recipients import normalize_key
from mail_sender.recipients import read_recipients
from mail_sender.sent_log import read_logged_emails
from . import mode_instructions

SOURCE_KEYS = {"source", "source-url", "sourceurl", "url", "website"}

RESEARCH_MODE = "PhD"
AI_PROVIDER = "gemini"
GEMINI_MODEL = "gemini-2.5-flash-lite"
OPENAI_MODEL = "gpt-5.4"
MIN_COMPANIES = 15
MAX_COMPANIES = 25
PERSON_EMAILS_PER_COMPANY = 3
WRITE_OUTPUT = True
UPLOAD_ATTACHMENTS = True
BASE_DIR = Path(__file__).resolve().parents[1]
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def default_config() -> ResearchConfig:
    load_dotenv()
    provider = os.getenv("RESEARCH_AI_PROVIDER", AI_PROVIDER)
    return ResearchConfig(
        provider=provider,
        mode_name=os.getenv("RESEARCH_MODE", RESEARCH_MODE),
        model=_model_for_provider(provider),
        min_companies=_env_int("RESEARCH_MIN_COMPANIES", MIN_COMPANIES),
        max_companies=_env_int("RESEARCH_MAX_COMPANIES", MAX_COMPANIES),
        person_emails_per_company=_env_int("RESEARCH_PERSON_EMAILS_PER_COMPANY", PERSON_EMAILS_PER_COMPANY),
        base_dir=Path(os.getenv("RESEARCH_BASE_DIR", str(BASE_DIR))).resolve(),
        write_output=_env_bool("RESEARCH_WRITE_OUTPUT", WRITE_OUTPUT),
        verbose=_env_bool("RESEARCH_VERBOSE", False),
        upload_attachments=_env_bool("RESEARCH_UPLOAD_ATTACHMENTS", UPLOAD_ATTACHMENTS),
    )


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv) if argv else default_config()
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
    parser = argparse.ArgumentParser(description="research new lead CSV files with Gemini and Google Search grounding.")
    parser.add_argument("--provider", default=env_config.provider, choices=["gemini", "openai"], help="AI research provider.")
    parser.add_argument("--mode", default=env_config.mode_name, choices=MODE_NAMES, help="research mode.")
    parser.add_argument("--model", help="Model name for the selected provider.")
    parser.add_argument("--min-companies", type=int, default=env_config.min_companies)
    parser.add_argument("--max-companies", type=int, default=env_config.max_companies)
    parser.add_argument("--person-emails-per-company", type=int, default=env_config.person_emails_per_company)
    parser.add_argument("--base-dir", default=str(env_config.base_dir))
    parser.add_argument("--no-write-output", action="store_true", help="Do not write the generated CSV file.")
    parser.add_argument("--no-upload-attachments", action="store_true", help="Do not upload mode attachment files to Gemini.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed AI research logging.")
    args = parser.parse_args(argv)

    return ResearchConfig(
        provider=args.provider,
        mode_name=args.mode,
        model=args.model or _model_for_provider(args.provider),
        min_companies=args.min_companies,
        max_companies=args.max_companies,
        person_emails_per_company=args.person_emails_per_company,
        base_dir=Path(args.base_dir).resolve(),
        write_output=env_config.write_output and not args.no_write_output,
        verbose=env_config.verbose or args.verbose,
        upload_attachments=env_config.upload_attachments and not args.no_upload_attachments,
    )


def run_research(config: ResearchConfig) -> tuple[Path | None, list[Recipient]]:
    if config.min_companies < 1 or config.max_companies < config.min_companies:
        raise ValueError("Company limits must satisfy 1 <= min_companies <= max_companies.")

    _verbose(config.verbose, f"Base directory: {config.base_dir}")
    _verbose(config.verbose, f"AI provider: {config.provider}")
    _verbose(config.verbose, f"research mode setting: {config.mode_name}")
    _verbose(config.verbose, f"AI model: {config.model}")
    _verbose(config.verbose, f"Company target range: {config.min_companies}-{config.max_companies}")
    _verbose(config.verbose, f"Person emails per company target: {config.person_emails_per_company}")
    _verbose(config.verbose, f"Write output CSV: {config.write_output}")
    _verbose(config.verbose, f"Upload attachment context to AI provider: {config.upload_attachments}")

    mode = get_mode(config.mode_name, config.base_dir)
    _verbose(config.verbose, f"Resolved mode: {mode.label}")
    _verbose(config.verbose, f"Mode input directory: {mode.recipients_dir}")
    _verbose(config.verbose, f"Mode attachment directory: {mode.attachments_dir}")
    _verbose(config.verbose, f"Mode output Excel log: {mode.log_path}")

    attachments = list_attachments(mode.attachments_dir) if config.upload_attachments else []
    if not config.upload_attachments:
        _verbose(config.verbose, "Attachment upload disabled; the provider will use prompt, input context, and web search only.")
    if attachments:
        for attachment in attachments:
            _verbose(config.verbose, f"Attachment context queued for provider upload: {attachment}")
    elif config.upload_attachments:
        _verbose(config.verbose, "No attachment context files found for this mode.")

    existing_emails = collect_existing_emails(config.base_dir)
    _verbose(config.verbose, f"Existing email exclusions loaded: {len(existing_emails)}")

    input_context = read_input_context(mode.recipients_dir)
    _verbose(config.verbose, f"Mode-specific input context characters: {len(input_context)}")

    prompt = build_prompt(config, mode, existing_emails, input_context)
    _verbose(config.verbose, f"AI prompt characters: {len(prompt)}")

    raw_response = generate_with_provider(config.provider, config.model, prompt, attachments, config.verbose)
    if _needs_retry(raw_response, existing_emails) and attachments:
        _verbose(
            config.verbose,
            "AI provider returned no usable CSV with attachment uploads; retrying once without attachment uploads.",
        )
        raw_response = generate_with_provider(config.provider, config.model, prompt, [], config.verbose)
    if _needs_retry(raw_response, existing_emails):
        retry_prompt = build_prompt(config, mode, set(), input_context)
        _verbose(
            config.verbose,
            "AI provider still returned no usable CSV; retrying once with a smaller prompt and local post-filtering.",
        )
        _verbose(config.verbose, f"Lite AI prompt characters: {len(retry_prompt)}")
        raw_response = generate_with_provider(config.provider, config.model, retry_prompt, [], config.verbose)
    _verbose(config.verbose, f"Raw AI response characters: {len(raw_response)}")

    recipients = parse_recipients(raw_response, existing_emails)
    _verbose(config.verbose, f"Usable new recipients after CSV parsing and exclusion filtering: {len(recipients)}")
    if not recipients:
        raise RuntimeError("Gemini returned no new usable email addresses.")

    output_path = None
    if config.write_output:
        output_path = write_recipients_csv(mode.recipients_dir, mode.label, recipients)
        _verbose(config.verbose, f"Wrote research CSV: {output_path}")
    else:
        _verbose(config.verbose, "research CSV was not written because output writing is disabled.")
    return output_path, recipients


def _needs_retry(raw_response: str, existing_emails: set[str]) -> bool:
    if _is_model_error(raw_response):
        return True
    _verbose(globals().get("VERBOSE", True), f"No Model error")
    try:
        return not parse_recipients(raw_response, existing_emails)
    except ValueError as error:
        _verbose(globals().get("VERBOSE", True), f"Failed to parse CSV")
        _verbose(globals().get("VERBOSE", True), f"{error}")
        return True


def _is_model_error(raw_response: str) -> bool:
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
        _verbose(globals().get("VERBOSE", True), f"AI provider returned an error: {text}")
    return output


def collect_existing_emails(base_dir: Path) -> set[str]:
    emails: set[str] = set()
    for mode_name in MODE_NAMES:
        mode = get_mode(mode_name, base_dir)
        emails.update(read_logged_emails(mode.log_path))
        for path in list_recipient_files(mode.recipients_dir):
            emails.update(recipient.email.lower() for recipient in read_recipients(path))
    return emails


def read_input_context(directory: Path, max_chars: int = 6000) -> str:
    parts: list[str] = []
    for path in list_recipient_files(directory):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        cleaned = text.strip()
        if cleaned:
            parts.append(f"File: {path.name}\n{cleaned}")

    context = "\n\n".join(parts)
    if len(context) > max_chars:
        return context[:max_chars].rstrip() + "\n...[truncated]"
    return context


def build_prompt(config: ResearchConfig, mode: MailMode, existing_emails: set[str], input_context: str = "") -> str:
    excluded = "\n".join(sorted(existing_emails)) or "(none)"
    input_reference = input_context.strip() or "(no mode-specific input files found)"
    contact_requirement = (
        f"- For PhD, include the general company contact email plus up to {config.person_emails_per_company} "
        "decision-maker work emails per company when public sources support them."
        if mode.label == "PhD"
        else "- For Freelance, one general or relevant contact email per company is enough. But 2 would be better!"
    )

    return f"""
    You are a careful B2B lead researcher.

    Use web search, the mode-specific input context, and any uploaded attachment context if provided.

    Mode: {mode.label}

    Task:
    {mode_instructions.instructions[mode.label]}

    Requirements:
    - Find leads from {config.min_companies} to {config.max_companies} relevant companies.
    - Do not include any email address already listed in the exclusion list.
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

    Mode-specific input CSV/TXT context:
    {input_reference}
    """.strip()


def generate_with_provider(
        provider: str,
        model: str,
        prompt: str,
        attachment_paths: list[Path],
        verbose: bool = False,
) -> str:
    normalized = provider.strip().lower()
    if normalized == "gemini":
        return generate_with_gemini(model, prompt, attachment_paths, verbose)
    if normalized == "openai":
        return generate_with_openai(model, prompt, attachment_paths, verbose)
    raise ValueError("Unknown research provider. Use gemini or openai.")


def generate_with_gemini(model: str, prompt: str, attachment_paths: list[Path], verbose: bool = False) -> str:
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
    uploaded_files = [client.files.upload(file=path) for path in attachment_paths]
    _verbose(verbose, "Calling Gemini with Google Search grounding enabled.")
    response = client.models.generate_content(
        model=model,
        contents=[prompt, *uploaded_files],
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
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


def generate_with_openai(model: str, prompt: str, attachment_paths: list[Path], verbose: bool = False) -> str:
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
    for path in attachment_paths:
        with path.open("rb") as handle:
            uploaded_files.append(client.files.create(file=handle, purpose="user_data"))

    content = [{"type": "input_text", "text": prompt}]
    content.extend({"type": "input_file", "file_id": uploaded_file.id} for uploaded_file in uploaded_files)
    _verbose(verbose, "Calling OpenAI Responses API with web_search enabled.")
    response = client.responses.create(
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
            "effort": "high",
            "summary": "auto",
        },
        max_output_tokens=32000,
    )
    _verbose(verbose, "OpenAI response received.")
    response_text = _extract_openai_response_text(response)
    _verbose(verbose, f"OpenAI response output_text raw: {response_text!r}")
    _verbose_openai_output(verbose, response)
    return response_text


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


def parse_recipients(raw_response: str, existing_emails: set[str]) -> list[Recipient]:
    csv_text = _strip_csv_fence(raw_response)
    rows = list(csv.DictReader(csv_text.splitlines(), dialect=_detect_dialect(csv_text))) if csv_text.strip() else []
    if rows:
        company_field = _find_field(rows[0], COMPANY_KEYS)
        email_field = _find_field(rows[0], EMAIL_KEYS)
        if company_field and email_field:
            source_field = _find_field(rows[0], SOURCE_KEYS)
            recipients = _extract_from_rows(rows, company_field, email_field, existing_emails, source_field)
            _verbose(globals().get("VERBOSE", True), f"Parsed CSV recipients: {len(recipients)}")
            return recipients

    recipients = _parse_headerless_csv_recipients(csv_text, existing_emails)
    if recipients:
        _verbose(globals().get("VERBOSE", True), f"Parsed headerless CSV recipients: {len(recipients)}")
        return recipients

    recipients = _parse_json_recipients(raw_response, existing_emails)
    if recipients:
        _verbose(globals().get("VERBOSE", True), f"Parsed JSON recipients: {len(recipients)}")
        return recipients

    return []


def _parse_headerless_csv_recipients(raw_text: str, existing_emails: set[str]) -> list[Recipient]:
    text = raw_text.strip().strip("'\"`").replace("\\n", "\n")
    if not text:
        return []

    try:
        rows = list(csv.reader(text.splitlines(), dialect=_detect_dialect(text)))
    except csv.Error:
        return []

    parsed_rows: list[dict[str, str]] = []
    for row in rows:
        cells = [cell.strip().strip("'\"`") for cell in row if cell.strip()]
        if len(cells) < 2:
            continue
        email = cells[-1]
        company = ", ".join(cells[:-1]).strip()
        parsed_rows.append({"company": company, "mail": email})

    return _extract_from_rows(parsed_rows, "company", "mail", existing_emails)


def _parse_json_recipients(raw_response: str, existing_emails: set[str]) -> list[Recipient]:
    payload_text = _strip_json_fence(raw_response)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        lead_rows = payload.get("leads", [])
    elif isinstance(payload, list):
        lead_rows = payload
    else:
        return []

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

    return _extract_from_rows(rows, "company", "mail", existing_emails, "source_url")


def _extract_from_rows(
        rows: list[dict[str, str]],
        company_field: str,
        email_field: str,
        existing_emails: set[str],
        source_field: str | None = None,
) -> list[Recipient]:
    recipients: list[Recipient] = []
    seen_emails = {email.lower() for email in existing_emails}
    seen_companies: set[str] = set()

    for row in rows:
        company = str(row.get(company_field, "")).strip()
        company_key = company.lower()
        email = normalize_email(str(row.get(email_field, ""))).lower()
        source_url = str(row.get(source_field, "")).strip() if source_field else ""
        if not company or not email:
            continue
        if source_field and not source_url:
            continue
        if email in seen_emails or not EMAIL_PATTERN.match(email):
            continue

        recipients.append(Recipient(email=email, company=company))
        seen_emails.add(email)
        seen_companies.add(company_key)

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


def _detect_dialect(text: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        return csv.excel


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


def _model_for_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "openai":
        return os.getenv("OPENAI_MODEL", OPENAI_MODEL)
    return os.getenv("GEMINI_MODEL", GEMINI_MODEL)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
