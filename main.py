import sys

from mail_sender.cli import main as mail_main
from research.research_leads import main as research_main

# Usually edit these settings.

# True = run AI research first and create a new lead CSV in input/<Mode>.
# False = start the mail sender only.
RUN_AI_RESEARCH = globals().get("RUN_AI_RESEARCH", True)

# Select the batch to run.
# Allowed: "PhD", "Freelance_German", "Freelance_English", or "Auto".
MODE = globals().get("MODE", "Freelance_German")

# AI research settings. Only used when RUN_AI_RESEARCH = True.
# Empty values use the defaults from .env / .env.example.
RESEARCH_AI_PROVIDER = globals().get("RESEARCH_AI_PROVIDER", "gemini")  # "gemini" or "openai"
RESEARCH_MIN_COMPANIES = globals().get("RESEARCH_MIN_COMPANIES", 25)
RESEARCH_MAX_COMPANIES = globals().get("RESEARCH_MAX_COMPANIES", 50)
RESEARCH_PERSON_EMAILS_PER_COMPANY = globals().get("RESEARCH_PERSON_EMAILS_PER_COMPANY", 2)
RESEARCH_WRITE_OUTPUT = globals().get("RESEARCH_WRITE_OUTPUT", True)
RESEARCH_UPLOAD_ATTACHMENTS = globals().get("RESEARCH_UPLOAD_ATTACHMENTS", True)

# Safety switch:
# False = dry run only, no real emails.
# True = send real emails via SMTP.
SEND = globals().get("SEND", False)

# Print detailed terminal output.
VERBOSE = globals().get("VERBOSE", False)

# Advanced mail settings.

# Default: skip addresses already present in send_phd.xlsx / send_freelance.xlsx.
# Only set this to True when you intentionally want to contact already logged addresses again.
RESEND_EXISTING = globals().get("RESEND_EXISTING", False)

# Default logo for the email signature. Place the logo there or adjust the path.
SIGNATURE_LOGO = globals().get("SIGNATURE_LOGO", "templates/signature-logo.png")
SIGNATURE_LOGO_WIDTH = globals().get("SIGNATURE_LOGO_WIDTH", 325)

# Only set this to True for tests without attachments. Keep it False for real emails.
ALLOW_EMPTY_ATTACHMENTS = globals().get("ALLOW_EMPTY_ATTACHMENTS", False)

# False = dry runs are not written to send_phd.xlsx / send_freelance.xlsx.
# True = dry runs are logged in Excel.
LOG_DRY_RUN = globals().get("LOG_DRY_RUN", False)

# True = write successfully sent emails to output/send_*.xlsx.
# False = do not write successful sends to Excel.
WRITE_SENT_LOG = globals().get("WRITE_SENT_LOG", True)

# True = delete processed .csv/.txt files from input/<Mode> after a successful real send run.
# False = keep input files after sending.
DELETE_INPUT_AFTER_SUCCESS = globals().get("DELETE_INPUT_AFTER_SUCCESS", False)


def _add_value(args: list[str], flag: str, value) -> None:
    if value is not None:
        args.extend([flag, str(value)])


def _add_flag(args: list[str], enabled: bool, flag: str) -> None:
    if enabled:
        args.append(flag)


def _info(message: str) -> None:
    print(f"[INFO] {message}")


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


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _info("CLI arguments detected; starting mail sender directly.")
        raise SystemExit(mail_main())

    if RUN_AI_RESEARCH:
        _info(f"Starting AI research for mode {MODE} with {RESEARCH_AI_PROVIDER}.")
        research_args = _build_research_args()
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
            sys.exit(0)
    else:
        _info("AI research disabled; starting mail sender only.")

    _info(f"Starting mail sender for mode {MODE}; sending is {'enabled' if SEND else 'disabled (dry-run)'}.")
    raise SystemExit(mail_main(_build_mail_args()))
