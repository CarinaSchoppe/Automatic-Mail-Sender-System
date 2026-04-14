from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mail_sender.attachments import list_attachments
from mail_sender.modes import MODE_NAMES, MailMode, get_mode
from mail_sender.recipients import Recipient, list_recipient_files, normalize_email, read_recipients
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
    return ResearchConfig(
        mode_name=RESEARCH_MODE,
        model=GEMINI_MODEL,
        min_companies=MIN_COMPANIES,
        max_companies=MAX_COMPANIES,
        person_emails_per_company=PERSON_EMAILS_PER_COMPANY,
        base_dir=BASE_DIR,
        write_output=WRITE_OUTPUT,
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
    parser = argparse.ArgumentParser(description="Research new lead CSV files with Gemini and Google Search grounding.")
    parser.add_argument("--mode", default=RESEARCH_MODE, choices=MODE_NAMES, help="Research mode.")
    parser.add_argument("--model", default=GEMINI_MODEL, help="Gemini model name.")
    parser.add_argument("--min-companies", type=int, default=MIN_COMPANIES)
    parser.add_argument("--max-companies", type=int, default=MAX_COMPANIES)
    parser.add_argument("--person-emails-per-company", type=int, default=PERSON_EMAILS_PER_COMPANY)
    parser.add_argument("--base-dir", default=str(BASE_DIR))
    parser.add_argument("--no-write-output", action="store_true", help="Do not write the generated CSV file.")
    args = parser.parse_args(argv)

    return ResearchConfig(
        mode_name=args.mode,
        model=args.model,
        min_companies=args.min_companies,
        max_companies=args.max_companies,
        person_emails_per_company=args.person_emails_per_company,
        base_dir=Path(args.base_dir).resolve(),
        write_output=not args.no_write_output,
    )


def run_research(config: ResearchConfig) -> tuple[Path | None, list[Recipient]]:
    if config.min_companies < 1 or config.max_companies < config.min_companies:
        raise ValueError("Company limits must satisfy 1 <= min_companies <= max_companies.")

    mode = get_mode(config.mode_name, config.base_dir)
    attachments = list_attachments(mode.attachments_dir)
    existing_emails = collect_existing_emails(config.base_dir)
    prompt = build_prompt(config, mode, existing_emails)
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


def build_prompt(config: ResearchConfig, mode: MailMode, existing_emails: set[str]) -> str:
    mode_instructions = {
        "PhD": (
            "Find organisations that are credible Industry PhD collaboration prospects for AI governance, "
            "responsible AI, enterprise GenAI risk, digital transformation, or innovation. Prefer companies "
            "with an Australian, Brisbane, university partnership, AI, data, risk, governance, or innovation fit. "
            "For each company, find the general company contact email plus two to three decision-maker work emails "
            "where public sources support them."
        ),
        "Freelance German": (
            "Find German-language DACH education providers, AVGS or publicly funded training organisations, "
            "vocational education providers, corporate training providers, or remote IT training companies that may "
            "collaborate with a German-speaking freelance IT, AI, cybersecurity, and digital education lecturer. "
            "One general contact email per company is enough."
        ),
        "Freelance English": (
            "Find English-oriented training providers, corporate learning companies, vocational education providers, "
            "or remote IT training organisations in Germany, Austria, Switzerland, or Luxembourg that may collaborate "
            "with an English-speaking freelance IT, AI, cybersecurity, and digital education lecturer. One general "
            "or relevant contact email per company is enough."
        ),
    }
    excluded = "\n".join(sorted(existing_emails)) or "(none)"

    return f"""
You are a careful B2B lead researcher. Use Google Search grounding and the uploaded attachment context.

Mode: {mode.label}
Task:
{mode_instructions[mode.label]}

Requirements:
- Find {config.min_companies} to {config.max_companies} different companies.
- Do not include any email address already listed in the exclusion list.
- Prefer directly verified, public company or work email addresses.
- Do not invent email addresses.
- Do not include generic consumer contact forms without an email address.
- Output JSON only, no markdown, no commentary.
- JSON schema:
  {{
    "leads": [
      {{
        "company": "Company name",
        "emails": ["info@example.com", "person@example.com"],
        "source_urls": ["https://example.com/contact"],
        "reason": "Short fit reason"
      }}
    ]
  }}

Existing email exclusion list:
{excluded}
""".strip()


def generate_with_gemini(model: str, prompt: str, attachment_paths: list[Path]) -> str:
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
    payload = json.loads(_strip_json_fence(raw_response))
    leads = payload.get("leads", [])
    recipients: list[Recipient] = []
    seen_emails = {email.lower() for email in existing_emails}
    seen_companies: set[str] = set()

    for lead in leads:
        company = str(lead.get("company", "")).strip()
        if not company or company.lower() in seen_companies:
            continue

        accepted_for_company = False
        for email_value in _lead_emails(lead):
            email = normalize_email(str(email_value)).lower()
            if email in seen_emails or not EMAIL_PATTERN.match(email):
                continue
            recipients.append(Recipient(email=email, company=company))
            seen_emails.add(email)
            accepted_for_company = True

        if accepted_for_company:
            seen_companies.add(company.lower())
        if len(seen_companies) >= max_companies:
            break

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


def _lead_emails(lead: dict[str, Any]) -> list[Any]:
    emails = lead.get("emails", [])
    if isinstance(emails, list):
        return emails
    return [emails]


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
