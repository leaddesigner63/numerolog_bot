from __future__ import annotations

import logging
import os
import random
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from importlib.util import find_spec
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.core.config import settings
from app.core.pdf_themes import PdfTheme, resolve_pdf_theme


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

    def delete(self, key: str) -> None:
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

    def delete(self, key: str) -> None:
        path = self._root / key
        if not path.exists():
            return
        path.unlink()


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

    def delete(self, key: str) -> None:
        storage_key = self._build_key(key, use_prefix=False)
        self._client.delete_object(Bucket=self._bucket, Key=storage_key)

    def _build_key(self, key: str, *, use_prefix: bool = True) -> str:
        if not use_prefix or not self._prefix:
            return key
        return f"{self._prefix}/{key}"


class PdfService:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)
        self._storage = self._build_storage()
        self._fallback_storage = self._build_fallback_storage()

    def generate_pdf(
        self,
        text: str,
        tariff: Any = None,
        meta: dict[str, Any] | None = None,
    ) -> bytes:
        renderer = PdfThemeRenderer(logger=self._logger)
        try:
            return renderer.render(text, tariff, meta)
        except Exception as exc:
            self._logger.warning(
                "pdf_theme_render_failed",
                extra={"error": str(exc), "tariff": str(tariff or "unknown")},
            )
            return self._generate_legacy_pdf(text)

    def _generate_legacy_pdf(self, text: str) -> bytes:
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
            if self._storage is not self._fallback_storage:
                try:
                    return self._fallback_storage.save(key, content)
                except Exception as fallback_exc:
                    self._logger.warning(
                        "pdf_store_fallback_failed",
                        extra={
                            "report_id": report_id,
                            "error": str(fallback_exc),
                        },
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

    def delete_pdf(self, storage_key: str | None) -> bool:
        if not storage_key:
            return False
        try:
            self._storage.delete(storage_key)
            return True
        except Exception as exc:
            self._logger.warning(
                "pdf_delete_failed",
                extra={"storage_key": storage_key, "error": str(exc)},
            )
            return False

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

    def _build_fallback_storage(self) -> PdfStorage:
        root = Path("storage/pdfs_fallback")
        return LocalPdfStorage(root)


pdf_service = PdfService()


class PdfThemeRenderer:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def render(
        self,
        report_text: str,
        tariff: Any,
        meta: dict[str, Any] | None,
    ) -> bytes:
        font_name = _register_font()
        theme = resolve_pdf_theme(tariff)
        payload_meta = meta or {}
        seed_basis = f"{payload_meta.get('id', '')}-{payload_meta.get('created_at', '')}-{tariff}"
        randomizer = random.Random(seed_basis)

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        page_width, page_height = A4

        self._draw_background(pdf, theme, page_width, page_height, randomizer)
        self._draw_decorative_layers(pdf, theme, page_width, page_height, randomizer)
        self._draw_header(pdf, theme, font_name, payload_meta, tariff, page_height)
        self._draw_body(pdf, theme, font_name, report_text, page_width, page_height)

        pdf.save()
        return buffer.getvalue()

    def _draw_background(
        self,
        pdf: canvas.Canvas,
        theme: PdfTheme,
        page_width: float,
        page_height: float,
        randomizer: random.Random,
    ) -> None:
        for idx, color in enumerate(theme.palette[:2]):
            alpha = max(theme.overlay_alpha * (idx + 1), 0.03)
            pdf.saveState()
            pdf.setFillColor(color, alpha=alpha)
            pdf.rect(
                -10 * idx,
                -10 * idx,
                page_width + 20 * idx,
                page_height + 20 * idx,
                fill=1,
                stroke=0,
            )
            pdf.restoreState()

        pdf.saveState()
        pdf.setStrokeColor(theme.palette[2], alpha=0.08)
        for x in range(0, int(page_width), theme.texture_step):
            offset = randomizer.randint(-8, 8)
            pdf.line(x, 0, x + offset, page_height)
        pdf.restoreState()

    def _draw_decorative_layers(
        self,
        pdf: canvas.Canvas,
        theme: PdfTheme,
        page_width: float,
        page_height: float,
        randomizer: random.Random,
    ) -> None:
        pdf.saveState()
        pdf.setFillColor(theme.palette[2], alpha=0.14)
        for _ in range(theme.splash_count):
            x = randomizer.uniform(0, page_width)
            y = randomizer.uniform(0, page_height)
            r = randomizer.uniform(20, 58)
            pdf.circle(x, y, r, stroke=0, fill=1)
        pdf.restoreState()

        pdf.saveState()
        pdf.setFillColor(theme.palette[2], alpha=0.22)
        for _ in range(theme.stars_count):
            x = randomizer.uniform(20, page_width - 20)
            y = randomizer.uniform(20, page_height - 20)
            pdf.drawString(x, y, "✦")
        for _ in range(theme.number_symbols_count):
            x = randomizer.uniform(20, page_width - 20)
            y = randomizer.uniform(20, page_height - 20)
            pdf.drawString(x, y, str(randomizer.randint(1, 9)))
        pdf.restoreState()

    def _draw_header(
        self,
        pdf: canvas.Canvas,
        theme: PdfTheme,
        font_name: str,
        meta: dict[str, Any],
        tariff: Any,
        page_height: float,
    ) -> None:
        margin = theme.margin
        pdf.saveState()
        pdf.setFillColor(theme.palette[2])
        pdf.setFont(font_name, theme.typography.title_size)
        pdf.drawString(margin, page_height - margin, "Персональный аналитический отчёт")

        subtitle = f"Тариф: {tariff or 'N/A'}"
        report_id = str(meta.get("id") or "")
        if report_id:
            subtitle = f"{subtitle} · Report #{report_id}"
        pdf.setFont(font_name, theme.typography.subtitle_size)
        pdf.drawString(margin, page_height - margin - 24, subtitle)
        pdf.restoreState()

    def _draw_body(
        self,
        pdf: canvas.Canvas,
        theme: PdfTheme,
        font_name: str,
        report_text: str,
        page_width: float,
        page_height: float,
    ) -> None:
        margin = theme.margin
        body_size = theme.typography.body_size
        line_height = int(body_size * theme.typography.line_height_ratio)
        max_width = page_width - margin * 2
        y = page_height - margin - 64

        pdf.setFillColor(theme.palette[2], alpha=0.96)
        pdf.setFont(font_name, body_size)
        for paragraph in (report_text or "").splitlines() or [""]:
            lines = simpleSplit(paragraph or " ", font_name, body_size, max_width)
            for line in lines:
                if y <= margin:
                    pdf.showPage()
                    self._draw_background(pdf, theme, page_width, page_height, random.Random(paragraph))
                    self._draw_decorative_layers(pdf, theme, page_width, page_height, random.Random(paragraph))
                    pdf.setFillColor(theme.palette[2], alpha=0.96)
                    pdf.setFont(font_name, body_size)
                    y = page_height - margin
                pdf.drawString(margin, y, line)
                y -= line_height
            y -= max(int(line_height * 0.3), 2)
