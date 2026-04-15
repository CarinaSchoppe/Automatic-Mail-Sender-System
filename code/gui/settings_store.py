from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

SettingKind = Literal["bool", "int", "float", "str", "choice", "list"]


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    kind: SettingKind
    default: Any
    section: str
    help_text: str
    choices: tuple[str, ...] = ()
    min_value: float | None = None
    max_value: float | None = None
    slider: bool = True


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "settings.toml"


SETTINGS_SCHEMA: tuple[SettingSpec, ...] = (
    SettingSpec("RUN_AI_RESEARCH", "Run AI research first", "bool", True, "Run", "Creates a fresh input CSV before the mail sender starts."),
    SettingSpec("MODE", "Mode", "choice", "Freelance_German", "Run", "Selects which templates, input folder, attachments, and sent log are used.", ("PhD", "Freelance_German", "Freelance_English", "Auto")),
    SettingSpec("RESEARCH_AI_PROVIDER", "Research provider", "choice", "gemini", "Research", "gemini/openai use hosted web-capable models, ollama uses local crawling plus local filtering, self only crawls locally.", ("gemini", "openai", "ollama", "self")),
    SettingSpec("GEMINI_MODEL", "Gemini model", "str", "gemini-3-flash-preview", "Research", "Gemini model for hosted research."),
    SettingSpec("OPENAI_MODEL", "OpenAI model", "str", "gpt-5.4-mini-2026-03-17", "Research", "OpenAI model for hosted research."),
    SettingSpec("OLLAMA_MODEL", "Ollama model", "str", "llama3.1:8b", "Research", "Installed local Ollama model used to filter locally crawled candidates."),
    SettingSpec("OLLAMA_BASE_URL", "Ollama base URL", "str", "http://localhost:11434", "Research", "Local Ollama HTTP endpoint."),
    SettingSpec("RESEARCH_REASONING_EFFORT", "Reasoning effort", "choice", "middle", "Research", "Provider reasoning/thinking level.", ("low", "middle", "high")),
    SettingSpec("RESEARCH_MIN_COMPANIES", "Minimum companies", "int", 15, "Research", "Lower bound requested from the AI research prompt.", min_value=1, max_value=500),
    SettingSpec("RESEARCH_MAX_COMPANIES", "Maximum companies", "int", 35, "Research", "Upper bound requested from the AI research prompt.", min_value=1, max_value=1000),
    SettingSpec("RESEARCH_PERSON_EMAILS_PER_COMPANY", "Person emails/company", "int", 3, "Research", "Target person/work emails per company where the mode allows it.", min_value=1, max_value=10),
    SettingSpec("RESEARCH_WRITE_OUTPUT", "Write research CSV", "bool", True, "Research", "Writes generated leads into input/<mode>."),
    SettingSpec("RESEARCH_UPLOAD_ATTACHMENTS", "Upload research context", "bool", True, "Research", "Uploads CV/resume files and sent logs as provider context."),
    SettingSpec("SELF_SEARCH_KEYWORDS", "Self search keywords", "list", [
        "\"industry phd\" \"contact\" email Australia",
        "\"research partnership\" \"contact\" email Australia",
        "\"innovation\" \"university partnership\" email Australia",
    ], "Self Search", "One Google-style search query per line for the local crawler."),
    SettingSpec("SELF_SEARCH_PAGES", "Search pages/keyword", "int", 1, "Self Search", "Number of result pages scanned per keyword.", min_value=1, max_value=20),
    SettingSpec("SELF_RESULTS_PER_PAGE", "Results per page", "int", 10, "Self Search", "Expected search results per result page.", min_value=1, max_value=20),
    SettingSpec("SELF_CRAWL_MAX_PAGES_PER_SITE", "Max crawl pages/site", "int", 8, "Self Search", "Maximum same-site pages opened for one search result.", min_value=1, max_value=100),
    SettingSpec("SELF_CRAWL_DEPTH", "Crawl depth", "int", 2, "Self Search", "0 only opens the result page; 2-3 follows contact/about/team sublinks.", min_value=0, max_value=5),
    SettingSpec("SELF_REQUEST_TIMEOUT", "Request timeout", "float", 10.0, "Self Search", "HTTP timeout for local crawling and optional mailbox probes.", min_value=1, max_value=120),
    SettingSpec("SELF_VERIFY_EMAIL_SMTP", "Verify self emails via SMTP", "bool", False, "Self Search", "Optionally probes found addresses before accepting self-research leads."),
    SettingSpec("SEND", "Real email sending", "bool", False, "Mail", "Off means dry-run. On sends through SMTP."),
    SettingSpec("SEND_TARGET_COUNT", "Target new sends", "int", 0, "Mail", "Repeated research/send target. 0 disables the target loop.", min_value=0, max_value=2000),
    SettingSpec("SEND_TARGET_MAX_ROUNDS", "Max target rounds", "int", 0, "Mail", "Safety limit for repeated target loop. 0 means unlimited.", min_value=0, max_value=100),
    SettingSpec("PARALLEL_THREADS", "Parallel threads", "int", 7, "Mail", "Maximum parallel research requests and mail sender workers.", min_value=1, max_value=50),
    SettingSpec("VERIFY_EMAIL_SMTP", "Verify before send", "bool", False, "Mail", "Optional MX/SMTP recipient probe before real sending."),
    SettingSpec("VERIFY_EMAIL_SMTP_TIMEOUT", "Verify timeout", "float", 8.0, "Mail", "Timeout for recipient SMTP probe.", min_value=1, max_value=60),
    SettingSpec("RESEND_EXISTING", "Resend existing", "bool", False, "Mail", "Allows sending to addresses already present in output logs."),
    SettingSpec("ALLOW_EMPTY_ATTACHMENTS", "Allow empty attachments", "bool", False, "Mail", "Allows running a mode even when the attachment folder is empty."),
    SettingSpec("LOG_DRY_RUN", "Log dry-run", "bool", False, "Mail", "Writes dry-run recipients to sent logs."),
    SettingSpec("WRITE_SENT_LOG", "Write sent log", "bool", True, "Mail", "Writes successful real sends to output/send_*.csv."),
    SettingSpec("DELETE_INPUT_AFTER_SUCCESS", "Delete input after success", "bool", False, "Mail", "Deletes processed input CSV/TXT files after a successful send run."),
    SettingSpec("SIGNATURE_LOGO", "Signature logo", "str", "templates/signature-logo.png", "Mail", "Path to the inline signature image."),
    SettingSpec("SIGNATURE_LOGO_WIDTH", "Logo width", "int", 325, "Mail", "Inline signature logo width in pixels.", min_value=50, max_value=900),
    SettingSpec("VERBOSE", "Verbose output", "bool", False, "Logging", "Enables detailed [VERBOSE] lines."),
    SettingSpec("SAVE_VERBOSE_LOG", "Save run logs", "bool", True, "Logging", "Writes run output into timestamped files."),
    SettingSpec("VERBOSE_LOG_DIR", "Log directory", "str", "logs", "Logging", "Folder for saved run logs."),
    SettingSpec("SMTP_HOST", "SMTP host", "str", "smtp.hostinger.com", "SMTP", "SMTPS hostname."),
    SettingSpec("SMTP_PORT", "SMTP port", "int", 465, "SMTP", "SMTPS port.", min_value=1, max_value=65535, slider=False),
    SettingSpec("SMTP_ENCRYPTION", "SMTP encryption", "choice", "ssl", "SMTP", "Encryption mode.", ("ssl",)),
    SettingSpec("SMTP_FROM_NAME", "From name", "str", "Carina Sophie Schoppe", "SMTP", "Display name used as sender."),
    SettingSpec("SMTP_FROM_EMAIL", "From email", "str", "info@carinaschoppe.com", "SMTP", "Sender email address."),
)


ENV_SCHEMA: tuple[SettingSpec, ...] = (
    SettingSpec("SMTP_USERNAME", "SMTP username", "str", "", "SMTP Secrets", "Login username for SMTP. Keep this in .env."),
    SettingSpec("SMTP_PASSWORD", "SMTP password", "str", "", "SMTP Secrets", "Login password for SMTP. Keep this in .env."),
    SettingSpec("GEMINI_API_KEY", "Gemini API key", "str", "", "AI Secrets", "Gemini API key. Keep this in .env."),
    SettingSpec("OPENAI_API_KEY", "OpenAI API key", "str", "", "AI Secrets", "OpenAI API key. Keep this in .env."),
)


def schema_by_key() -> dict[str, SettingSpec]:
    return {spec.key: spec for spec in SETTINGS_SCHEMA}


def default_settings() -> dict[str, Any]:
    return {spec.key: spec.default for spec in SETTINGS_SCHEMA}


def default_env() -> dict[str, Any]:
    return {spec.key: spec.default for spec in ENV_SCHEMA}


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    values = default_settings()
    if path.exists():
        with path.open("rb") as handle:
            values.update(tomllib.load(handle))
    return values


def load_env(path: Path | None = None) -> dict[str, Any]:
    env_path = path or (PROJECT_ROOT / ".env")
    values = default_env()
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if key in values:
            values[key] = _unquote_env_value(raw_value.strip())
    return values


def coerce_value(spec: SettingSpec, value: Any) -> Any:
    if spec.kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if spec.kind == "int":
        return int(float(value or 0))
    if spec.kind == "float":
        return float(value or 0)
    if spec.kind == "list":
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        return list(value or [])
    return str(value)


def write_settings(path: Path, values: dict[str, Any], *, omit_defaults: bool = False) -> None:
    specs = SETTINGS_SCHEMA
    defaults = default_settings()
    lines = [
        "# MailSenderSystem settings.",
        "# Generated by the Tkinter GUI. Values that match defaults can be omitted by compact save.",
        "",
    ]
    current_section = ""
    for spec in specs:
        value = coerce_value(spec, values.get(spec.key, spec.default))
        if omit_defaults and value == defaults[spec.key]:
            continue
        if spec.section != current_section:
            current_section = spec.section
            lines.extend(["", f"# {current_section}", ""])
        lines.append(f"# {spec.label}: {spec.help_text}")
        lines.append(f"{spec.key} = {_format_toml_value(value)}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_env(path: Path, values: dict[str, Any]) -> None:
    lines = [
        "# MailSenderSystem .env",
        "# Generated by the Tkinter GUI. Keep secrets here, not in settings.toml.",
        "",
    ]
    current_section = ""
    for spec in ENV_SCHEMA:
        value = coerce_value(spec, values.get(spec.key, spec.default))
        if spec.section != current_section:
            current_section = spec.section
            lines.extend(["", f"# {current_section}", ""])
        lines.append(f"# {spec.label}: {spec.help_text}")
        lines.append(f"{spec.key}={_format_env_value(value)}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = ["["]
        lines.extend(f"  {_format_toml_value(item)}," for item in value)
        lines.append("]")
        return "\n".join(lines)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _format_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("\n", " ").strip()


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
