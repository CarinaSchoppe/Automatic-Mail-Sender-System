"""
Zentrale Verwaltung der KI-Prompts für die Recherche-Pipeline.
Ermöglicht das Laden und Speichern von Prompts aus einer TOML-Datei
und stellt Standard-Prompts für verschiedene Modi bereit.
"""

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

DEFAULT_PROMPTS["Freelance German"] = """
Finde ausschliesslich deutschsprachige Online-only Bildungsanbieter, die realistisch mit einer remote arbeitenden freiberuflichen Dozentin oder Trainerin zusammenarbeiten koennten.

Harte Ausschlussregeln:
- Nur Anbieter aufnehmen, bei denen auf der offiziellen Website klar sichtbar ist, dass sie reine Online-Unterrichtskurse, Live-Online-Kurse, virtuelle Klassenraeume, E-Learning oder remote durchfuehrbare Kurse anbieten.
- Keine reinen Praesenzanbieter.
- Keine Anbieter aufnehmen, deren Kurse nur als Praesenz, Standortkurs, Inhouse vor Ort oder Hybrid beschrieben sind.
- Keine allgemeinen Firmen aufnehmen, die keine klar sichtbaren Online-Unterrichtsangebote verkaufen.
- Keine Firmen aufnehmen, die nicht klar in Weiterbildung, Training, Unterricht, Umschulung, Coaching oder Kursdurchfuehrung taetig sind.
- Nur Unternehmen aufnehmen, deren Website klar zeigt, dass sie auf Deutsch oder Englisch arbeiten und international oder ueberregional online liefern koennen.

Prioritaet:
- Online-Bildungstraeger
- AVGS-/AZAV-Traeger mit eindeutig online durchfuehrbaren Kursen
- oeffentlich gefoerderte Online-Weiterbildungstraeger
- Online-Umschulungs- und Reskilling-Anbieter
- Corporate-Training-Anbieter mit klaren Live-Online- oder E-Learning-Angeboten
- Anbieter, die externe oder freiberufliche Dozenten, Trainer, Coaches, Tutoren oder Kursleiter einsetzen koennten

Bevorzugte Laender:
- Deutschland
- Australien
- Schweiz
- Oesterreich
- Luxemburg
- weltweit, wenn der Anbieter deutsch- oder englischsprachig arbeitet und international Online-Kurse anbietet

Fachlicher Fit muss klar zu mindestens einem dieser Themen passen:
- IT
- Softwareentwicklung
- KI / AI
- Daten / Analytics / BI
- Cybersecurity / IT-Security
- digitale Wirtschaftskompetenzen
- kaufmaennische oder betriebswirtschaftliche Weiterbildung mit starkem Digitalbezug

Lead-Qualitaet:
- Bevorzuge Unternehmen, die laufend viele Kurse, Weiterbildungen, Bootcamps, Umschulungen oder Corporate-Trainings anbieten.
- Bevorzuge Anbieter, bei denen eine Zusammenarbeit mit externen Dozenten realistisch ist.
- Schicke keine Zufallstreffer, Branchenverzeichnisse, reine Jobboersen, reine Universitaeten ohne externe Trainingslogik oder Unternehmen ohne klaren Online-Kursverkauf.
- Wenn der Online-only-Fit nicht klar beweisbar ist, die Firma weglassen.

Fuer jedes Unternehmen:
- nenne 1 relevante oeffentliche E-Mail-Adresse
- optional eine zweite oeffentliche E-Mail-Adresse, wenn sie klar passend ist
- keine Kontaktformulare
- keine geratenen oder aus Mustern abgeleiteten E-Mail-Adressen
- nur E-Mail-Adressen, die sichtbar auf einer oeffentlichen Webseite stehen
- nimm nur E-Mail-Adressen, die auf einer offiziellen Anbieter-Website oder einer klar zuordenbaren offiziellen Unternehmensseite sichtbar sind
- wenn die E-Mail nicht eindeutig oeffentlich verifizierbar ist, die Zeile weglassen
- gib die exakte oeffentliche source_url an, auf der die E-Mail gefunden wurde

Schliesse alle E-Mail-Adressen aus der Exclusion-Liste aus. Die Exclusion-Liste enthaelt bereits gesendete, bereits gefundene und als nicht valide markierte E-Mails.

Gib ausschliesslich CSV mit diesem exakten Header zurueck:
company,mail,source_url

Regeln:
- eine Zeile pro E-Mail-Adresse
- bei mehreren E-Mails pro Unternehmen den Unternehmensnamen je Zeile wiederholen
- wenn nicht genug verifizierbare Online-only Ergebnisse gefunden werden, weniger Ergebnisse statt geratener Ergebnisse zurueckgeben
- kein Markdown
- keine Kommentare
- kein zusaetzlicher Text
""".strip()

DEFAULT_PROMPTS["Freelance English"] = """
Find only online-only education or training providers that may realistically hire or collaborate with a remote freelance lecturer or trainer in IT, business, AI, software, data, or cybersecurity.

Hard exclusion rules:
- Only include providers whose official website clearly shows pure online courses, live online classes, virtual classrooms, e-learning, remote training, or fully online course delivery.
- Do not include in-person-only providers.
- Do not include providers whose courses are only described as in-person, location-based, on-site, or hybrid.
- Do not include generic companies without a clear public online course or training offer.
- Do not include companies that are not clearly active in education, training, tutoring, coaching, reskilling, course delivery, or corporate learning.
- Only include companies whose website clearly shows they operate in German or English and can deliver online courses internationally or beyond one local city.

Allowed geography:
- Germany
- Australia
- Switzerland
- Austria
- Luxembourg
- worldwide, if the provider works in German or English and offers international online course delivery

Prioritise:
- online education providers
- vocational training providers with clear online delivery
- reskilling and bootcamp providers with online cohorts
- corporate training providers with live-online or e-learning delivery
- apprenticeship or adult-learning providers with fully online courses
- organisations that could realistically use external freelance lecturers, trainers, coaches, tutors, or course instructors

Use the provided files only to understand the trainer profile and topic fit.

Find only organisations whose course portfolio clearly overlaps with:
- IT
- software development
- AI
- data / analytics
- cybersecurity
- digital business skills
- business or commercial training with a strong digital focus

Lead quality:
- Prefer providers running many courses, cohorts, bootcamps, reskilling programmes, or corporate trainings.
- Prefer organisations where collaboration with external freelance trainers is realistic.
- Do not return directories, random companies, job boards, universities without an external-training fit, or providers without clear online course sales.
- If the online-only fit is not clearly provable, omit the company.

For each company:
- include 1 relevant public email address
- optionally include a second public email address if clearly relevant
- do not guess or infer email patterns
- do not include contact forms
- only include emails visibly shown on a public webpage
- only include emails visible on an official provider website or a clearly attributable official company page
- if the email cannot be clearly verified from a public source, omit the row
- include the exact source URL where the email was found

Exclude all emails in the exclusion list. The exclusion list already contains sent emails, previously found emails, and invalid emails.

Return CSV only with this exact header:
company,mail,source_url

Rules:
- one row per email
- repeat company name for multiple emails
- if you cannot verify enough online-only results, return fewer results instead of guessing
- no markdown
- no commentary
- no extra text
""".strip()

DEFAULT_PROMPTS["Overseer"] = DEFAULT_PROMPTS["Overseer"].replace(
    "- Do not include any email address already listed in the exclusion list.\n"
    "- Do not search for or return a company if the company name or email address already appears in the mode-specific sent CSV list, uploaded sent-log file, or exclusions.",
    "- Do not include any email address already listed in the exclusion list. This list contains already sent emails, previously found emails, input CSV emails, output log emails, and invalid_mails.csv entries.\n"
    "- Do not search for or return a company if the company name or email address already appears in the mode-specific sent CSV list, uploaded sent-log file, current input files, or exclusions.\n"
    "- For Freelance modes, apply the online-only provider gate strictly: the company must visibly offer pure online courses or remote course delivery, not just in-person, on-site, or hybrid classes.\n"
    "- For Freelance modes, omit any company whose online-only course fit is uncertain.\n"
    "- For Freelance modes, global companies are allowed when they clearly work in German or English and offer international online course delivery. Prefer Germany, Australia, Switzerland, Austria, Luxembourg, and strong worldwide providers.\n"
    "- Treat an email as usable only when it is clearly verified on an official provider website or clearly attributable official company page; otherwise omit it.",
)


def load_prompts(path: Path = PROMPTS_PATH) -> dict[str, str]:
    """
    Lädt die Prompts aus der prompts.toml Datei.
    Falls die Datei nicht existiert oder fehlerhaft ist, werden die Standardwerte zurückgegeben.

    Args:
        path (Path): Pfad zur TOML-Datei.

    Returns:
        dict[str, str]: Ein Dictionary mit den Prompt-Vorlagen.
    """
    prompts = DEFAULT_PROMPTS.copy()
    if path.exists():
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
                if "prompts" in data:
                    for key, value in data["prompts"].items():
                        if isinstance(key, str) and isinstance(value, str):
                            prompts[key] = value
        except (OSError, tomllib.TOMLDecodeError):
            # Fallback to defaults on error
            pass
    return prompts


def save_prompts(prompts: dict[str, str], path: Path = PROMPTS_PATH) -> None:
    """
    Speichert die übergebenen Prompts in einer TOML-Datei.
    Verwendet Multi-Line-Strings für bessere Lesbarkeit.

    Args:
        prompts (dict[str, str]): Die zu speichernden Prompts.
        path (Path): Zielpfad der TOML-Datei.
    """
    lines = ["# MailSenderSystem AI Prompts", "", "[prompts]"]
    for key, value in prompts.items():
        if "\n" in value:
            # Use multi-line string for better readability, and escape triple quotes if needed
            escaped_multiline = value.replace('"""', '\\"\\"\\"')
            lines.append(f'"{key}" = \"\"\"\n{escaped_multiline}\"\"\"')
        else:
            # Escape backslashes and quotes for TOML string
            escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'"{key}" = "{escaped_value}"')

    try:
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass
