"""
Module for rendering email templates.
Supports placeholders (e.g., {company}), HTML conversion, and appending the configured HTML signature.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from mail_sender.recipients import Recipient


@dataclass(frozen=True)
class InlineImage:
    """
    Represents an image that is embedded directly into the HTML body of an email (via CID).
    """
    path: Path
    cid: str
    width: int


@dataclass(frozen=True)
class RenderedMail:
    """
    Holds the result of the rendering process ready for sending.
    """
    subject: str
    text_body: str
    html_body: str
    inline_images: list[InlineImage]


def render_mail(
        template_path: Path,
        signature_path: Path,
        recipient: Recipient,
        subject_override: str | None = None,
) -> RenderedMail:
    """
    Creates the subject, plain text body, and HTML body for an email.
    Replaces placeholders with recipient data and adds the configured HTML signature.

    Args:
        template_path (Path): Path to the mode's .txt template.
        signature_path (Path): Path to the HTML signature file.
        recipient (Recipient): Data of the current recipient.
        subject_override (str | None): Optional subject override.

    Returns:
        RenderedMail: The finished email object.
    """
    if not template_path.exists():
        raise FileNotFoundError(f"Mail template not found: {template_path}")
    if not signature_path.exists():
        raise FileNotFoundError(f"Signature HTML file not found: {signature_path}")

    subject_template, body_template = _split_subject(template_path.read_text(encoding="utf-8"))
    if subject_override:
        subject_template = subject_override

    signature = signature_path.read_text(encoding="utf-8").strip()
    signature_html = _html_body_fragment(signature)
    signature_text = _html_to_text(signature)
    signature_marker = "__MAILSENDER_SIGNATURE_HTML__"
    context = defaultdict(str, recipient.template_context())
    context["SIGNATURE"] = signature_marker

    subject = subject_template.format_map(context).strip()
    body_with_marker = body_template.format_map(context).strip()
    inline_images: list[InlineImage] = []
    if signature_marker in body_with_marker:
        body_text = body_with_marker.replace(signature_marker, signature_text).strip()
        html_body = _text_to_html(body_with_marker).replace(html.escape(signature_marker), signature_html)
    elif signature:
        body_text = f"{body_with_marker}\n\n{signature_text}".strip()
        html_body = _append_signature_html(_text_to_html(body_with_marker), signature_html)
    else:
        body_text = body_with_marker
        html_body = _text_to_html(body_with_marker)

    return RenderedMail(subject=subject, text_body=body_text, html_body=html_body, inline_images=inline_images)


def _split_subject(text: str) -> tuple[str, str]:
    """
    Splits the subject from the rest of the template body, if present (Subject: ...).
    """
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        body_lines = lines[1:]
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        return subject, "\n".join(body_lines)

    return "Message for {company_or_email}", text


def _text_to_html(text: str) -> str:
    """Escapes plain text and preserves line breaks as HTML breaks."""
    escaped = html.escape(text).replace("\n", "<br>\n")
    return f"<html><body>{escaped}</body></html>"


def _html_to_text(markup: str) -> str:
    """Extracts a readable plain-text fallback from the configured HTML signature."""
    extractor = _HtmlTextExtractor()
    extractor.feed(markup)
    extractor.close()
    return extractor.text()


def _html_body_fragment(markup: str) -> str:
    """Returns the body content when the configured signature is a full HTML document."""
    match = re.search(r"<body\b[^>]*>(?P<body>.*?)</body>", markup, flags=re.IGNORECASE | re.DOTALL)
    return match.group("body").strip() if match else markup.strip()


def _append_signature_html(html_body: str, signature_html: str) -> str:
    """Inserts the signature fragment before the message body's closing tag."""
    if not signature_html:
        return html_body
    return re.sub(
        r"</body>\s*</html>\s*$",
        f"<br><br>{signature_html}</body></html>",
        html_body,
        flags=re.IGNORECASE,
    )


class _HtmlTextExtractor(HTMLParser):
    """Small HTML-to-text extractor for multipart/alternative plain text bodies."""

    _BREAK_TAGS = {"br", "div", "p", "tr", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Adds useful text for links/images and lightweight line breaks."""
        if tag in self._BREAK_TAGS:
            self._newline()
        if tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.handle_data(alt)

    def handle_endtag(self, tag: str) -> None:
        """Keeps block-ish tags separated in the text alternative."""
        if tag in self._BREAK_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        """Stores non-empty normalized text chunks."""
        text = " ".join(data.split())
        if text:
            if self._chunks and self._chunks[-1] not in {"\n", " "}:
                self._chunks.append(" ")
            self._chunks.append(text)

    def _newline(self) -> None:
        if self._chunks and self._chunks[-1] != "\n":
            self._chunks.append("\n")

    def text(self) -> str:
        """Returns the extracted text with duplicate blank lines removed."""
        lines = []
        for line in "".join(self._chunks).splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
        return "\n".join(lines)
