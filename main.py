import sys

from mail_sender.cli import main


# Stelle hier ein, welchen Batch du starten willst.
# Erlaubt: "PhD", "Freelance_German", "Freelance_English" oder "Auto"
MODE = "PhD"

# Sicherheits-Schalter:
# False = nur Probelauf, keine echten Mails
# True = echte Mails per SMTP senden
SEND = True

# Viele Ausgaben im Terminal.
VERBOSE = True

# Standard: vorhandene Adressen in send_phd.xlsx / send_freelance.xlsx werden geskippt.
# Nur auf True setzen, wenn du bewusst erneut an bereits geloggte Adressen senden willst.
RESEND_EXISTING = False

# Standardlogo fuer die Signatur. Lege dein Logo dort ab oder passe den Pfad an.
SIGNATURE_LOGO = "templates/signature-logo.png"
SIGNATURE_LOGO_WIDTH = 325

# Nur fuer Tests ohne Anhaenge auf True setzen. Fuer echte Mails besser False lassen.
ALLOW_EMPTY_ATTACHMENTS = False

# False = Probelauf schreibt nicht in send_phd.xlsx / send_freelance.xlsx
# True = Probelauf wird in Excel protokolliert
LOG_DRY_RUN = False

# True = erfolgreich gesendete Mails in output/send_*.xlsx eintragen
# False = erfolgreiche Sendungen nicht in Excel eintragen
WRITE_SENT_LOG = True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(main())

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

    raise SystemExit(main(args))
