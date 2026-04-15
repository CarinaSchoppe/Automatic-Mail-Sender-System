"""
Kommandozeilen-Schnittstelle für den E-Mail-Versand.
Verarbeitet Empfängerlisten, validiert E-Mails, rendert Vorlagen und versendet Nachrichten über SMTP.
Unterstützt Dry-Runs, parallele Verarbeitung und detaillierte Protokollierung.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mail_sender.attachments import list_attachments
from mail_sender.config import ConfigError, load_smtp_config
from mail_sender.email_validation import validate_email_address
from mail_sender.modes import MODE_NAMES
from mail_sender.modes import get_mode
from mail_sender.recipients import list_recipient_files, read_recipients_from_dir
from mail_sender.sent_log import append_invalid_email, append_log, read_invalid_emails, read_known_output_emails
from mail_sender.smtp_sender import SmtpMailer
from mail_sender.templates import render_mail


def _verbose(enabled: bool, message: str) -> None:
    """Gibt eine Verbose-Meldung aus, wenn Verbose aktiv ist."""
    if enabled:
        print(f"[VERBOSE] {message}")


def _info(message: str) -> None:
    """Gibt eine normale Info-Meldung aus."""
    print(f"[INFO] {message}")


def main(argv: list[str] | None = None) -> int:
    """
    Hauptfunktion des Mail-Senders. Parst Argumente und startet den Versandprozess für die gewählten Modi.

    Args:
        argv (list[str] | None): Liste der Kommandozeilenargumente.

    Returns:
        int: Exit-Code (0 für Erfolg, 1 bei Fehlern).
    """
    parser = argparse.ArgumentParser(description="Send PhD or Freelance mail batches via SMTPS.")
    parser.add_argument("--mode", required=True, choices=["Auto", "auto", "PhD", "phd", "Freelance_German", "freelance_german", "Freelance_English", "freelance_english"], help="Mail mode.")
    parser.add_argument("--base-dir", default=".", help="Project base directory.")
    parser.add_argument("--send", action="store_true", help="Actually send the emails. Without this flag, dry-run only.")
    parser.add_argument("--log-dry-run", action="store_true", help="Write dry-run rows to the CSV log. Off by default.")
    parser.add_argument("--no-write-sent-log", action="store_true", help="Do not write successfully sent emails to the CSV log.")
    parser.add_argument("--delete-input-after-success", action="store_true", help="Delete processed .csv/.txt input files after a successful real send run.")
    parser.add_argument("--resend-existing", action="store_true", help="Ignore addresses already present in the mode CSV log.")
    parser.add_argument(
        "--skip-invalid-check",
        action="store_true",
        default=True,
        help="Do not read invalid_mails.csv before sending; recipients listed there can be sent again.",
    )
    parser.add_argument(
        "--no-skip-invalid-check",
        action="store_false",
        dest="skip_invalid_check",
        help="Read invalid_mails.csv and skip recipients already listed there.",
    )
    parser.add_argument("--allow-empty-attachments", action="store_true", help="Allow sending even if the mode attachment folder is empty.")
    parser.add_argument("--subject", help="Optional subject override. Supports template placeholders like {company}.")
    parser.add_argument("--signature-logo", default="templates/signature-logo.png", help="Inline logo image used when the signature contains {IMAGE}.")
    parser.add_argument("--signature-logo-width", type=int, default=180, help="Width of the inline signature logo in pixels.")
    parser.add_argument("--max-send-count", type=int, help="Maximum number of filtered recipients to process in this run.")
    parser.add_argument("--parallel-threads", type=int, default=1, help="Maximum number of recipients to render/send in parallel.")
    parser.add_argument("--verify-email-smtp", action="store_true", help="Probe recipient MX servers for definitive mailbox rejects before sending.")
    parser.add_argument("--skip-email-dns-check", action="store_true", help="Skip DNS/MX record verification during email validation.")
    parser.add_argument("--verify-email-smtp-timeout", type=float, default=8.0, help="Timeout in seconds for optional SMTP mailbox probes.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed pipeline logging.")
    args = parser.parse_args(argv)

    base_dir = Path(args.base_dir).resolve()
    signature_path = base_dir / "templates" / "signature.txt"
    signature_logo_path = (base_dir / args.signature_logo).resolve() if not Path(args.signature_logo).is_absolute() else Path(args.signature_logo)

    try:
        if args.max_send_count is not None and args.max_send_count < 1:
            raise ValueError("--max-send-count must be at least 1.")
        if args.parallel_threads < 1:
            raise ValueError("--parallel-threads must be at least 1.")
        if args.verify_email_smtp_timeout <= 0:
            raise ValueError("--verify-email-smtp-timeout must be greater than 0.")

        _info(f"Starting mail pipeline in mode {args.mode}.")
        _verbose(args.verbose, f"Parsed CLI args: {args}")
        modes = _select_modes(args.mode, base_dir)
        if not modes:
            print("No input files found in input/PhD, input/Freelance_German, or input/Freelance_English.")
            return 0

        _info(f"Selected {len(modes)} mode(s): {', '.join(mode.label for mode in modes)}.")
        total_errors = 0
        for mode in modes:
            total_errors += _run_mode(args, mode, base_dir, signature_path, signature_logo_path)

        if total_errors:
            print(f"Finished with {total_errors} total error(s).")
            return 1

        print("Finished successfully.")
        return 0
    except (ConfigError, FileNotFoundError, NotADirectoryError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1


def _select_modes(mode_name: str, base_dir: Path):
    """
    Wählt basierend auf dem Modus-Namen die entsprechenden Mail-Modi aus.
    Bei "Auto" werden alle Modi mit vorhandenen Input-Dateien gewählt.
    """
    normalized = mode_name.strip().lower()
    if normalized != "auto":
        return [get_mode(mode_name, base_dir)]

    modes = [get_mode(name, base_dir) for name in MODE_NAMES]
    return [mode for mode in modes if list_recipient_files(mode.recipients_dir)]


def _run_mode(args, mode, base_dir: Path, signature_path: Path, signature_logo_path: Path) -> int:
    """
    Führt den Versandprozess für einen spezifischen Modus (z.B. PhD) aus.

    Args:
        args: Die parsierten Kommandozeilenargumente.
        mode: Das MailMode-Objekt.
        base_dir (Path): Das Projekt-Basisverzeichnis.
        signature_path (Path): Pfad zur Signatur-Vorlage.
        signature_logo_path (Path): Pfad zum Logo für die Signatur.

    Returns:
        int: Anzahl der aufgetretenen Fehler während der Verarbeitung der Empfänger.
    """
    _info(f"Starting mode {mode.label}.")
    invalid_log_path = base_dir / "output" / "invalid_mails.csv"
    _log_mode_paths(args, mode, base_dir, signature_path, signature_logo_path, invalid_log_path)

    recipient_files = _scan_recipient_files(args, mode)
    _info("Reading recipients.")
    recipients = read_recipients_from_dir(mode.recipients_dir)
    _info(f"Recipients loaded: {len(recipients)}.")
    _verbose(args.verbose, f"Loaded recipients: {[recipient.email for recipient in recipients]}")

    attachments = _load_attachments(args, mode)
    logged_emails, invalid_emails = _load_exclusion_logs(args, base_dir, invalid_log_path)
    recipients_to_process, skipped_before_send = _filter_recipients(
        args,
        recipients,
        logged_emails,
        invalid_emails,
        invalid_log_path,
    )
    recipients_to_process = _apply_max_send_count(args, recipients_to_process)
    _print_mode_summary(args, mode, recipients, recipients_to_process, skipped_before_send, attachments, invalid_log_path)

    if not recipients_to_process:
        print("Nothing to process.")
        if args.send and args.delete_input_after_success:
            _info("Deleting input files because everything was already handled.")
            _delete_input_files(recipient_files, args.verbose)
        return 0

    _info("Loading SMTP configuration.")
    smtp_config = load_smtp_config(require_password=args.send)
    _verbose(args.verbose, f"SMTP host: {smtp_config.host}:{smtp_config.port}")
    _verbose(args.verbose, f"SMTP username: {smtp_config.username}")
    _verbose(args.verbose, f"SMTP from: {smtp_config.from_name} <{smtp_config.from_email}>")

    errors = _send_or_dry_run(
        args,
        mode,
        signature_path,
        signature_logo_path,
        recipients_to_process,
        attachments,
        smtp_config,
    )

    if errors:
        print(f"Finished {mode.label} with {errors} error(s).")
    else:
        print(f"Finished {mode.label} successfully.")
        if args.send and args.delete_input_after_success:
            _info("Deleting processed input files after successful send.")
            _delete_input_files(recipient_files, args.verbose)
    return errors


def _log_mode_paths(args, mode, base_dir: Path, signature_path: Path, signature_logo_path: Path, invalid_log_path: Path) -> None:
    """Schreibt die wichtigsten Pfade des aktuellen Versandmodus ins Verbose-Log."""
    _verbose(args.verbose, f"Base directory: {base_dir}")
    _verbose(args.verbose, f"Recipient input directory: {mode.recipients_dir}")
    _verbose(args.verbose, f"Mode template: {mode.template_path}")
    _verbose(args.verbose, f"Signature template: {signature_path}")
    _verbose(args.verbose, f"Signature logo: {signature_logo_path}")
    _verbose(args.verbose, f"Signature logo width: {args.signature_logo_width}px")
    _verbose(args.verbose, f"Attachment directory: {mode.attachments_dir}")
    _verbose(args.verbose, f"CSV log file: {mode.log_path}")
    _verbose(args.verbose, f"Invalid email log file: {invalid_log_path}")


def _scan_recipient_files(args, mode) -> list[Path]:
    """
    Durchsucht das Eingabeverzeichnis des Modus nach CSV- oder TXT-Dateien.
    """
    _info("Scanning recipient input files.")
    recipient_files = list_recipient_files(mode.recipients_dir)
    if recipient_files:
        _info(f"Recipient files found: {len(recipient_files)}.")
        for recipient_file in recipient_files:
            _verbose(args.verbose, f"Recipient file queued: {recipient_file}")
    else:
        _info("No recipient files found for this mode.")
        _verbose(args.verbose, "No recipient files found.")
    return recipient_files


def _load_attachments(args, mode) -> list[Path]:
    """
    Lädt alle Dateien aus dem Attachment-Verzeichnis des aktuellen Modus.
    """
    _info("Scanning attachment files for mail sending.")
    attachments = list_attachments(mode.attachments_dir)
    if attachments:
        _info(f"Mail attachments found: {len(attachments)}.")
        for attachment in attachments:
            _verbose(args.verbose, f"Attachment queued: {attachment}")
    else:
        _info("No mail attachments found.")
        _verbose(args.verbose, "No attachments found.")

    if not attachments and not args.allow_empty_attachments:
        raise RuntimeError(
            f"No attachments found in {mode.attachments_dir}. "
            "Add files there or use --allow-empty-attachments."
        )
    return attachments


def _load_exclusion_logs(args, base_dir: Path, invalid_log_path: Path) -> tuple[set[str], set[str]]:
    """
    Lädt die Mengen bereits verarbeiteter (sent) und ungültiger (invalid) E-Mails.
    """
    _info("Loading sent and invalid email logs.")
    logged_emails = set() if args.resend_existing else read_known_output_emails(base_dir / "output")
    invalid_emails = set() if args.skip_invalid_check else read_invalid_emails(invalid_log_path)
    if args.resend_existing:
        _verbose(args.verbose, "Existing CSV log addresses will be ignored because --resend-existing is set.")
    elif logged_emails:
        _verbose(args.verbose, f"Loaded {len(logged_emails)} existing email address(es) from output CSV files.")
    else:
        _verbose(args.verbose, "No existing sent addresses were loaded from output CSV files.")
    if args.skip_invalid_check:
        _verbose(args.verbose, "Invalid CSV log addresses will be ignored because --skip-invalid-check is set.")
    else:
        _verbose(args.verbose, f"Loaded {len(invalid_emails)} invalid email address(es) from {invalid_log_path}.")
    return logged_emails, invalid_emails


def _filter_recipients(args, recipients, logged_emails: set[str], invalid_emails: set[str], invalid_log_path: Path):
    """
    Filtert die geladenen Empfänger basierend auf Duplikaten, Ausschlusslisten und E-Mail-Validierung.
    Parallele Validierung mittels ThreadPoolExecutor.
    """
    _info("Validating and filtering recipients.")

    # 1. Vorab-Filterung (Duplikate und bereits bekannte Logs)
    to_validate = []
    skipped_before_send = 0
    seen_in_this_run = set()

    for recipient in recipients:
        email_key = recipient.email.lower()
        if email_key in logged_emails:
            skipped_before_send += 1
            print(f"[SKIP] {recipient.email} is already present in an output CSV log; no mail will be created or sent.")
            continue
        if not args.skip_invalid_check and email_key in invalid_emails:
            skipped_before_send += 1
            print(f"[SKIP_INVALID] {recipient.email} is already listed in invalid_mails.csv; no mail will be created or sent.")
            continue
        if email_key in seen_in_this_run:
            skipped_before_send += 1
            print(f"[SKIP] {recipient.email} appears more than once in this CSV run; duplicate skipped.")
            continue

        seen_in_this_run.add(email_key)
        to_validate.append(recipient)

    if not to_validate:
        return [], skipped_before_send

    # 2. Parallele Validierung
    validation_kwargs = {"skip_dns_check": args.skip_email_dns_check}
    if args.verify_email_smtp:
        validation_kwargs.update(
            verify_mailbox=True,
            smtp_timeout=args.verify_email_smtp_timeout,
        )

    def validate_one(rec):
        _verbose(args.verbose, f"Checking recipient {rec.email} ({rec.company}).")
        try:
            val = validate_email_address(rec.email, **validation_kwargs)
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            val = validate_email_address(rec.email)
        return rec, val

    max_workers = args.parallel_threads
    _info(f"Validating {len(to_validate)} recipients using {max_workers} threads...")

    recipients_to_process = []
    # Wir sammeln die Ergebnisse in der ursprünglichen Reihenfolge
    results = [None] * len(to_validate)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(validate_one, rec): i for i, rec in enumerate(to_validate)}
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            rec, validation = future.result()
            results[index] = (rec, validation)
            # Sofortiges Feedback für Verbose-User
            _verbose(args.verbose, f"Validation result for {rec.email}: {validation.is_valid} {validation.reason}")

    # 3. Ergebnisse konsolidieren (in ursprünglicher Reihenfolge)
    for res in results:
        if res is None: continue
        recipient, validation = res
        if not validation.is_valid:
            skipped_before_send += 1
            invalid_emails.add(recipient.email.lower())
            append_invalid_email(invalid_log_path, recipient, validation.reason)
            print(f"[INVALID] {recipient.email} | {validation.reason}; logged to {invalid_log_path.name}.")
            continue

        recipients_to_process.append(recipient)
        _verbose(args.verbose, f"Recipient accepted for processing: {recipient.email}")

    return recipients_to_process, skipped_before_send


def _apply_max_send_count(args, recipients_to_process):
    """
    Begrenzt die Anzahl der zu verarbeitenden Empfänger auf den Wert von --max-send-count.
    """
    if args.max_send_count is None or len(recipients_to_process) <= args.max_send_count:
        return recipients_to_process

    _info(f"Limiting this run to {args.max_send_count} recipient(s).")
    _verbose(args.verbose, f"Recipients before max-send-count limit: {[recipient.email for recipient in recipients_to_process]}")
    limited_recipients = recipients_to_process[:args.max_send_count]
    _verbose(args.verbose, f"Recipients after max-send-count limit: {[recipient.email for recipient in limited_recipients]}")
    return limited_recipients


def _print_mode_summary(args, mode, recipients, recipients_to_process, skipped_before_send: int, attachments: list[Path], invalid_log_path: Path) -> None:
    """Gibt die Zusammenfassung des aktuellen Versandmodus aus."""
    print(f"Mode: {mode.label}")
    print(f"Recipients loaded: {len(recipients)}")
    print(f"Recipients skipped before sending: {skipped_before_send}")
    print(f"Recipients to process: {len(recipients_to_process)}")
    print(f"Attachments: {len(attachments)}")
    print(f"Log file: {mode.log_path}")
    print(f"Invalid email log file: {invalid_log_path}")
    print("Existing CSV check: disabled (--resend-existing)" if args.resend_existing else "Existing CSV check: enabled")
    print("Invalid CSV check: disabled (--skip-invalid-check)" if args.skip_invalid_check else "Invalid CSV check: enabled")
    print("Sending: yes" if args.send else "Sending: no (dry-run)")
    print("Dry-run CSV logging: yes" if args.log_dry_run else "Dry-run CSV logging: no")
    print("Sent CSV logging: no" if args.no_write_sent_log else "Sent CSV logging: yes")
    print("Delete input after success: yes" if args.delete_input_after_success else "Delete input after success: no")
    print(f"Parallel threads: {args.parallel_threads}")
    print("SMTP mailbox verification: yes" if args.verify_email_smtp else "SMTP mailbox verification: no")


def _send_or_dry_run(args, mode, signature_path: Path, signature_logo_path: Path, recipients_to_process, attachments: list[Path], smtp_config) -> int:
    """
    Entscheidet basierend auf dem --send Flag, ob ein Dry-Run oder ein echter Versand erfolgt.
    """
    if not args.send:
        _info("Running dry-run rendering; no real emails will be sent.")
        return _process_recipients(
            mailer=None,
            template_path=mode.template_path,
            signature_path=signature_path,
            log_path=mode.log_path,
            recipients=recipients_to_process,
            attachments=attachments,
            subject_override=args.subject,
            signature_image_path=signature_logo_path,
            signature_image_width=args.signature_logo_width,
            dry_run=True,
            log_dry_run=args.log_dry_run,
            write_sent_log=not args.no_write_sent_log,
            verbose=args.verbose,
            smtp_config=None,
            parallel_threads=args.parallel_threads,
        )

    _info("Opening SMTP connection and sending real emails.")
    return _process_recipients(
        mailer=None,
        template_path=mode.template_path,
        signature_path=signature_path,
        log_path=mode.log_path,
        recipients=recipients_to_process,
        attachments=attachments,
        subject_override=args.subject,
        signature_image_path=signature_logo_path,
        signature_image_width=args.signature_logo_width,
        dry_run=False,
        log_dry_run=args.log_dry_run,
        write_sent_log=not args.no_write_sent_log,
        verbose=args.verbose,
        smtp_config=smtp_config,
        parallel_threads=args.parallel_threads,
    )


def _delete_input_files(files: list[Path], verbose: bool) -> None:
    """
    Löscht die verarbeiteten Eingabedateien vom Dateisystem.
    """
    _info(f"Deleting {len(files)} input file(s).")
    for path in files:
        path.unlink()
        _verbose(verbose, f"Deleted input file: {path}")


def _process_recipients(
        mailer: SmtpMailer | None,
        template_path: Path,
        signature_path: Path,
        log_path: Path,
        recipients,
        attachments: list[Path],
        subject_override: str | None,
        signature_image_path: Path,
        signature_image_width: int,
        dry_run: bool,
        log_dry_run: bool,
        write_sent_log: bool,
        verbose: bool,
        smtp_config=None,
        parallel_threads: int = 1,
) -> int:
    """
    Verarbeitet die Liste der Empfänger (Rendern und Senden/Dry-Run).
    Unterstützt parallele Abarbeitung mittels ThreadPoolExecutor.
    """
    _info(f"Processing {len(recipients)} recipient(s).")
    worker_count = max(1, min(parallel_threads, len(recipients) or 1))
    _info(f"Parallel recipient workers: {worker_count}.")

    if worker_count == 1:
        errors = 0
        for recipient in recipients:
            try:
                _process_one_recipient(
                    mailer=mailer,
                    smtp_config=smtp_config,
                    template_path=template_path,
                    signature_path=signature_path,
                    log_path=log_path,
                    recipient=recipient,
                    attachments=attachments,
                    subject_override=subject_override,
                    signature_image_path=signature_image_path,
                    signature_image_width=signature_image_width,
                    dry_run=dry_run,
                    log_dry_run=log_dry_run,
                    write_sent_log=write_sent_log,
                    verbose=verbose,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                errors += 1
                print(f"[ERROR] {recipient.email} | {exc}")
        _info(f"Recipient processing finished with {errors} error(s).")
        return errors

    errors = 0
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                _process_one_recipient,
                mailer=None,
                smtp_config=smtp_config,
                template_path=template_path,
                signature_path=signature_path,
                log_path=log_path,
                recipient=recipient,
                attachments=attachments,
                subject_override=subject_override,
                signature_image_path=signature_image_path,
                signature_image_width=signature_image_width,
                dry_run=dry_run,
                log_dry_run=log_dry_run,
                write_sent_log=write_sent_log,
                verbose=verbose,
            ): recipient
            for recipient in recipients
        }
        for future in as_completed(futures):
            recipient = futures[future]
            try:
                future.result()
            except (OSError, RuntimeError, ValueError) as exc:
                errors += 1
                print(f"[ERROR] {recipient.email} | {exc}")
    _info(f"Recipient processing finished with {errors} error(s).")

    return errors


def _process_one_recipient(
        mailer: SmtpMailer | None,
        smtp_config,
        template_path: Path,
        signature_path: Path,
        log_path: Path,
        recipient,
        attachments: list[Path],
        subject_override: str | None,
        signature_image_path: Path,
        signature_image_width: int,
        dry_run: bool,
        log_dry_run: bool,
        write_sent_log: bool,
        verbose: bool,
) -> None:
    """
    Führt den kompletten Workflow für einen einzelnen Empfänger aus.
    """
    _info(f"Preparing mail for {recipient.email}.")
    _verbose(verbose, f"Rendering mail for {recipient.email}.")
    rendered = render_mail(
        template_path,
        signature_path,
        recipient,
        subject_override=subject_override,
        signature_image_path=signature_image_path,
        signature_image_width=signature_image_width,
    )
    _verbose(verbose, f"Subject for {recipient.email}: {rendered.subject}")
    _verbose(verbose, f"Text body length for {recipient.email}: {len(rendered.text_body)} characters.")
    _verbose(verbose, f"HTML body length for {recipient.email}: {len(rendered.html_body)} characters.")
    _verbose(verbose, f"Attachment count for {recipient.email}: {len(attachments)}")
    _verbose(verbose, f"Inline image count for {recipient.email}: {len(rendered.inline_images)}")

    if dry_run:
        print(f"[DRY_RUN] {recipient.email} | {rendered.subject}")
        if log_dry_run:
            append_log(log_path, recipient)
            _verbose(verbose, f"Dry-run logged to {log_path}.")
        else:
            _verbose(verbose, "Dry-run was not written to CSV because --log-dry-run is not set.")
        return

    if mailer is not None:
        _send_with_mailer(mailer, recipient, rendered, attachments, log_path, write_sent_log, verbose)
        return

    if smtp_config is None:
        raise RuntimeError("SMTP config is required when dry_run is False.")

    _verbose(verbose, "Opening SMTPS connection for recipient worker.")
    with SmtpMailer(smtp_config) as worker_mailer:
        _send_with_mailer(worker_mailer, recipient, rendered, attachments, log_path, write_sent_log, verbose)


def _send_with_mailer(mailer: SmtpMailer, recipient, rendered, attachments: list[Path], log_path: Path, write_sent_log: bool, verbose: bool) -> None:
    """
    Nutzt einen geöffneten Mailer, um eine bereits gerenderte Nachricht zu versenden und zu loggen.
    """
    _verbose(verbose, f"Sending mail to '{recipient.email}'.")
    _info(f"Sending mail to {recipient.email}.")
    mailer.send(
        recipient,
        rendered.subject,
        rendered.text_body,
        rendered.html_body,
        attachments,
        rendered.inline_images,
    )
    if write_sent_log:
        append_log(log_path, recipient)
        _verbose(verbose, f"Sent mail logged to {log_path}.")
    else:
        _verbose(verbose, "Sent mail was not written to CSV because --no-write-sent-log is set.")
    print(f"[SENT] {recipient.email} | {rendered.subject}")
