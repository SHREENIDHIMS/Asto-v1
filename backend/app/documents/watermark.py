"""Client-facing document watermarking (Phase I5).

Compliance-friendly "Viewed by {viewer} on {date}" overlay applied to the
served copy at request time — never to the stored file. Staff/admin file
serving bypasses this module entirely (see ``client.py``).

PDFs are stamped by merging a reportlab-generated text page onto every page
via pypdf. Images get a diagonal PIL text overlay. Anything else (or any
failure to watermark) passes through unchanged so a watermarking hiccup never
breaks document delivery.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

_PDF_SUFFIXES = (".pdf",)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp")


def watermark_text(viewer: str, now: datetime | None = None) -> str:
    """Build the watermark string, e.g. 'Viewed by Jane Doe on 2026-08-15'."""
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
    return f"Viewed by {viewer} on {stamp}"


def watermark_bytes(data: bytes, filename: str, viewer: str) -> bytes:
    """Return ``data`` with a viewer watermark applied where supported.

    Unknown or unprocessable content is returned unchanged.
    """
    lower = (filename or "").lower()
    text = watermark_text(viewer)

    if lower.endswith(_PDF_SUFFIXES):
        try:
            return _watermark_pdf(data, text)
        except Exception:  # noqa: BLE001 - never fail document delivery
            logger.warning("PDF watermark failed, serving raw bytes", exc_info=True)
            return data

    if lower.endswith(_IMAGE_SUFFIXES):
        try:
            return _watermark_image(data, text)
        except Exception:  # noqa: BLE001
            logger.warning("Image watermark failed, serving raw bytes", exc_info=True)
            return data

    return data


def _watermark_pdf(data: bytes, text: str) -> bytes:
    from pypdf import PdfReader, PdfWriter

    from reportlab.lib.colors import Color
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas

    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()

    for page in reader.pages:
        width = float(page.mediabox.width or 0)
        height = float(page.mediabox.height or 0)

        packet = io.BytesIO()
        c = canvas.Canvas(packet, pagesize=(width, height))
        c.saveState()
        c.setFillColor(Color(0.4, 0.4, 0.4, alpha=0.35))
        c.setFont("Helvetica", 12)
        c.translate(width / 2, height / 2)
        c.rotate(45)
        c.drawCentredString(0, 0, text)
        c.restoreState()
        c.save()
        packet.seek(0)

        overlay = PdfReader(packet).pages[0]
        page.merge_page(overlay)
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _watermark_image(data: bytes, text: str) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        base = image.convert("RGB")
        width, height = base.size
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        try:
            font = ImageFont.load_default(28)
        except TypeError:  # older Pillow: load_default() takes no size
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        draw.text(
            ((width - text_w) / 2, (height - text_h) / 2),
            text,
            fill=(120, 120, 120, 120),
            font=font,
        )

        base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

        out = io.BytesIO()
        fmt = image.format or "PNG"
        base.save(out, format=fmt)
        return out.getvalue()
