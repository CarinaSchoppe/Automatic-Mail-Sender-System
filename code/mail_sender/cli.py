"""
Command-line interface for email sending.
Processes recipient lists, validates emails, renders templates, and sends messages via SMTP.
Supports dry-runs, parallel processing, and detailed logging.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mail_sender.attachments import list_attachments
from mail_sender.config import ConfigError, load_smtp_config
from mail_sender.email_validation import EmailValidationResult, validate_email_address
from mail_sender.modes import get_available_mode_names
from mail_sender.modes import get_mode
from mail_sender.recipients import Recipient, list_recipient_files, read_recipients_from_dir
from mail_sender.sent_log import append_invalid_email, append_log, read_invalid_emails, read_known_output_emails
from mail_sender.smtp_sender import SmtpMailer
from mail_sender.templates import render_mail


def _verbose(enabled: bool, message: str) -> None:
    """Prints a verbose message if verbose mode is active."""
    if enabled:
        print(f"[VERBOSE] {message}")


def _info(message: str) -> None:
    """Prints a normal info message."""
    print(f"[INFO] {message}")


def main(argv: list[str] | None = None) -> int:
    """
    Main function of the mail sender. Parses arguments and starts the sending process for the chosen modes.

    Args:
        argv (list[str] | None): List of command-line arguments.

    Returns:
        int: Exit code (0 for success, 1 for errors).
    """
    parser = argparse.ArgumentParser(description="Send PhD or Freelance mail batches via SMTPS.")
    parser.add_argument("--mode", required=True, help="Mail mode. Use Auto or any built-in/custom task mode.")
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
    parser.add_argument(
        "--spam-safe",
        action="store_true",
        help="Use the spam-safe mail template and send without file attachments or embedded signature image.",
    )
    parser.add_argument("--subject", help="Optional subject override. Supports template placeholders like {company}.")
    parser.add_argument("--signature-logo", default="templates/signature-logo.png", help="Inline logo image used when the signature contains {IMAGE}.")
    parser.add_argument("--signature-logo-width", type=int, default=180, help="Width of the inline signature logo in pixels.")
    parser.add_argument("--max-send-count", type=int, help="Maximum number of filtered recipients to process in this run.")
    parser.add_argument("--parallel-threads", type=int, default=1, help="Maximum number of recipients to render/send in parallel.")
    parser.add_argument("--verify-email-smtp", action="store_true", help="Probe recipient MX servers for definitive mailbox rejects before sending.")
    parser.add_argument(
        "--require-email-smtp-pass",
        action="store_true",
        help="Only accept recipients whose mailbox is positively confirmed by the SMTP probe.",
    )
    parser.add_argument(
        "--reject-catch-all",
        action="store_true",
        help="Reject domains that accept random invented mailboxes because the real recipient cannot be confirmed.",
    )
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
            print("No input files found for any available mode.")
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
    Selects the corresponding mail modes based on the mode name.
    In "Auto" mode, all modes with existing input files are selected.
    """
    normalized = mode_name.strip().lower()
    if normalized != "auto":
        return [get_mode(mode_name, base_dir)]

    modes = [get_mode(name, base_dir) for name in get_available_mode_names(base_dir)]
    return [mode for mode in modes if list_recipient_files(mode.recipients_dir)]


def _run_mode(args, mode, base_dir: Path, signature_path: Path, signature_logo_path: Path) -> int:
    """
    Executes the sending process for a specific mode (e.g., PhD).

    Args:
        args: The parsed command-line arguments.
        mode: The MailMode object.
        base_dir (Path): The project base directory.
        signature_path (Path): Path to the signature template.
        signature_logo_path (Path): Path to the logo for the signature.

    Returns:
        int: Number of errors encountered during recipient processing.
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
    validation_smtp_from = _load_validation_smtp_from(args)
    recipients_to_process, skipped_before_send = _filter_recipients(
        args,
        recipients,
        logged_emails,
        invalid_emails,
        invalid_log_path,
        validation_smtp_from,
    )
    recipients_to_process = _apply_max_send_count(args, recipients_to_process)
    _print_mode_summary(args, mode, recipients, recipients_to_process, skipped_before_send, attachments, invalid_log_path)

    if not recipients_to_process:
        print("Nothing to process.")
        if args.send and args.delete_input_after_success:
            _info("Checking for completed input files to delete (nothing to process in this run).")
            completed_files = _identify_completed_files(recipients, logged_emails, invalid_emails)
            if completed_files:
                _delete_input_files(completed_files, args.verbose)
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
        _info("Checking for completed input files to delete.")
        # Reload logs to see what was actually sent/marked invalid in this run
        logged_emails_after, invalid_emails_after = _load_exclusion_logs(args, base_dir, invalid_log_path)
        completed_files = _identify_completed_files(recipients, logged_emails_after, invalid_emails_after)
        if completed_files:
            _delete_input_files(completed_files, args.verbose)
        else:
            _info("No input files were fully processed (some recipients might still be pending or failed).")
    return errors


def _identify_completed_files(recipients: list[Recipient], logged_emails: set[str], invalid_emails: set[str]) -> list[Path]:
    """
    Identifies files where all recipients have been either successfully logged or marked invalid.
    """
    file_to_recipients: dict[Path, list[str]] = {}
    for r in recipients:
        if r.source_file:
            file_to_recipients.setdefault(r.source_file, []).append(r.email.lower())

    completed_files: list[Path] = []
    for file_path, emails in file_to_recipients.items():
        if all(email in logged_emails or email in invalid_emails for email in emails):
            completed_files.append(file_path)

    return completed_files


def _log_mode_paths(args, mode, base_dir: Path, signature_path: Path, signature_logo_path: Path, invalid_log_path: Path) -> None:
    """Writes the most important paths of the current mailing mode to the verbose log."""
    template_path = mode.spam_safe_template_path if args.spam_safe else mode.template_path
    _verbose(args.verbose, f"Base directory: {base_dir}")
    _verbose(args.verbose, f"Recipient input directory: {mode.recipients_dir}")
    _verbose(args.verbose, f"Mode template: {template_path}")
    _verbose(args.verbose, f"Spam-safe mode: {'enabled' if args.spam_safe else 'disabled'}")
    _verbose(args.verbose, f"Signature template: {signature_path}")
    _verbose(args.verbose, f"Signature logo: {signature_logo_path}")
    _verbose(args.verbose, f"Signature logo width: {args.signature_logo_width}px")
    _verbose(args.verbose, f"Attachment directory: {mode.attachments_dir}")
    _verbose(args.verbose, f"CSV log file: {mode.log_path}")
    _verbose(args.verbose, f"Invalid email log file: {invalid_log_path}")


def _scan_recipient_files(args, mode) -> list[Path]:
    """
    Scans the mode's input directory for CSV or TXT files.
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
    Loads all files from the attachment directory of the current mode.
    """
    if args.spam_safe:
        _info("Spam-safe mode enabled; skipping all mail attachments.")
        _verbose(args.verbose, "Attachment scan skipped because --spam-safe is set.")
        return []

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
    Loads the sets of already processed (sent) and invalid email addresses.
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


def _load_validation_smtp_from(args) -> str | None:
    """Loads the configured sender address for SMTP mailbox probes."""
    if not _smtp_mailbox_validation_enabled(args):
        return None
    smtp_config = load_smtp_config(require_password=False)
    _verbose(args.verbose, f"SMTP validation MAIL FROM: {smtp_config.from_email}")
    return smtp_config.from_email


def _smtp_mailbox_validation_enabled(args) -> bool:
    """Returns True when recipient validation needs live SMTP probes."""
    return bool(args.verify_email_smtp or args.require_email_smtp_pass or args.reject_catch_all)


def _filter_recipients(
        args,
        recipients,
        logged_emails: set[str],
        invalid_emails: set[str],
        invalid_log_path: Path,
        validation_smtp_from: str | None = None,
):
    """
    Filters the loaded recipients based on duplicates, exclusion lists, and email validation.
    Parallel validation using ThreadPoolExecutor.
    """
    _info("Validating and filtering recipients.")

    # 1. Pre-filtering (duplicates and already known logs)
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
        _info(f"Recipient pre-filter removed all rows. Skipped before validation: {skipped_before_send}.")
        return [], skipped_before_send

    # 2. Parallele Validierung
    validation_kwargs = {"skip_dns_check": args.skip_email_dns_check}
    if _smtp_mailbox_validation_enabled(args):
        validation_kwargs.update(
            verify_mailbox=True,
            require_mailbox_confirmation=args.require_email_smtp_pass,
            reject_catch_all=args.reject_catch_all,
            smtp_timeout=args.verify_email_smtp_timeout,
        )
        if validation_smtp_from:
            validation_kwargs["smtp_from_email"] = validation_smtp_from
    _verbose(args.verbose, f"Validation options: {validation_kwargs}")

    def validate_one(rec):
        _verbose(args.verbose, f"Checking recipient {rec.email} ({rec.company}).")
        try:
            val = validate_email_address(rec.email, **validation_kwargs)
        except TypeError as type_error:
            if "unexpected keyword" not in str(type_error):
                raise
            val = validate_email_address(rec.email)
        return rec, val

    max_workers = args.parallel_threads
    _info(f"Validating {len(to_validate)} recipients using {max_workers} threads...")

    recipients_to_process = []
    # We collect the results in the original order
    results: list[tuple[Recipient, EmailValidationResult] | None] = [None] * len(to_validate)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(validate_one, rec): i for i, rec in enumerate(to_validate)}
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            rec = to_validate[index]
            try:
                rec, validation = future.result()
            except Exception as validation_error:  # pragma: no cover - defensive around third-party DNS/SMTP libraries
                reason = f"validation crashed: {type(validation_error).__name__}: {validation_error}"
                validation = EmailValidationResult(False, reason)
            results[index] = (rec, validation)
            # Instant feedback for verbose users
            _verbose(args.verbose, f"Validation result for {rec.email}: {validation.is_valid} {validation.reason}")

    # 3. Consolidate results (in original order)
    for res in results:
        if res is None:
            continue
        recipient, validation = res
        if not validation.is_valid:
            skipped_before_send += 1
            invalid_emails.add(recipient.email.lower())
            append_invalid_email(invalid_log_path, recipient, validation.reason)
            print(f"[INVALID] {recipient.email} | {validation.reason}; logged to {invalid_log_path.name}.")
            continue

        recipients_to_process.append(recipient)
        _verbose(args.verbose, f"Recipient accepted for processing: {recipient.email}")

    _info(
        "Validation summary: "
        f"loaded={len(recipients)}, prefiltered_or_invalid={skipped_before_send}, "
        f"accepted={len(recipients_to_process)}, rejected={len(to_validate) - len(recipients_to_process)}."
    )
    return recipients_to_process, skipped_before_send


def _apply_max_send_count(args, recipients_to_process):
    """
    Limits the number of recipients to be processed to the value of --max-send-count.
    """
    if args.max_send_count is None or len(recipients_to_process) <= args.max_send_count:
        return recipients_to_process

    _info(f"Limiting this run to {args.max_send_count} recipient(s).")
    _verbose(args.verbose, f"Recipients before max-send-count limit: {[recipient.email for recipient in recipients_to_process]}")
    limited_recipients = recipients_to_process[:args.max_send_count]
    _verbose(args.verbose, f"Recipients after max-send-count limit: {[recipient.email for recipient in limited_recipients]}")
    return limited_recipients


def _print_mode_summary(args, mode, recipients, recipients_to_process, skipped_before_send: int, attachments: list[Path], invalid_log_path: Path) -> None:
    """Prints the summary of the current mailing mode."""
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
    print("Spam-safe mode: yes" if args.spam_safe else "Spam-safe mode: no")
    print(f"Parallel threads: {args.parallel_threads}")
    print("SMTP mailbox verification: yes" if args.verify_email_smtp else "SMTP mailbox verification: no")
    print("Require SMTP mailbox confirmation: yes" if args.require_email_smtp_pass else "Require SMTP mailbox confirmation: no")
    print("Reject catch-all domains: yes" if args.reject_catch_all else "Reject catch-all domains: no")


def _send_or_dry_run(args, mode, signature_path: Path, signature_logo_path: Path, recipients_to_process, attachments: list[Path], smtp_config) -> int:
    """
    Decides based on the --send flag whether a dry-run or a real mailing occurs.
    """
    template_path = mode.spam_safe_template_path if args.spam_safe else mode.template_path
    embed_signature_image = not args.spam_safe
    if not args.send:
        _info("Running dry-run rendering; no real emails will be sent.")
        return _process_recipients(
            mailer=None,
            template_path=template_path,
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
            embed_signature_image=embed_signature_image,
        )

    _info("Opening SMTP connection and sending real emails.")
    return _process_recipients(
        mailer=None,
        template_path=template_path,
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
        embed_signature_image=embed_signature_image,
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
        embed_signature_image: bool = True,
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
                    embed_signature_image=embed_signature_image,
                )
            except Exception as recipient_error:
                errors += 1
                print(f"[ERROR] {recipient.email} | {type(recipient_error).__name__}: {recipient_error}")
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
                embed_signature_image=embed_signature_image,
            ): recipient
            for recipient in recipients
        }
        for future in as_completed(futures):
            recipient = futures[future]
            try:
                future.result()
            except Exception as recipient_error:
                errors += 1
                print(f"[ERROR] {recipient.email} | {type(recipient_error).__name__}: {recipient_error}")
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
        embed_signature_image: bool = True,
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
        embed_signature_image=embed_signature_image,
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
