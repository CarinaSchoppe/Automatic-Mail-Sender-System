from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_PATH = PROJECT_ROOT / "prompts.toml"

DEFAULT_PROMPTS = {
    "PhD": (
        """
        Find companies that are realistic Industry PhD collaboration prospects for applied AI governance research in Australia.

Priority order:
1. Brisbane and South East Queensland
2. Other Australian organisations
3. International organisations only if they have Australian operations, Australian partnerships, or a very strong fit for enterprise AI governance / responsible AI / GenAI risk.

Target organisations should be relevant to at least one of these:
- AI governance
- responsible AI
- enterprise AI / GenAI
- digital transformation
- compliance, risk, assurance, or cybersecurity
- university-industry research collaboration

For each company:
- include 1 general company contact email if publicly listed
- include up to 1 or 2 decision-maker work emails only if they are publicly listed on a reliable public page
- do not guess or infer email patterns
- do not include contact forms
- do not include placeholder or assumed addresses
- only include emails that are visibly written on a public webpage
- include the exact public source URL where the email was found

Exclude all emails in the exclusion list.

Use the provided files only as context for fit, not as contacts to repeat.

Return CSV only with this exact header:
company,mail,source_url

Rules:
- one row per email
- repeat company name for multiple emails
- if you cannot verify enough results, return fewer results
- no markdown
- no commentary
- no extra text
        """).strip(),
    "Freelance German": (
        """Finde deutschsprachige Organisationen, die mit einer remote arbeitenden freiberuflichen Dozentin oder Trainerin zusammenarbeiten könnten.

    Priorität:
    - Bildungsträger
    - AVGS-/AZAV-Träger
    - öffentlich geförderte Weiterbildungsträger
    - Berufsausbildungs- und Umschulungsanbieter
    - Corporate-Training-Anbieter
    - Anbieter mit Remote-, Online- oder Homeoffice-kompatiblen Lehrformaten

    Berücksichtige bevorzugt Organisationen in:
    - Deutschland
    - Schweiz
    - Österreich
    - Luxemburg

    Berücksichtige nur Organisationen, deren Kurs- oder Leistungsportfolio klar zu mindestens einem dieser Themen passt:
    - IT
    - Softwareentwicklung
    - KI / AI
    - Daten / Analytics / BI
    - Cybersecurity / IT-Security
    - digitale Wirtschaftskompetenzen
    - kaufmännische oder betriebswirtschaftliche Weiterbildung mit starkem Digitalbezug

    Nutze die bereitgestellten Dateien nur, um das Profil, die Themen und den fachlichen Fit besser zu verstehen.

    Für jedes Unternehmen:
    - nenne 1 relevante öffentliche E-Mail-Adresse
    - optional eine zweite öffentliche E-Mail-Adresse, wenn sie klar passend ist
    - keine Kontaktformulare
    - keine geratenen oder aus Mustern abgeleiteten E-Mail-Adressen
    - nur E-Mail-Adressen, die sichtbar auf einer öffentlichen Webseite stehen
    - gib die exakte öffentliche source_url an, auf der die E-Mail gefunden wurde

    Schließe alle E-Mail-Adressen aus der Exclusion-Liste aus.

    Gib ausschließlich CSV mit diesem exakten Header zurück:
    company,mail,source_url

    Regeln:
    - eine Zeile pro E-Mail-Adresse
    - bei mehreren E-Mails pro Unternehmen den Unternehmensnamen je Zeile wiederholen
    - wenn nicht genug verifizierbare Ergebnisse gefunden werden, weniger Ergebnisse statt geratener Ergebnisse zurückgeben
    - kein Markdown
    - keine Kommentare
    - kein zusätzlicher Text"""
    ).strip(),
    "Freelance English": (
        """Find organisations that may hire or collaborate with a remote freelance lecturer or trainer in IT, business, AI, software, data, or cybersecurity.

Prioritise:
- education providers
- vocational training providers
- reskilling providers
- corporate training providers
- apprenticeship or adult-learning providers
- organisations that offer remote or online teaching opportunities

Use the provided files only to understand the trainer profile and topic fit.

Find only organisations whose course portfolio clearly overlaps with:
- IT
- software development
- AI
- data / analytics
- cybersecurity
- digital business skills

For each company:
- include 1 relevant public email address
- optionally include a second public email address if clearly relevant
- do not guess or infer email patterns
- do not include contact forms
- only include emails visibly shown on a public webpage
- include the exact source URL

Exclude all emails in the exclusion list.

Return CSV only with this exact header:
company,mail,source_url

Rules:
- one row per email
- repeat company name for multiple emails
- if you cannot verify enough results, return fewer results
- no markdown
- no commentary
- no extra text"""
    ).strip(),
    "Overseer": (
        """
You are a careful B2B lead researcher.

Use medium-to-high reasoning for the research. Use web search, the mode-specific input context,
any uploaded attachment context if provided, and any available tools you need. Use tools automatically
whenever they help verify public source URLs or email addresses.

Mode: {MODE_LABEL}

Task:
{TASK_INSTRUCTIONS}

Requirements:
- Find leads from {MIN_COMPANIES} to {MAX_COMPANIES} relevant companies.
- Do not include any email address already listed in the exclusion list.
- Do not search for or return a company if the company name or email address already appears in the mode-specific sent CSV list, uploaded sent-log file, or exclusions.
- Use the mode-specific input CSV/TXT context only as background for fit and targeting.
- Prefer official company websites and publicly visible work email addresses.
- Only include an email address if it is explicitly shown on a public webpage.
- Do not invent, infer, guess, or pattern-generate email addresses.
- Do not include contact forms without an email address.
- Do not include placeholder or assumed addresses unless that exact address is publicly shown.
{CONTACT_REQUIREMENT}
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
{EXCLUDED_EMAILS}

Existing company exclusion list for this mode:
{EXCLUDED_COMPANIES}

Mode-specific input CSV/TXT context:
{INPUT_CONTEXT}
        """).strip(),
}


def load_prompts(path: Path = PROMPTS_PATH) -> dict[str, str]:
    """Loads prompts from a TOML file. Returns defaults if file missing or keys absent."""
    prompts = DEFAULT_PROMPTS.copy()
    if path.exists():
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
                if "prompts" in data:
                    for key, value in data["prompts"].items():
                        if key in prompts:
                            prompts[key] = value
        except (OSError, tomllib.TOMLDecodeError):
            # Fallback to defaults on error
            pass
    return prompts


def save_prompts(prompts: dict[str, str], path: Path = PROMPTS_PATH) -> None:
    """Saves prompts to a TOML file."""
    lines = ["# MailSenderSystem AI Prompts", "", "[prompts]"]
    for key, value in prompts.items():
        # Escape backslashes and quotes for TOML string
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        if "\n" in value:
            # Use multi-line string for better readability
            lines.append(f'"{key}" = \"\"\"\n{value}\"\"\"')
        else:
            lines.append(f'"{key}" = "{escaped_value}"')

    path.write_text("\n".join(lines), encoding="utf-8")
