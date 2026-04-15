"""
Modul für den E-Mail-Versand über SMTP (SSL/TLS).
Kapselt die Verbindung zum Mail-Server und die Erstellung von MIME-Nachrichten (Text, HTML, Anhänge, Bilder).
"""

from __future__ import annotations

import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import cast

from mail_sender.config import SmtpConfig
from mail_sender.recipients import Recipient
from mail_sender.templates import InlineImage


class SmtpMailer:
    """
    Verwaltet eine SMTPS-Sitzung. Kann als Context Manager genutzt werden,
    um die Verbindung automatisch zu öffnen und zu schließen.
    """

    def __init__(self, config: SmtpConfig) -> None:
        """Initialisiert die Instanz und ihre benoetigten Zustandswerte."""
        self._config = config
        self._server: smtplib.SMTP_SSL | None = None

    def __enter__(self) -> "SmtpMailer":
        """Oeffnet die Ressource fuer die Nutzung im Context Manager."""
        context = ssl.create_default_context()
        server = smtplib.SMTP_SSL(self._config.host, self._config.port, context=context)
        server.login(self._config.username, self._config.password)
        self._server = server
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        """Schliesst die Ressource beim Verlassen des Context Managers."""
        if self._server is not None:
            self._server.quit()
            self._server = None

    def send(
            self,
            recipient: Recipient,
            subject: str,
            text_body: str,
            html_body: str,
            attachments: list[Path],
            inline_images: list[InlineImage],
    ) -> None:
        """
        Erstellt und versendet eine E-Mail an einen Empfänger.

        Args:
            recipient (Recipient): Der Empfänger der Mail.
            subject (str): Der Betreff.
            text_body (str): Der reine Text-Inhalt.
            html_body (str): Der HTML-Inhalt.
            attachments (list[Path]): Liste von Dateianhängen.
            inline_images (list[InlineImage]): Liste von eingebetteten Bildern (CIDs).
        """
        if self._server is None:
            raise RuntimeError("SMTP connection is not open.")

        message = EmailMessage()
        message["From"] = formataddr((self._config.from_name, self._config.from_email))
        message["To"] = recipient.email
        message["Subject"] = subject
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

        payload = cast(list[EmailMessage], message.get_payload())
        html_part = payload[-1]
        for inline_image in inline_images:
            main_type, sub_type = guess_content_type(inline_image.path, fallback=("image", "png"))
            html_part.add_related(
                inline_image.path.read_bytes(),
                maintype=main_type,
                subtype=sub_type,
                cid=f"<{inline_image.cid}>",
                filename=inline_image.path.name,
            )

        for attachment in attachments:
            main_type, sub_type = guess_content_type(attachment, fallback=("application", "octet-stream"))

            message.add_attachment(
                attachment.read_bytes(),
                maintype=main_type,
                subtype=sub_type,
                filename=attachment.name,
            )

        self._server.send_message(message)


def guess_content_type(path: Path, fallback: tuple[str, str]) -> tuple[str, str]:
    """
    Versucht den MIME-Typ einer Datei basierend auf ihrer Endung zu ermitteln.
    """
    content_type, encoding = mimetypes.guess_type(path)
    if content_type is None or encoding is not None:
        return fallback
    return tuple(content_type.split("/", 1))  # type: ignore[return-value]
