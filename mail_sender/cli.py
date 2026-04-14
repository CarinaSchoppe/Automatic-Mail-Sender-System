from __future__ import annotations

import argparse
from pathlib import Path

from mail_sender.attachments import list_attachments
from mail_sender.config import ConfigError, load_smtp_config
from mail_sender.email_validation import validate_email_address
from mail_sender.modes import MODE_NAMES
from mail_sender.modes import get_mode
from mail_sender.recipients import list_recipient_files, read_recipients_from_dir
from mail_sender.sent_log import append_invalid_email, append_log, read_invalid_emails, read_known_output_emails, read_logged_emails
from mail_sender.smtp_sender import SmtpMailer
from mail_sender.templates import render_mail


def _verbose(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[VERBOSE] {message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send PhD or Freelance mail batches via SMTPS.")
    parser.add_argument("--mode", required=True, choices=["Auto", "auto", "PhD", "phd", "Freelance_German", "freelance_german", "Freelance_English", "freelance_english"], help="Mail mode.")
    parser.add_argument("--base-dir", default=".", help="Project base directory.")
    parser.add_argument("--send", action="store_true", help="Actually send the emails. Without this flag, dry-run only.")
    parser.add_argument("--log-dry-run", action="store_true", help="Write dry-run rows to the Excel log. Off by default.")
    parser.add_argument("--no-write-sent-log", action="store_true", help="Do not write successfully sent emails to the Excel log.")
    parser.add_argument("--delete-input-after-success", action="store_true", help="Delete processed .csv/.txt input files after a successful real send run.")
    parser.add_argument("--resend-existing", action="store_true", help="Ignore addresses already present in the mode Excel log.")
    parser.add_argument("--allow-empty-attachments", action="store_true", help="Allow sending even if the mode attachment folder is empty.")
    parser.add_argument("--subject", help="Optional subject override. Supports template placeholders like {company}.")
    parser.add_argument("--signature-logo", default="templates/signature-logo.png", help="Inline logo image used when the signature contains {IMAGE}.")
    parser.add_argument("--signature-logo-width", type=int, default=180, help="Width of the inline signature logo in pixels.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed pipeline logging.")
    args = parser.parse_args(argv)

    base_dir = Path(args.base_dir).resolve()
    signature_path = base_dir / "templates" / "signature.txt"
    signature_logo_path = (base_dir / args.signature_logo).resolve() if not Path(args.signature_logo).is_absolute() else Path(args.signature_logo)

    try:
        modes = _select_modes(args.mode, base_dir)
        if not modes:
            print("No input files found in input/PhD, input/Freelance_German, or input/Freelance_English.")
            return 0

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
    normalized = mode_name.strip().lower()
    if normalized != "auto":
        return [get_mode(mode_name, base_dir)]

    modes = [get_mode(name, base_dir) for name in MODE_NAMES]
    return [mode for mode in modes if list_recipient_files(mode.recipients_dir)]


def _run_mode(args, mode, base_dir: Path, signature_path: Path, signature_logo_path: Path) -> int:
    _verbose(args.verbose, f"Base directory: {base_dir}")
    _verbose(args.verbose, f"Recipient input directory: {mode.recipients_dir}")
    _verbose(args.verbose, f"Mode template: {mode.template_path}")
    _verbose(args.verbose, f"Signature template: {signature_path}")
    _verbose(args.verbose, f"Signature logo: {signature_logo_path}")
    _verbose(args.verbose, f"Signature logo width: {args.signature_logo_width}px")
    _verbose(args.verbose, f"Attachment directory: {mode.attachments_dir}")
    _verbose(args.verbose, f"Excel log file: {mode.log_path}")
    invalid_log_path = base_dir / "output" / "invalid_mails.xlsx"
    _verbose(args.verbose, f"Invalid email log file: {invalid_log_path}")

    recipient_files = list_recipient_files(mode.recipients_dir)
    if recipient_files:
        for recipient_file in recipient_files:
            _verbose(args.verbose, f"Recipient file queued: {recipient_file}")
    else:
        _verbose(args.verbose, "No recipient files found.")

    recipients = read_recipients_from_dir(mode.recipients_dir)
    _verbose(args.verbose, f"Loaded recipients: {[recipient.email for recipient in recipients]}")

    attachments = list_attachments(mode.attachments_dir)
    if attachments:
        for attachment in attachments:
            _verbose(args.verbose, f"Attachment queued: {attachment}")
    else:
        _verbose(args.verbose, "No attachments found.")

    if not attachments and not args.allow_empty_attachments:
        raise RuntimeError(
            f"No attachments found in {mode.attachments_dir}. "
            "Add files there or use --allow-empty-attachments."
        )

    logged_emails = set() if args.resend_existing else read_known_output_emails(base_dir / "output")
    invalid_emails = read_invalid_emails(invalid_log_path)
    if args.resend_existing:
        _verbose(args.verbose, "Existing Excel log addresses will be ignored because --resend-existing is set.")
    elif logged_emails:
        _verbose(args.verbose, f"Loaded {len(logged_emails)} existing email address(es) from output Excel files.")
    else:
        _verbose(args.verbose, "No existing sent addresses were loaded from output Excel files.")
    _verbose(args.verbose, f"Loaded {len(invalid_emails)} invalid email address(es) from {invalid_log_path}.")

    recipients_to_process = []
    skipped_before_send = 0
    seen_in_this_run = set()
    for recipient in recipients:
        email_key = recipient.email.lower()
        if email_key in logged_emails:
            skipped_before_send += 1
            print(f"[SKIP] {recipient.email} is already present in an output Excel log; no mail will be created or sent.")
            continue
        if email_key in invalid_emails:
            skipped_before_send += 1
            print(f"[SKIP_INVALID] {recipient.email} is already listed in invalid_mails.xlsx; no mail will be created or sent.")
            continue
        if email_key in seen_in_this_run:
            skipped_before_send += 1
            print(f"[SKIP] {recipient.email} appears more than once in this CSV run; duplicate skipped.")
            continue
        validation = validate_email_address(recipient.email)
        if not validation.is_valid:
            skipped_before_send += 1
            invalid_emails.add(email_key)
            append_invalid_email(invalid_log_path, recipient, validation.reason)
            print(f"[INVALID] {recipient.email} | {validation.reason}; logged to {invalid_log_path.name}.")
            continue
        seen_in_this_run.add(email_key)
        recipients_to_process.append(recipient)

    print(f"Mode: {mode.label}")
    print(f"Recipients loaded: {len(recipients)}")
    print(f"Recipients skipped before sending: {skipped_before_send}")
    print(f"Recipients to process: {len(recipients_to_process)}")
    print(f"Attachments: {len(attachments)}")
    print(f"Log file: {mode.log_path}")
    print(f"Invalid email log file: {invalid_log_path}")
    print("Existing Excel check: disabled (--resend-existing)" if args.resend_existing else "Existing Excel check: enabled")
    print("Sending: yes" if args.send else "Sending: no (dry-run)")
    print("Dry-run Excel logging: yes" if args.log_dry_run else "Dry-run Excel logging: no")
    print("Sent Excel logging: no" if args.no_write_sent_log else "Sent Excel logging: yes")
    print("Delete input after success: yes" if args.delete_input_after_success else "Delete input after success: no")

    if not recipients_to_process:
        print("Nothing to process.")
        if args.send and args.delete_input_after_success:
            _delete_input_files(recipient_files, args.verbose)
        return 0

    smtp_config = load_smtp_config(require_password=args.send)
    _verbose(args.verbose, f"SMTP host: {smtp_config.host}:{smtp_config.port}")
    _verbose(args.verbose, f"SMTP username: {smtp_config.username}")
    _verbose(args.verbose, f"SMTP from: {smtp_config.from_name} <{smtp_config.from_email}>")
    0

    if args.send:
        _verbose(args.verbose, "Opening SMTPS connection.")
        with SmtpMailer(smtp_config) as mailer:
            _verbose(args.verbose, "SMTPS connection opened and login completed.")
            errors = _process_recipients(
                mailer=mailer,
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
            )
    else:
        errors = _process_recipients(
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
        )

    if errors:
        print(f"Finished {mode.label} with {errors} error(s).")
    else:
        print(f"Finished {mode.label} successfully.")
        if args.send and args.delete_input_after_success:
            _delete_input_files(recipient_files, args.verbose)
    return errors


def _delete_input_files(files: list[Path], verbose: bool) -> None:
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
) -> int:
    errors = 0
    for recipient in recipients:
        try:
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
                    _verbose(verbose, "Dry-run was not written to Excel because --log-dry-run is not set.")
                continue

            if mailer is None:
                raise RuntimeError("Mailer is required when dry_run is False.")

            _verbose(verbose, f"Sending mail to '{recipient.email}'.")
            mailer.send(
                recipient,
                rendered.subject,
                rendered.text_body,
                rendered.html_body,
                attachments,
                rendered.inline_images,
            )
            print(f"[SENT] {recipient.email} | {rendered.subject}")
            if write_sent_log:
                append_log(log_path, recipient)
                _verbose(verbose, f"Sent mail logged to {log_path}.")
            else:
                _verbose(verbose, "Sent mail was not written to Excel because --no-write-sent-log is set.")
        except Exception as exc:  # Keep the batch moving and log the failed recipient.
            errors += 1
            print(f"[ERROR] {recipient.email} | {exc}")

    return errors
