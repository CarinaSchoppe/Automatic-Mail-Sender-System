import sys
import tomllib
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

from mail_sender.cli import main as mail_main
from research.research_leads import main as research_main

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "settings.toml"


def _load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    with SETTINGS_PATH.open("rb") as handle:
        return tomllib.load(handle)


SETTINGS = _load_settings()


def _setting(name: str, default):
    return globals().get(name, SETTINGS.get(name, default))


RUN_AI_RESEARCH = _setting("RUN_AI_RESEARCH", True)
MODE = _setting("MODE", "Freelance_German")
RESEARCH_AI_PROVIDER = _setting("RESEARCH_AI_PROVIDER", "gemini")
RESEARCH_MIN_COMPANIES = _setting("RESEARCH_MIN_COMPANIES", 25)
RESEARCH_MAX_COMPANIES = _setting("RESEARCH_MAX_COMPANIES", 50)
RESEARCH_PERSON_EMAILS_PER_COMPANY = _setting("RESEARCH_PERSON_EMAILS_PER_COMPANY", 3)
RESEARCH_WRITE_OUTPUT = _setting("RESEARCH_WRITE_OUTPUT", True)
RESEARCH_UPLOAD_ATTACHMENTS = _setting("RESEARCH_UPLOAD_ATTACHMENTS", True)
SEND = _setting("SEND", False)
VERBOSE = _setting("VERBOSE", False)
SAVE_VERBOSE_LOG = _setting("SAVE_VERBOSE_LOG", True)
VERBOSE_LOG_DIR = _setting("VERBOSE_LOG_DIR", "logs")
RESEND_EXISTING = _setting("RESEND_EXISTING", False)
SIGNATURE_LOGO = _setting("SIGNATURE_LOGO", "templates/signature-logo.png")
SIGNATURE_LOGO_WIDTH = _setting("SIGNATURE_LOGO_WIDTH", 325)
ALLOW_EMPTY_ATTACHMENTS = _setting("ALLOW_EMPTY_ATTACHMENTS", False)
LOG_DRY_RUN = _setting("LOG_DRY_RUN", False)
WRITE_SENT_LOG = _setting("WRITE_SENT_LOG", True)
DELETE_INPUT_AFTER_SUCCESS = _setting("DELETE_INPUT_AFTER_SUCCESS", False)


def _add_value(args: list[str], flag: str, value) -> None:
    if value is not None:
        args.extend([flag, str(value)])


def _add_flag(args: list[str], enabled: bool, flag: str) -> None:
    if enabled:
        args.append(flag)


def _info(message: str) -> None:
    print(f"[INFO] {message}")


def _verbose(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[VERBOSE] {message}")


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
    _info(f"Mode: {MODE}. AI research: {'on' if RUN_AI_RESEARCH else 'off'}. Provider: {RESEARCH_AI_PROVIDER}.")
    _info(f"Mail sending: {'real send enabled' if SEND else 'dry-run / no mail send unless research is disabled'}.")
    _info(f"Output: research CSV {'enabled' if RESEARCH_WRITE_OUTPUT else 'disabled'}, CV/resume upload {'enabled' if RESEARCH_UPLOAD_ATTACHMENTS else 'disabled'}.")
    _info(f"Log file saving: {'enabled' if SAVE_VERBOSE_LOG else 'disabled'}.")
    _verbose(VERBOSE, f"Effective research target: {RESEARCH_MIN_COMPANIES}-{RESEARCH_MAX_COMPANIES} companies, person emails per company={RESEARCH_PERSON_EMAILS_PER_COMPANY}.")
    _verbose(VERBOSE, f"Advanced mail settings: resend_existing={RESEND_EXISTING}, allow_empty_attachments={ALLOW_EMPTY_ATTACHMENTS}, log_dry_run={LOG_DRY_RUN}, write_sent_log={WRITE_SENT_LOG}, delete_input_after_success={DELETE_INPUT_AFTER_SUCCESS}.")
    _verbose(VERBOSE, f"Signature logo: {SIGNATURE_LOGO}, width={SIGNATURE_LOGO_WIDTH}.")
    _verbose(VERBOSE, f"Verbose log directory: {_resolve_log_dir()}.")


def _build_research_args() -> list[str]:
    args = ["--provider", RESEARCH_AI_PROVIDER, "--mode", MODE]
    for flag, value in [
        ("--min-companies", RESEARCH_MIN_COMPANIES),
        ("--max-companies", RESEARCH_MAX_COMPANIES),
        ("--person-emails-per-company", RESEARCH_PERSON_EMAILS_PER_COMPANY),
    ]:
        _add_value(args, flag, value)
    for flag, enabled in [
        ("--no-write-output", not RESEARCH_WRITE_OUTPUT),
        ("--no-upload-attachments", not RESEARCH_UPLOAD_ATTACHMENTS),
        ("--verbose", VERBOSE),
    ]:
        _add_flag(args, enabled, flag)
    return args


def _build_mail_args() -> list[str]:
    args = [
        "--mode",
        MODE,
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
    ]:
        _add_flag(args, enabled, flag)
    return args


def _run() -> int:
    if len(sys.argv) > 1:
        _info("CLI arguments detected; starting mail sender directly.")
        _verbose(VERBOSE, f"Forwarded raw CLI args to mail sender: {sys.argv[1:]}.")
        return mail_main()

    _print_effective_settings()

    if RUN_AI_RESEARCH:
        _info(f"Starting AI research for mode {MODE} with {RESEARCH_AI_PROVIDER}.")
        research_args = _build_research_args()
        _verbose(VERBOSE, f"Research CLI args: {research_args}.")
        research_status = research_main(research_args)
        if research_status != 0:
            _info("AI research failed; stopping before mail sender.")
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

    _info(f"Starting mail sender for mode {MODE}; sending is {'enabled' if SEND else 'disabled (dry-run)'}.")
    mail_args = _build_mail_args()
    _verbose(VERBOSE, f"Mail CLI args: {mail_args}.")
    return mail_main(mail_args)


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
