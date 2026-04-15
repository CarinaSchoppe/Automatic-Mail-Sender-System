"""Settings-driven entry point for research, sending, logging, and target loops."""

import sys
import tomllib
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from mail_sender.cli import main as mail_main
from mail_sender.sent_log import read_known_output_emails, read_logged_rows
from research.logging_utils import info as _info
from research.logging_utils import verbose as _verbose
from research.research_leads import main as research_main

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "settings.toml"


def _load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    with SETTINGS_PATH.open("rb") as handle:
        return tomllib.load(handle)


SETTINGS = _load_settings()


def _setting(name: str, default: Any) -> Any:
    return globals().get(name, SETTINGS.get(name, default))


RUN_AI_RESEARCH: bool = cast(bool, _setting("RUN_AI_RESEARCH", True))
MODE: str = cast(str, _setting("MODE", "Freelance_German"))
RESEARCH_AI_PROVIDER: str = cast(str, _setting("RESEARCH_AI_PROVIDER", "gemini"))
RESEARCH_MIN_COMPANIES: int = cast(int, _setting("RESEARCH_MIN_COMPANIES", 25))
RESEARCH_MAX_COMPANIES: int = cast(int, _setting("RESEARCH_MAX_COMPANIES", 50))
RESEARCH_PERSON_EMAILS_PER_COMPANY: int = cast(int, _setting("RESEARCH_PERSON_EMAILS_PER_COMPANY", 3))
RESEARCH_WRITE_OUTPUT: bool = cast(bool, _setting("RESEARCH_WRITE_OUTPUT", True))
RESEARCH_UPLOAD_ATTACHMENTS: bool = cast(bool, _setting("RESEARCH_UPLOAD_ATTACHMENTS", True))
GEMINI_MODEL: str = cast(str, _setting("GEMINI_MODEL", "gemini-3-flash-preview"))
OPENAI_MODEL: str = cast(str, _setting("OPENAI_MODEL", "gpt-5.4-mini-2026-03-17"))
OLLAMA_MODEL: str = cast(str, _setting("OLLAMA_MODEL", "llama3.1:8b"))
OLLAMA_BASE_URL: str = cast(str, _setting("OLLAMA_BASE_URL", "http://localhost:11434"))
RESEARCH_REASONING_EFFORT: str = cast(str, _setting("RESEARCH_REASONING_EFFORT", "middle"))
SELF_SEARCH_KEYWORDS: list[str] = cast(list[str], _setting("SELF_SEARCH_KEYWORDS", []))
SELF_SEARCH_PAGES: int = cast(int, _setting("SELF_SEARCH_PAGES", 1))
SELF_RESULTS_PER_PAGE: int = cast(int, _setting("SELF_RESULTS_PER_PAGE", 10))
SELF_CRAWL_MAX_PAGES_PER_SITE: int = cast(int, _setting("SELF_CRAWL_MAX_PAGES_PER_SITE", 8))
SELF_CRAWL_DEPTH: int = cast(int, _setting("SELF_CRAWL_DEPTH", 2))
SELF_REQUEST_TIMEOUT: int = cast(int, _setting("SELF_REQUEST_TIMEOUT", 10))
SELF_VERIFY_EMAIL_SMTP: bool = cast(bool, _setting("SELF_VERIFY_EMAIL_SMTP", False))
SEND: bool = cast(bool, _setting("SEND", False))
SEND_TARGET_COUNT: int = cast(int, _setting("SEND_TARGET_COUNT", 0))
SEND_TARGET_MAX_ROUNDS: int = cast(int, _setting("SEND_TARGET_MAX_ROUNDS", 0))
PARALLEL_THREADS: int = cast(int, _setting("PARALLEL_THREADS", 5))
VERIFY_EMAIL_SMTP: bool = cast(bool, _setting("VERIFY_EMAIL_SMTP", False))
VERIFY_EMAIL_SMTP_TIMEOUT: int = cast(int, _setting("VERIFY_EMAIL_SMTP_TIMEOUT", 8))
VERBOSE: bool = cast(bool, _setting("VERBOSE", False))
SAVE_VERBOSE_LOG: bool = cast(bool, _setting("SAVE_VERBOSE_LOG", True))
VERBOSE_LOG_DIR: str = cast(str, _setting("VERBOSE_LOG_DIR", "logs"))
RESEND_EXISTING: bool = cast(bool, _setting("RESEND_EXISTING", False))
SIGNATURE_LOGO: str = cast(str, _setting("SIGNATURE_LOGO", "templates/signature-logo.png"))
SIGNATURE_LOGO_WIDTH: int = cast(int, _setting("SIGNATURE_LOGO_WIDTH", 325))
ALLOW_EMPTY_ATTACHMENTS: bool = cast(bool, _setting("ALLOW_EMPTY_ATTACHMENTS", False))
LOG_DRY_RUN: bool = cast(bool, _setting("LOG_DRY_RUN", False))
WRITE_SENT_LOG: bool = cast(bool, _setting("WRITE_SENT_LOG", True))
DELETE_INPUT_AFTER_SUCCESS: bool = cast(bool, _setting("DELETE_INPUT_AFTER_SUCCESS", False))


def _add_value(args: list[str], flag: str, value) -> None:
    if value is not None:
        args.extend([flag, str(value)])


def _add_flag(args: list[str], enabled: bool, flag: str) -> None:
    if enabled:
        args.append(flag)


class _Tee:
    def __init__(self, *streams) -> None:
        self.streams = streams

    def write(self, data: str) -> int:
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def _resolve_log_dir() -> Path:
    path = Path(str(VERBOSE_LOG_DIR))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _create_log_file():
    if not SAVE_VERBOSE_LOG:
        return None

    log_dir = _resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_mode = str(MODE).lower().replace(" ", "_").replace("/", "_").replace("\\", "_")
    path = log_dir / f"run_{safe_mode}_{timestamp}.log"
    handle = path.open("w", encoding="utf-8")
    return path, handle


def _print_effective_settings() -> None:
    _info(f"Settings file: {SETTINGS_PATH if SETTINGS_PATH.exists() else 'not found; using built-in defaults'}.")
    _info(f"Mode: {MODE}. AI research: {'on' if RUN_AI_RESEARCH else 'off'}. Provider: {RESEARCH_AI_PROVIDER}. Reasoning: {RESEARCH_REASONING_EFFORT}.")
    _info(f"Mail sending: {'real send enabled' if SEND else 'dry-run / no mail send unless research is disabled'}.")
    _info(f"Send target: {SEND_TARGET_COUNT if SEND_TARGET_COUNT else 'disabled'}.")
    _info(f"Parallel threads: {PARALLEL_THREADS}.")
    _info(f"SMTP mailbox verification: {'enabled' if VERIFY_EMAIL_SMTP else 'disabled'}.")
    _info(f"Output: research CSV {'enabled' if RESEARCH_WRITE_OUTPUT else 'disabled'}, CV/resume upload {'enabled' if RESEARCH_UPLOAD_ATTACHMENTS else 'disabled'}.")
    _info(f"Log file saving: {'enabled' if SAVE_VERBOSE_LOG else 'disabled'}.")
    _verbose(VERBOSE, f"Effective research target: {RESEARCH_MIN_COMPANIES}-{RESEARCH_MAX_COMPANIES} companies, person emails per company={RESEARCH_PERSON_EMAILS_PER_COMPANY}.")
    _verbose(VERBOSE, f"Ollama settings: model={OLLAMA_MODEL}, base_url={OLLAMA_BASE_URL}.")
    _verbose(VERBOSE, f"Self research settings: pages={SELF_SEARCH_PAGES}, results_per_page={SELF_RESULTS_PER_PAGE}, crawl_max_pages_per_site={SELF_CRAWL_MAX_PAGES_PER_SITE}, crawl_depth={SELF_CRAWL_DEPTH}, keywords={SELF_SEARCH_KEYWORDS}.")
    _verbose(VERBOSE, f"Advanced mail settings: resend_existing={RESEND_EXISTING}, allow_empty_attachments={ALLOW_EMPTY_ATTACHMENTS}, log_dry_run={LOG_DRY_RUN}, write_sent_log={WRITE_SENT_LOG}, delete_input_after_success={DELETE_INPUT_AFTER_SUCCESS}.")
    _verbose(VERBOSE, f"Target loop max rounds (safety gate): {SEND_TARGET_MAX_ROUNDS if SEND_TARGET_MAX_ROUNDS else 'unlimited (0)'}.")
    _verbose(VERBOSE, f"Signature logo: {SIGNATURE_LOGO}, width={SIGNATURE_LOGO_WIDTH}.")
    _verbose(VERBOSE, f"Verbose log directory: {_resolve_log_dir()}.")


def _build_research_args() -> list[str]:
    args = [
        "--provider",
        str(RESEARCH_AI_PROVIDER),
        "--mode",
        str(MODE),
        "--base-dir",
        str(PROJECT_ROOT),
        "--gemini-model",
        str(GEMINI_MODEL),
        "--openai-model",
        str(OPENAI_MODEL),
        "--ollama-model",
        str(OLLAMA_MODEL),
        "--ollama-base-url",
        str(OLLAMA_BASE_URL),
        "--reasoning-effort",
        str(RESEARCH_REASONING_EFFORT),
    ]
    for flag, value in [
        ("--min-companies", RESEARCH_MIN_COMPANIES),
        ("--max-companies", RESEARCH_MAX_COMPANIES),
        ("--person-emails-per-company", RESEARCH_PERSON_EMAILS_PER_COMPANY),
        ("--self-search-pages", SELF_SEARCH_PAGES),
        ("--self-results-per-page", SELF_RESULTS_PER_PAGE),
        ("--self-crawl-max-pages-per-site", SELF_CRAWL_MAX_PAGES_PER_SITE),
        ("--self-crawl-depth", SELF_CRAWL_DEPTH),
        ("--self-request-timeout", SELF_REQUEST_TIMEOUT),
    ]:
        _add_value(args, flag, value)
    for keyword in SELF_SEARCH_KEYWORDS:
        _add_value(args, "--self-search-keyword", keyword)
    for flag, enabled in [
        ("--no-write-output", not RESEARCH_WRITE_OUTPUT),
        ("--no-upload-attachments", not RESEARCH_UPLOAD_ATTACHMENTS),
        ("--self-verify-email-smtp", SELF_VERIFY_EMAIL_SMTP),
        ("--verbose", VERBOSE),
    ]:
        _add_flag(args, enabled, flag)
    _add_value(args, "--send-target-count", SEND_TARGET_COUNT)
    _add_value(args, "--max-iterations", SEND_TARGET_MAX_ROUNDS)
    _add_value(args, "--parallel-threads", PARALLEL_THREADS)
    return args


def _build_mail_args(max_send_count: int | None = None) -> list[str]:
    args = [
        "--mode",
        MODE,
        "--base-dir",
        str(PROJECT_ROOT),
        "--signature-logo",
        SIGNATURE_LOGO,
        "--signature-logo-width",
        str(SIGNATURE_LOGO_WIDTH),
    ]
    for flag, enabled in [
        ("--send", SEND),
        ("--verbose", VERBOSE),
        ("--resend-existing", RESEND_EXISTING),
        ("--allow-empty-attachments", ALLOW_EMPTY_ATTACHMENTS),
        ("--log-dry-run", LOG_DRY_RUN),
        ("--no-write-sent-log", not WRITE_SENT_LOG),
        ("--delete-input-after-success", DELETE_INPUT_AFTER_SUCCESS),
        ("--verify-email-smtp", VERIFY_EMAIL_SMTP),
    ]:
        _add_flag(args, enabled, flag)
    _add_value(args, "--max-send-count", max_send_count)
    _add_value(args, "--parallel-threads", PARALLEL_THREADS)
    _add_value(args, "--verify-email-smtp-timeout", VERIFY_EMAIL_SMTP_TIMEOUT)
    return args


def _target_send_enabled() -> bool:
    return int(SEND_TARGET_COUNT) > 0


def _count_logged_sent_emails() -> int:
    return len(read_known_output_emails(PROJECT_ROOT / "output"))


def _get_logged_emails() -> set[str]:
    return read_known_output_emails(PROJECT_ROOT / "output")


def _read_output_sent_rows() -> list[dict[str, str]]:
    output_dir = PROJECT_ROOT / "output"
    rows: list[dict[str, str]] = []
    if not output_dir.exists():
        return rows
    for path in output_dir.glob("*.csv"):
        if path.name.lower() != "invalid_mails.csv":
            rows.extend(read_logged_rows(path))
    return rows


def _print_run_summary(sent_details: list[dict[str, str]]) -> None:
    if not sent_details:
        return

    # Filter to unique emails just in case, though the logic should handle it
    unique_emails = {d["mail"].lower() for d in sent_details}

    print("\n" + "=" * 60)
    print(f"Summary: {len(unique_emails)} unique email(s) sent to these recipients:")

    # Sort by company
    sorted_details = sorted(sent_details, key=lambda x: (x.get("company") or "").lower())
    for detail in sorted_details:
        mail = detail.get("mail") or ""
        company = detail.get("company")
        if not company and mail and "@" in mail:
            parts = mail.split("@")
            if len(parts) > 1:
                company = parts[1].split(".")[0]
        company = company or "(No Company)"
        print(f"- {company}: {mail}")
    print("=" * 60 + "\n")


def _validate_target_send_settings() -> bool:
    """Validate the only configuration combination that can safely run target sending."""
    if not _target_send_enabled():
        return True

    problems = []
    if not RUN_AI_RESEARCH:
        problems.append("RUN_AI_RESEARCH must be true")
    if not SEND:
        problems.append("SEND must be true")
    if not RESEARCH_WRITE_OUTPUT:
        problems.append("RESEARCH_WRITE_OUTPUT must be true")
    if not WRITE_SENT_LOG:
        problems.append("WRITE_SENT_LOG must be true")
    if RESEND_EXISTING:
        problems.append("RESEND_EXISTING must be false")
    if str(MODE).strip().lower() == "auto":
        problems.append('MODE must be a concrete mode, not "Auto"')

    if problems:
        print("Error: SEND_TARGET_COUNT can only run when " + ", ".join(problems) + ".")
        return False
    return True


def _run_research_once(round_number: int | None = None) -> int:
    label = f" round {round_number}" if round_number is not None else ""
    _info(f"Starting AI research{label} for mode {MODE} with {RESEARCH_AI_PROVIDER}.")
    research_args = _build_research_args()
    _verbose(VERBOSE, f"Research CLI args: {research_args}.")
    research_status = research_main(research_args)
    if research_status != 0:
        _info("AI research failed; stopping before mail sender.")
    return research_status


def _run_mail_once(max_send_count: int | None = None) -> int:
    _info(f"Starting mail sender for mode {MODE}; sending is {'enabled' if SEND else 'disabled (dry-run)'}.")
    mail_args = _build_mail_args(max_send_count=max_send_count)
    _verbose(VERBOSE, f"Mail CLI args: {mail_args}.")
    return mail_main(mail_args)


def _run_target_send_loop() -> int:
    """Repeat research and capped sending until the configured sent-log target is reached."""
    if not _validate_target_send_settings():
        return 1

    target_count = int(SEND_TARGET_COUNT)
    max_rounds = int(SEND_TARGET_MAX_ROUNDS)

    # We track unique emails sent in this run to reach the target_count increment.
    start_emails = _get_logged_emails()
    start_count = len(start_emails)
    target_total = start_count + target_count

    current_count = start_count
    round_number = 0

    # Details for the final summary (list of dicts with company/mail)
    run_sent_details: list[dict[str, str]] = []
    # Set of emails already added to run_sent_details to avoid duplicates in summary
    run_sent_emails_set: set[str] = set()

    _info(f"Target send loop enabled: send and log {target_count} new email(s).")
    _info(f"Logged sent emails at start: {start_count}. Target logged total: {target_total}.")

    if max_rounds > 0:
        _info(f"Safety gate active: Maximum of {max_rounds} round(s) allowed.")
    else:
        _info("Safety gate: Unlimited rounds (0) until target is reached.")
        if target_count >= 100:
            _info("Note: With a high target count and unlimited rounds, this process might take significant time and AI credits.")

    while current_count < target_total:
        round_number += 1
        if max_rounds and round_number > max_rounds:
            _info(f"Stopping before target because SEND_TARGET_MAX_ROUNDS={max_rounds} was reached.")
            _print_run_summary(run_sent_details)
            return 1

        remaining = target_total - current_count
        _info(f"Target loop round {round_number}: {remaining} unique email(s) still needed.")

        research_status = _run_research_once(round_number)
        if research_status != 0:
            _print_run_summary(run_sent_details)
            return research_status

        print("\n" + "=" * 50)
        print(f"AI Research round {round_number} finished. Now sending up to {remaining} email(s)...")
        print("=" * 50 + "\n")

        # Track what was in the logs before this round
        # We need the full rows to get company names for the summary
        rows_before = _read_output_sent_rows()
        emails_before = {r["mail"].lower() for r in rows_before if r.get("mail")}

        mail_status = _run_mail_once(max_send_count=remaining)

        rows_after = _read_output_sent_rows()
        current_emails = {r["mail"].lower() for r in rows_after if r.get("mail")}
        current_count = len(current_emails)

        # Identify newly logged emails in this round
        for row in rows_after:
            email = row.get("mail", "").lower()
            if email and email not in emails_before and email not in run_sent_emails_set:
                run_sent_details.append(row)
                run_sent_emails_set.add(email)

        sent_this_run = current_count - start_count
        _info(f"Target loop round {round_number} finished. Total new unique emails this run: {sent_this_run}/{target_count}.")

        if mail_status != 0:
            _info("Mail sender returned an error; stopping target loop.")
            _print_run_summary(run_sent_details)
            return mail_status

        if sent_this_run >= target_count:
            break

        # Check if we made progress
        if len(current_emails - emails_before) <= 0:
            _info("No new unique sent-log entries were created in this round; stopping to avoid an endless loop.")
            _print_run_summary(run_sent_details)
            return 1

    _info(f"Target reached: {current_count - start_count}/{target_count} new unique email(s) logged.")
    _print_run_summary(run_sent_details)
    return 0


def _run() -> int:
    if len(sys.argv) > 1:
        _info("CLI arguments detected; starting mail sender directly.")
        _verbose(VERBOSE, f"Forwarded raw CLI args to mail sender: {sys.argv[1:]}.")
        return mail_main()

    _print_effective_settings()

    if _target_send_enabled():
        return _run_target_send_loop()

    # Track unique emails for non-target run too
    rows_before = _read_output_sent_rows()
    emails_before = {r["mail"].lower() for r in rows_before if r.get("mail")}

    if RUN_AI_RESEARCH:
        research_status = _run_research_once()
        if research_status != 0:
            sys.exit(research_status)

        if SEND:
            print("\n" + "=" * 50)
            print("AI Research finished. Now starting mail sender process...")
            print("=" * 50 + "\n")
        else:
            print("\n" + "=" * 50)
            print("AI Research finished. Skipping mail sender process.")
            return 0
    else:
        _info("AI research disabled; starting mail sender only.")

    mail_status = _run_mail_once()

    # Identify newly logged emails
    rows_after = _read_output_sent_rows()

    run_sent_details = []
    seen_in_run = set()
    for row in rows_after:
        email = row.get("mail", "").lower()
        if email and email not in emails_before and email not in seen_in_run:
            run_sent_details.append(row)
            seen_in_run.add(email)

    _print_run_summary(run_sent_details)
    return mail_status


def _run_with_optional_log() -> int:
    log_file = _create_log_file()
    if log_file is None:
        return _run()

    log_path, handle = log_file
    try:
        with handle:
            stdout = _Tee(sys.stdout, handle)
            stderr = _Tee(sys.stderr, handle)
            with redirect_stdout(stdout), redirect_stderr(stderr):
                _info(f"Saving terminal log to {log_path}.")
                _verbose(VERBOSE, "Log file capture is active. Console output is mirrored to disk.")
                status = _run()
                _info(f"Run finished with status {status}. Log saved to {log_path}.")
                return status
    except Exception:
        handle.close()
        raise


if __name__ == "__main__":
    raise SystemExit(_run_with_optional_log())
