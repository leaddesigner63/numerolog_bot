from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Protocol

from importlib.util import find_spec
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.core.config import settings


_FONT_NAME = "DejaVuSans"
_FONT_REGISTERED = False
_BOTO3_AVAILABLE = find_spec("boto3") is not None
if _BOTO3_AVAILABLE:
    import boto3


def _register_font() -> str:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return _FONT_NAME
    if settings.pdf_font_path:
        custom_path = Path(settings.pdf_font_path)
        if not custom_path.exists():
            logging.getLogger(__name__).warning(
                "pdf_font_custom_missing",
                extra={"font_path": str(custom_path)},
            )
    for font_path in _resolve_font_paths():
        if not font_path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(_FONT_NAME, str(font_path)))
            _FONT_REGISTERED = True
            return _FONT_NAME
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "pdf_font_register_failed",
                extra={"font_path": str(font_path), "error": str(exc)},
            )
    return "Helvetica"


def _resolve_font_paths() -> list[Path]:
    paths: list[Path] = []
    if settings.pdf_font_path:
        paths.append(Path(settings.pdf_font_path))
    paths.append(Path(__file__).resolve().parents[1] / "assets" / "fonts" / "DejaVuSans.ttf")
    return paths

def _wrap_text(text: str, max_width: float, font_name: str, font_size: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split()
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = word
        if current:
            lines.append(current)
    return lines


class PdfStorage(Protocol):
    def save(self, key: str, content: bytes) -> str:
        ...

    def load(self, key: str) -> bytes:
        ...


class LocalPdfStorage:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, key: str, content: bytes) -> str:
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    def load(self, key: str) -> bytes:
        path = self._root / key
        return path.read_bytes()


class BucketPdfStorage:
    def __init__(self, bucket: str, prefix: str | None) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/") if prefix else None
        self._client = boto3.client("s3", endpoint_url=os.getenv("AWS_ENDPOINT_URL"))

    def save(self, key: str, content: bytes) -> str:
        storage_key = self._build_key(key)
        self._client.put_object(
            Bucket=self._bucket,
            Key=storage_key,
            Body=content,
            ContentType="application/pdf",
        )
        return storage_key

    def load(self, key: str) -> bytes:
        storage_key = self._build_key(key, use_prefix=False)
        response = self._client.get_object(Bucket=self._bucket, Key=storage_key)
        return response["Body"].read()

    def _build_key(self, key: str, *, use_prefix: bool = True) -> str:
        if not use_prefix or not self._prefix:
            return key
        return f"{self._prefix}/{key}"


class PdfService:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)
        self._storage = self._build_storage()

    def generate_pdf(self, text: str) -> bytes:
        font_name = _register_font()
        if font_name != _FONT_NAME:
            custom_path = settings.pdf_font_path
            self._logger.warning(
                "pdf_font_missing",
                extra={"font_path": custom_path or "bundled"},
            )
        buffer = BytesIO()
        page_width, page_height = A4
        margin = 40
        font_size = 11
        line_height = int(font_size * 1.5)
        max_width = page_width - margin * 2

        pdf = canvas.Canvas(buffer, pagesize=A4)
        pdf.setFont(font_name, font_size)

        y = page_height - margin
        for line in _wrap_text(text, max_width, font_name, font_size):
            if y <= margin:
                pdf.showPage()
                pdf.setFont(font_name, font_size)
                y = page_height - margin
            pdf.drawString(margin, y, line)
            y -= line_height

        pdf.save()
        return buffer.getvalue()

    def store_pdf(self, report_id: int, content: bytes) -> str | None:
        key = f"{report_id}.pdf"
        try:
            return self._storage.save(key, content)
        except Exception as exc:
            self._logger.warning(
                "pdf_store_failed",
                extra={"report_id": report_id, "error": str(exc)},
            )
            return None

    def load_pdf(self, storage_key: str) -> bytes | None:
        try:
            return self._storage.load(storage_key)
        except Exception as exc:
            self._logger.warning(
                "pdf_load_failed",
                extra={"storage_key": storage_key, "error": str(exc)},
            )
            return None

    def storage_mode(self) -> str:
        if settings.pdf_storage_bucket:
            return "bucket"
        return "local"

    def _build_storage(self) -> PdfStorage:
        if settings.pdf_storage_bucket:
            if _BOTO3_AVAILABLE:
                try:
                    return BucketPdfStorage(
                        settings.pdf_storage_bucket,
                        settings.pdf_storage_key or "reports",
                    )
                except Exception as exc:
                    self._logger.warning(
                        "pdf_bucket_init_failed",
                        extra={
                            "bucket": settings.pdf_storage_bucket,
                            "error": str(exc),
                        },
                    )
            else:
                self._logger.warning(
                    "pdf_bucket_unavailable_missing_boto3",
                    extra={"bucket": settings.pdf_storage_bucket},
                )
        root = Path(settings.pdf_storage_key or "storage/pdfs")
        return LocalPdfStorage(root)


pdf_service = PdfService()
