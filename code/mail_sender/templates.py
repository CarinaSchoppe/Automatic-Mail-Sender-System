from __future__ import annotations

import html
import mimetypes
from collections import defaultdict
from dataclasses import dataclass
from email.utils import make_msgid
from pathlib import Path

from mail_sender.recipients import Recipient


@dataclass(frozen=True)
class InlineImage:
    path: Path
    cid: str
    width: int


@dataclass(frozen=True)
class RenderedMail:
    subject: str
    text_body: str
    html_body: str
    inline_images: list[InlineImage]


def render_mail(
        template_path: Path,
        signature_path: Path,
        recipient: Recipient,
        subject_override: str | None = None,
        signature_image_path: Path | None = None,
        signature_image_width: int = 180,
) -> RenderedMail:
    if not template_path.exists():
        raise FileNotFoundError(f"Mail template not found: {template_path}")
    if not signature_path.exists():
        raise FileNotFoundError(f"Signature template not found: {signature_path}")

    subject_template, body_template = _split_subject(template_path.read_text(encoding="utf-8"))
    if subject_override:
        subject_template = subject_override

    signature = signature_path.read_text(encoding="utf-8").strip()
    context = defaultdict(str, recipient.template_context())
    context["IMAGE"] = "{IMAGE}"

    subject = subject_template.format_map(context).strip()
    body_text = body_template.format_map(context).strip()
    inline_images: list[InlineImage] = []
    signature_text = ""

    if signature:
        signature_text = signature.format_map(context)
        body_text = f"{body_text}\n\n{_render_text_signature(signature_text)}"

    html_body = _text_to_html(body_text)
    if signature and "{IMAGE}" in signature:
        if signature_image_path is None or not signature_image_path.exists():
            raise FileNotFoundError(
                "Signature contains {IMAGE}, but the logo file was not found. "
                "Add it as templates/signature-logo.png or pass --signature-logo."
            )

        content_type, encoding = mimetypes.guess_type(signature_image_path)
        if content_type is None or encoding is not None or not content_type.startswith("image/"):
            raise ValueError(f"Signature logo must be an image file: {signature_image_path}")

        cid = make_msgid(domain="signature.local")[1:-1]
        inline_images.append(InlineImage(path=signature_image_path, cid=cid, width=signature_image_width))
        html_body = _render_html_with_signature_image(body_template.format_map(context), signature_text, cid, signature_image_width)

    return RenderedMail(subject=subject, text_body=body_text, html_body=html_body, inline_images=inline_images)


def _split_subject(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        body_lines = lines[1:]
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        return subject, "\n".join(body_lines)

    return "Message for {company_or_email}", text


def _render_text_signature(signature: str) -> str:
    return signature.replace("{IMAGE}", "[Logo]").strip()


def _text_to_html(text: str) -> str:
    escaped = html.escape(text).replace("\n", "<br>\n")
    return f"<html><body>{escaped}</body></html>"


def _render_html_with_signature_image(body: str, signature: str, cid: str, width: int) -> str:
    safe_body = html.escape(body.strip()).replace("\n", "<br>\n")
    image_html = (
        f'<img src="cid:{cid}" width="{width}" '
        'style="display:block; width:'
        f'{width}px; height:auto; margin:8px 0;" alt="Carina Schoppe logo">'
    )
    safe_signature = html.escape(signature.strip()).replace("{IMAGE}", image_html).replace("\n", "<br>\n")
    return f"<html><body>{safe_body}<br><br>{safe_signature}</body></html>"
