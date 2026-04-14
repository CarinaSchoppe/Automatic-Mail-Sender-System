import sys

from Research.research_leads import main as research_main
from mail_sender.cli import main as mail_main


# True = AI Research starten und neue Lead-CSV in input/<Mode> erzeugen
# False = Mail-Sender starten
RUN_AI_RESEARCH = globals().get("RUN_AI_RESEARCH", True)


# Stelle hier ein, welchen Batch du starten willst.
# Erlaubt: "PhD", "Freelance_German", "Freelance_English" oder "Auto"
MODE = globals().get("MODE", "PhD")

# AI Research Settings, nur relevant wenn RUN_AI_RESEARCH = True ist.
# Leere Werte nehmen die Defaults aus .env / .env.example.
RESEARCH_MODEL = globals().get("RESEARCH_MODEL", "")
RESEARCH_MIN_COMPANIES = globals().get("RESEARCH_MIN_COMPANIES", None)
RESEARCH_MAX_COMPANIES = globals().get("RESEARCH_MAX_COMPANIES", None)
RESEARCH_PERSON_EMAILS_PER_COMPANY = globals().get("RESEARCH_PERSON_EMAILS_PER_COMPANY", None)
RESEARCH_WRITE_OUTPUT = globals().get("RESEARCH_WRITE_OUTPUT", True)

# Sicherheits-Schalter:
# False = nur Probelauf, keine echten Mails
# True = echte Mails per SMTP senden
SEND = globals().get("SEND", False)

# Viele Ausgaben im Terminal.
VERBOSE = globals().get("VERBOSE", True)

# Standard: vorhandene Adressen in send_phd.xlsx / send_freelance.xlsx werden geskippt.
# Nur auf True setzen, wenn du bewusst erneut an bereits geloggte Adressen senden willst.
RESEND_EXISTING = globals().get("RESEND_EXISTING", False)

# Standardlogo fuer die Signatur. Lege dein Logo dort ab oder passe den Pfad an.
SIGNATURE_LOGO = globals().get("SIGNATURE_LOGO", "templates/signature-logo.png")
SIGNATURE_LOGO_WIDTH = globals().get("SIGNATURE_LOGO_WIDTH", 325)

# Nur fuer Tests ohne Anhaenge auf True setzen. Fuer echte Mails besser False lassen.
ALLOW_EMPTY_ATTACHMENTS = globals().get("ALLOW_EMPTY_ATTACHMENTS", False)

# False = Probelauf schreibt nicht in send_phd.xlsx / send_freelance.xlsx
# True = Probelauf wird in Excel protokolliert
LOG_DRY_RUN = globals().get("LOG_DRY_RUN", False)

# True = erfolgreich gesendete Mails in output/send_*.xlsx eintragen
# False = erfolgreiche Sendungen nicht in Excel eintragen
WRITE_SENT_LOG = globals().get("WRITE_SENT_LOG", False)

# True = nach erfolgreichem echtem Versand die verarbeiteten .csv/.txt Dateien aus input/<Mode> loeschen
# False = Input-Dateien nach dem Versand liegen lassen
DELETE_INPUT_AFTER_SUCCESS = globals().get("DELETE_INPUT_AFTER_SUCCESS", True)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(mail_main())

    if RUN_AI_RESEARCH:
        research_args = [
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

        raise SystemExit(research_main(research_args))

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
