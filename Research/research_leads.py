from __future__ import annotations

import argparse
import csv
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


RESEARCH_MODE = "PhD"
GEMINI_MODEL = "gemini-2.5-flash-lite"
MIN_COMPANIES = 15
MAX_COMPANIES = 25
PERSON_EMAILS_PER_COMPANY = 3
WRITE_OUTPUT = True
BASE_DIR = Path(__file__).resolve().parents[1]


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class ResearchConfig:
    mode_name: str
    model: str
    min_companies: int
    max_companies: int
    person_emails_per_company: int
    base_dir: Path
    write_output: bool


def default_config() -> ResearchConfig:
    load_dotenv()
    return ResearchConfig(
        mode_name=os.getenv("RESEARCH_MODE", RESEARCH_MODE),
        model=os.getenv("GEMINI_MODEL", GEMINI_MODEL),
        min_companies=_env_int("RESEARCH_MIN_COMPANIES", MIN_COMPANIES),
        max_companies=_env_int("RESEARCH_MAX_COMPANIES", MAX_COMPANIES),
        person_emails_per_company=_env_int("RESEARCH_PERSON_EMAILS_PER_COMPANY", PERSON_EMAILS_PER_COMPANY),
        base_dir=Path(os.getenv("RESEARCH_BASE_DIR", str(BASE_DIR))).resolve(),
        write_output=_env_bool("RESEARCH_WRITE_OUTPUT", WRITE_OUTPUT),
    )


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv) if argv else default_config()
    try:
        output_path, recipients = run_research(config)
    except (RuntimeError, ValueError, FileNotFoundError, NotADirectoryError) as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Research mode: {config.mode_name}")
    print(f"New recipients: {len(recipients)}")
    print(f"Output CSV: {output_path if output_path else 'not written'}")
    return 0


def parse_args(argv: list[str]) -> ResearchConfig:
    env_config = default_config()
    parser = argparse.ArgumentParser(description="Research new lead CSV files with Gemini and Google Search grounding.")
    parser.add_argument("--mode", default=env_config.mode_name, choices=MODE_NAMES, help="Research mode.")
    parser.add_argument("--model", default=env_config.model, help="Gemini model name.")
    parser.add_argument("--min-companies", type=int, default=env_config.min_companies)
    parser.add_argument("--max-companies", type=int, default=env_config.max_companies)
    parser.add_argument("--person-emails-per-company", type=int, default=env_config.person_emails_per_company)
    parser.add_argument("--base-dir", default=str(env_config.base_dir))
    parser.add_argument("--no-write-output", action="store_true", help="Do not write the generated CSV file.")
    args = parser.parse_args(argv)

    return ResearchConfig(
        mode_name=args.mode,
        model=args.model,
        min_companies=args.min_companies,
        max_companies=args.max_companies,
        person_emails_per_company=args.person_emails_per_company,
        base_dir=Path(args.base_dir).resolve(),
        write_output=env_config.write_output and not args.no_write_output,
    )


def run_research(config: ResearchConfig) -> tuple[Path | None, list[Recipient]]:
    if config.min_companies < 1 or config.max_companies < config.min_companies:
        raise ValueError("Company limits must satisfy 1 <= min_companies <= max_companies.")

    mode = get_mode(config.mode_name, config.base_dir)
    attachments = list_attachments(mode.attachments_dir)
    existing_emails = collect_existing_emails(config.base_dir)
    input_context = read_input_context(mode.recipients_dir)
    prompt = build_prompt(config, mode, existing_emails, input_context)
    raw_response = generate_with_gemini(config.model, prompt, attachments)
    recipients = parse_recipients(raw_response, existing_emails, config.max_companies)
    if not recipients:
        raise RuntimeError("Gemini returned no new usable email addresses.")

    output_path = None
    if config.write_output:
        output_path = write_recipients_csv(mode.recipients_dir, mode.label, recipients)
    return output_path, recipients


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
    mode_instructions = {
        "PhD": (
            "Find organisations that are credible Industry PhD collaboration prospects for an applied university "
            "collaboration in Australia. Prioritise Australian organisations, but also include strong international "
            "companies, especially US-based organisations, if they have a clear fit for AI governance, responsible AI, "
            "enterprise GenAI risk, digital transformation, innovation, or university-industry research partnerships. "
            "Prefer companies that look willing and able to cooperate with an Industry PhD project and provide a "
            "real-world business context for the research. "
            "For each company, find the general company contact email plus two to three decision-maker work emails "
            "where public sources support them."
        ),
        "Freelance German": (
            "Find German-language organisations that may collaborate with a remote freelance lecturer or trainer. "
            "Prioritise education providers, AVGS or publicly funded training organisations, vocational education "
            "providers, corporate training providers, reskilling or apprenticeship providers, and companies offering "
            "remote or home-office compatible training. The fit should be IT, business, AI, digital skills, software, "
            "cybersecurity, IT security, or related professional education. One general or relevant contact email per "
            "company is enough."
        ),
        "Freelance English": (
            "Find English-oriented organisations that may collaborate with a remote freelance lecturer or trainer. "
            "Prioritise training providers, corporate learning companies, vocational education providers, reskilling "
            "or apprenticeship providers, and companies offering remote or home-office compatible training in Germany, "
            "Austria, Switzerland, Luxembourg, or internationally if the fit is strong. The fit should be IT, business, "
            "AI, digital skills, software, cybersecurity, IT security, or related professional education. One general "
            "or relevant contact email per company is enough."
        ),
    }
    excluded = "\n".join(sorted(existing_emails)) or "(none)"
    input_reference = input_context.strip() or "(no mode-specific input files found)"
    contact_requirement = (
        f"- For PhD, include the general company contact email plus up to {config.person_emails_per_company} "
        "decision-maker work emails per company when public sources support them."
        if mode.label == "PhD"
        else "- For Freelance, one general or relevant contact email per company is enough."
    )

    return f"""
You are a careful B2B lead researcher. Use Google Search grounding and the uploaded attachment context.

Mode: {mode.label}
Task:
{mode_instructions[mode.label]}

Requirements:
- Find {config.min_companies} to {config.max_companies} different companies.
- Do not include any email address already listed in the exclusion list.
- Use the mode-specific input CSV/TXT context below as examples and extra context, but do not repeat excluded emails.
- Prefer directly verified, public company or work email addresses.
- Do not invent email addresses.
- Do not include generic consumer contact forms without an email address.
{contact_requirement}
- Output CSV only, no markdown, no commentary.
- CSV header must be exactly:
  company,mail
- Use one row per email address. If you find multiple contacts for one company, repeat the company name on separate rows.

Existing email exclusion list:
{excluded}

Mode-specific input CSV/TXT context:
{input_reference}
""".strip()


def generate_with_gemini(model: str, prompt: str, attachment_paths: list[Path]) -> str:
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
    uploaded_files = [client.files.upload(file=path) for path in attachment_paths]
    response = client.models.generate_content(
        model=model,
        contents=[prompt, *uploaded_files],
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        ),
    )
    return response.text or ""


def parse_recipients(raw_response: str, existing_emails: set[str], max_companies: int) -> list[Recipient]:
    csv_text = _strip_csv_fence(raw_response)
    rows = list(csv.DictReader(csv_text.splitlines(), dialect=_detect_dialect(csv_text)))
    if not rows:
        return []

    company_field = _find_field(rows[0], COMPANY_KEYS)
    email_field = _find_field(rows[0], EMAIL_KEYS)
    if not company_field or not email_field:
        raise ValueError("Gemini CSV output must contain company and mail columns.")

    recipients: list[Recipient] = []
    seen_emails = {email.lower() for email in existing_emails}
    seen_companies: set[str] = set()

    for row in rows:
        company = str(row.get(company_field, "")).strip()
        company_key = company.lower()
        email = normalize_email(str(row.get(email_field, ""))).lower()
        if not company or not email:
            continue
        if email in seen_emails or not EMAIL_PATTERN.match(email):
            continue
        if company_key not in seen_companies and len(seen_companies) >= max_companies:
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
        writer.writerow(["company", "mail"])
        for recipient in recipients:
            writer.writerow([recipient.company, recipient.email])
    return path


def _strip_csv_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:csv)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def _detect_dialect(text: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _find_field(row: dict[str, str], allowed_keys: set[str]) -> str | None:
    for field in row:
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
