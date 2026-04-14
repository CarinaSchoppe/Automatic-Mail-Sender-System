import sys

from mail_sender.cli import main as mail_main
from research.research_leads import main as research_main

# True = run AI research first and create a new lead CSV in input/<Mode>.
# False = start the mail sender only.
RUN_AI_RESEARCH = globals().get("RUN_AI_RESEARCH", True)

# Select the batch to run.
# Allowed: "PhD", "Freelance_German", "Freelance_English", or "Auto".
MODE = globals().get("MODE", "Freelance_German")

# AI research settings. Only used when RUN_AI_RESEARCH = True.
# Empty values use the defaults from .env / .env.example.
RESEARCH_AI_PROVIDER = globals().get("RESEARCH_AI_PROVIDER", "openai")  # "gemini" or "openai"
RESEARCH_MODEL = globals().get("RESEARCH_MODEL", "")
RESEARCH_MIN_COMPANIES = globals().get("RESEARCH_MIN_COMPANIES", 15)
RESEARCH_MAX_COMPANIES = globals().get("RESEARCH_MAX_COMPANIES", 50)
RESEARCH_PERSON_EMAILS_PER_COMPANY = globals().get("RESEARCH_PERSON_EMAILS_PER_COMPANY", 2)
RESEARCH_WRITE_OUTPUT = globals().get("RESEARCH_WRITE_OUTPUT", True)
RESEARCH_UPLOAD_ATTACHMENTS = globals().get("RESEARCH_UPLOAD_ATTACHMENTS", True)

# Safety switch:
# False = dry run only, no real emails.
# True = send real emails via SMTP.
SEND = globals().get("SEND", False)

# Print detailed terminal output.
VERBOSE = globals().get("VERBOSE", True)

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

if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(mail_main())

    if RUN_AI_RESEARCH:
        research_args = [
            "--provider",
            RESEARCH_AI_PROVIDER,
            "--mode",
            MODE,
        ]
        if RESEARCH_MODEL:
            research_args.extend(["--model", RESEARCH_MODEL])
        if RESEARCH_MIN_COMPANIES is not None:
            research_args.extend(["--min-companies", str(RESEARCH_MIN_COMPANIES)])
        if RESEARCH_MAX_COMPANIES is not None:
            research_args.extend(["--max-companies", str(RESEARCH_MAX_COMPANIES)])
        if RESEARCH_PERSON_EMAILS_PER_COMPANY is not None:
            research_args.extend(["--person-emails-per-company", str(RESEARCH_PERSON_EMAILS_PER_COMPANY)])
        if not RESEARCH_WRITE_OUTPUT:
            research_args.append("--no-write-output")
        if not RESEARCH_UPLOAD_ATTACHMENTS:
            research_args.append("--no-upload-attachments")
        if VERBOSE:
            research_args.append("--verbose")

        research_status = research_main(research_args)
        if research_status != 0:
            sys.exit(research_status)

        print("\n" + "=" * 50)
        print("AI Research finished. Now starting mail sender process...")
        print("=" * 50 + "\n")

    args = [
        "--mode",
        MODE,
        "--signature-logo",
        SIGNATURE_LOGO,
        "--signature-logo-width",
        str(SIGNATURE_LOGO_WIDTH),
    ]

    if SEND:
        args.append("--send")
    if VERBOSE:
        args.append("--verbose")
    if RESEND_EXISTING:
        args.append("--resend-existing")
    if ALLOW_EMPTY_ATTACHMENTS:
        args.append("--allow-empty-attachments")
    if LOG_DRY_RUN:
        args.append("--log-dry-run")
    if not WRITE_SENT_LOG:
        args.append("--no-write-sent-log")
    if DELETE_INPUT_AFTER_SUCCESS:
        args.append("--delete-input-after-success")

    raise SystemExit(mail_main(args))
