"""AI lead research pipeline with provider calls, context uploads, and local filters."""

# Local imports intentionally come after the direct-script path bootstrap below.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import contextlib
import csv
import importlib
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
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
from mail_sender.sent_log import read_logged_emails
from mail_sender.sent_log import read_logged_rows

mode_instructions = importlib.import_module(
    f"{__package__}.mode_instructions" if __package__ else "mode_instructions"
)

SOURCE_KEYS = {"source", "source-url", "sourceurl", "url", "website"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COMPANY_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")
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
    parser = argparse.ArgumentParser(description="research new lead CSV files with Gemini and Google Search grounding.")
    parser.add_argument("--provider", default=env_config.provider, choices=["gemini", "openai"], help="AI research provider.")
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
    )


def run_research(config: ResearchConfig) -> tuple[Path | None, list[Recipient]]:
    """Run one AI research pass and return the optional CSV path plus usable recipients."""
    if config.min_companies < 1 or config.max_companies < config.min_companies:
        raise ValueError("Company limits must satisfy 1 <= min_companies <= max_companies.")

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
            
        iteration += 1
        if iteration > 1:
            _info(f"Research iteration {iteration}: {len(all_recipients)}/{target_count} recipients found so far.")

        _info("Building AI research prompt.")
        prompt = build_prompt(config, mode, seen_emails_in_run, seen_companies_in_run, input_context)
        _verbose(config.verbose, f"AI prompt characters: {len(prompt)}")

        _info("Calling AI provider now; this can take a moment.")
        raw_response = generate_with_provider(
            config.provider, config.model, prompt, attachments, config.reasoning_effort, config.verbose
        )
        if _needs_retry(raw_response, seen_emails_in_run, config.verbose) and attachments:
            _info("AI response was not usable yet; retrying once without CV/resume uploads.")
            _verbose(config.verbose, "AI provider returned no usable CSV with attachment uploads; retrying once without attachment uploads.")
            raw_response = generate_with_provider(
                config.provider, config.model, prompt, [], config.reasoning_effort, config.verbose
            )
        if _needs_retry(raw_response, seen_emails_in_run, config.verbose):
            retry_prompt = build_prompt(config, mode, set(), set(), input_context)
            _info("AI response still was not usable; retrying once with a smaller exclusion prompt.")
            _verbose(config.verbose, "AI provider still returned no usable CSV; retrying once with a smaller prompt and local post-filtering.")
            _verbose(config.verbose, f"Lite AI prompt characters: {retry_prompt}")
            raw_response = generate_with_provider(
                config.provider, config.model, retry_prompt, [], config.reasoning_effort, config.verbose
            )
        _verbose(config.verbose, f"Raw AI response characters: {len(raw_response)}")

        _info("Parsing and filtering AI response.")
        new_recipients = parse_recipients(raw_response, seen_emails_in_run, seen_companies_in_run, config.verbose)
        _info(f"Usable new recipients found in this iteration: {len(new_recipients)}.")
        
        if not new_recipients:
            _info("No more new recipients found in this iteration.")
            if iteration == 1:
                raise RuntimeError("Gemini returned no new usable email addresses on the first attempt.")
            break

        for r in new_recipients:
            all_recipients.append(r)
            seen_emails_in_run.add(r.email.lower())
            seen_companies_in_run.add(_normalize_company(r.company))

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
    raise ValueError("Unknown research provider. Use gemini or openai.")


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


def _detect_dialect(text: str) -> csv.Dialect | type[csv.Dialect]:
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


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default.resolve()
    return Path(value).resolve()


def _model_for_provider(provider: str, gemini_model: str, openai_model: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "openai":
        return os.getenv("OPENAI_MODEL", openai_model)
    return os.getenv("GEMINI_MODEL", gemini_model)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
