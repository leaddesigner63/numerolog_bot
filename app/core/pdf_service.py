from __future__ import annotations

import logging
import os
import random
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from importlib.util import find_spec
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.core.config import settings
from app.core.report_document import ReportDocument, report_document_builder
from app.core.pdf_theme_config import PdfThemeAssetBundle, resolve_pdf_asset_bundle
from app.core.pdf_themes import PdfTheme, resolve_pdf_theme


_FONT_REGULAR_NAME = "NumerologRegular"
_FONT_BOLD_NAME = "NumerologBold"
_FONT_ACCENT_NAME = "NumerologAccent"
_FONT_FALLBACK_NAME = "Helvetica"

_FONT_FAMILY: dict[str, str] | None = None
_BOTO3_AVAILABLE = find_spec("boto3") is not None
if _BOTO3_AVAILABLE:
    import boto3


_ZERO_WIDTH_CHARS = {
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\u2060",  # WORD JOINER
    "\ufeff",  # ZERO WIDTH NO-BREAK SPACE
}


def _register_font() -> dict[str, str]:
    global _FONT_FAMILY
    if _FONT_FAMILY is not None:
        return _FONT_FAMILY

    logger = logging.getLogger(__name__)
    regular_font = _register_font_variant(
        font_name=_FONT_REGULAR_NAME,
        variant="regular",
        paths=_resolve_font_paths_for_variant("regular"),
        logger=logger,
    )
    bold_font = _register_font_variant(
        font_name=_FONT_BOLD_NAME,
        variant="bold",
        paths=_resolve_font_paths_for_variant("bold"),
        logger=logger,
    )
    accent_font = _register_font_variant(
        font_name=_FONT_ACCENT_NAME,
        variant="accent",
        paths=_resolve_font_paths_for_variant("accent"),
        logger=logger,
    )

    if bold_font in {_FONT_FALLBACK_NAME, "Helvetica-Bold"}:
        bold_font = regular_font
    if accent_font == _FONT_FALLBACK_NAME:
        accent_font = regular_font

    family: dict[str, str] = {
        "body": regular_font,
        "title": bold_font,
        "subtitle": bold_font,
        "numeric": accent_font,
    }
    _FONT_FAMILY = family
    return family


def _register_font_variant(
    *,
    font_name: str,
    variant: str,
    paths: list[Path],
    logger: logging.Logger,
) -> str:
    for font_path in paths:
        if not font_path.exists():
            logger.warning(
                "pdf_font_path_missing",
                extra={"variant": variant, "font_path": str(font_path)},
            )
            continue
        try:
            pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
            return font_name
        except Exception as exc:
            logger.warning(
                "pdf_font_register_failed",
                extra={"variant": variant, "font_path": str(font_path), "error": str(exc)},
            )

    fallback = _FONT_FALLBACK_NAME
    if variant == "bold":
        fallback = "Helvetica-Bold"
    logger.warning(
        "pdf_font_variant_fallback",
        extra={"variant": variant, "fallback": fallback},
    )
    return fallback


def _resolve_font_paths_for_variant(variant: str) -> list[Path]:
    fonts_dir = Path(__file__).resolve().parents[1] / "assets" / "fonts"

    configured_path: str | None
    legacy_path = settings.pdf_font_path
    if variant == "regular":
        configured_path = settings.pdf_font_regular_path or legacy_path
        bundled = [fonts_dir / "DejaVuSans.ttf"]
    elif variant == "bold":
        configured_path = settings.pdf_font_bold_path
        bundled = [fonts_dir / "DejaVuSans-Bold.ttf", fonts_dir / "DejaVuSans.ttf"]
    else:
        configured_path = settings.pdf_font_accent_path
        bundled = [
            fonts_dir / "DejaVuSerif.ttf",
            fonts_dir / "DejaVuSans.ttf",
        ]

    paths: list[Path] = []
    if configured_path:
        paths.append(Path(configured_path))
    paths.extend(bundled)
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
        report_document: ReportDocument | None = None,
    ) -> bytes:
        renderer = PdfThemeRenderer(logger=self._logger)
        structured_document = report_document or report_document_builder.build(
            text,
            tariff=tariff,
            meta=meta,
        )
        try:
            return renderer.render(text, tariff, meta, report_document=structured_document)
        except Exception as exc:
            self._logger.warning(
                "pdf_theme_render_failed",
                extra={"error": str(exc), "tariff": str(tariff or "unknown")},
            )
            return self._generate_legacy_pdf(text)

    def _generate_legacy_pdf(self, text: str) -> bytes:
        font_map = _register_font()
        font_name = font_map["body"]
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
        report_document: ReportDocument | None = None,
    ) -> bytes:
        font_map = _register_font()
        theme = resolve_pdf_theme(tariff)
        payload_meta = meta or {}
        seed_basis = f"{payload_meta.get('id', '')}-{payload_meta.get('created_at', '')}-{tariff}"
        randomizer = random.Random(seed_basis)
        asset_bundle = resolve_pdf_asset_bundle(str(tariff or ""))

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        page_width, page_height = A4

        self._draw_background(pdf, theme, page_width, page_height, randomizer, asset_bundle)
        self._draw_decorative_layers(pdf, theme, page_width, page_height, randomizer, asset_bundle)
        body_start_y = self._draw_header(
            pdf,
            theme,
            font_map,
            payload_meta,
            tariff,
            page_width,
            page_height,
            report_document=report_document,
        )
        self._draw_body(
            pdf,
            theme,
            font_map,
            report_text,
            page_width,
            page_height,
            asset_bundle,
            body_start_y=body_start_y,
            report_document=report_document,
        )

        pdf.save()
        return buffer.getvalue()

    def _draw_background(
        self,
        pdf: canvas.Canvas,
        theme: PdfTheme,
        page_width: float,
        page_height: float,
        randomizer: random.Random,
        asset_bundle: PdfThemeAssetBundle,
    ) -> None:
        if self._try_draw_image_layer(
            pdf,
            layer_type="background",
            primary=asset_bundle.background_main,
            fallback=asset_bundle.background_fallback,
            x=0,
            y=0,
            width=page_width,
            height=page_height,
        ):
            return

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
        asset_bundle: PdfThemeAssetBundle,
    ) -> None:
        self._try_draw_image_layer(
            pdf,
            layer_type="overlay",
            primary=asset_bundle.overlay_main,
            fallback=asset_bundle.overlay_fallback,
            x=0,
            y=0,
            width=page_width,
            height=page_height,
        )
        self._try_draw_image_layer(
            pdf,
            layer_type="icon",
            primary=asset_bundle.icon_main,
            fallback=asset_bundle.icon_fallback,
            x=page_width - 72,
            y=page_height - 72,
            width=40,
            height=40,
        )

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
        font_map: dict[str, str],
        meta: dict[str, Any],
        tariff: Any,
        page_width: float,
        page_height: float,
        report_document: ReportDocument | None = None,
    ) -> float:
        margin = theme.margin
        max_width = page_width - margin * 2
        title_size = theme.typography.title_size
        subtitle_size = theme.typography.subtitle_size
        title_line_height = int(title_size * theme.typography.line_height_ratio)
        subtitle_line_height = int(subtitle_size * theme.typography.line_height_ratio)

        pdf.saveState()
        pdf.setFillColor(theme.palette[2])
        title = (report_document.title if report_document else "") or "Персональный аналитический отчёт"
        title_lines = self._split_text_into_visual_lines(title, font_map["title"], title_size, max_width)
        y = page_height - margin
        pdf.setFont(font_map["title"], title_size)
        for line in title_lines:
            pdf.drawString(margin, y, line)
            y -= title_line_height

        y -= max(int(title_line_height * 0.2), 4)

        subtitle = (report_document.subtitle if report_document else "") or f"Тариф: {tariff or 'N/A'}"
        report_id = str(meta.get("id") or "")
        if report_id:
            subtitle = f"{subtitle} · Report #{report_id}"
        subtitle_lines = self._split_text_into_visual_lines(
            subtitle,
            font_map["subtitle"],
            subtitle_size,
            max_width,
        )
        pdf.setFont(font_map["subtitle"], subtitle_size)
        for line in subtitle_lines:
            pdf.drawString(margin, y, line)
            y -= subtitle_line_height
        pdf.restoreState()

        return y - max(int(subtitle_line_height * 0.4), 8)

    def _draw_body(
        self,
        pdf: canvas.Canvas,
        theme: PdfTheme,
        font_map: dict[str, str],
        report_text: str,
        page_width: float,
        page_height: float,
        asset_bundle: PdfThemeAssetBundle,
        body_start_y: float,
        report_document: ReportDocument | None = None,
    ) -> None:
        margin = theme.margin
        body_size = theme.typography.body_size
        line_height = int(body_size * theme.typography.line_height_ratio)
        max_width = page_width - margin * 2
        y = body_start_y
        self._draw_content_surface(pdf, theme, page_width, page_height)

        if not report_document:
            y = self._draw_raw_text_block(
                pdf,
                text=report_text,
                y=y,
                margin=margin,
                width=max_width,
                font=font_map["body"],
                numeric_font=font_map["numeric"],
                size=body_size,
                page_width=page_width,
                page_height=page_height,
                theme=theme,
                asset_bundle=asset_bundle,
            )
            return

        section_gap = max(line_height, 14)
        key_gap = max(int(line_height * 0.6), 8)
        effective_width = max_width - 8 * report_document.decoration_depth

        y = self._draw_text_block(
            pdf,
            text="Ключевые выводы",
            y=y,
            margin=margin,
            width=effective_width,
            font=font_map["subtitle"],
            size=body_size + 1,
            page_width=page_width,
            page_height=page_height,
            theme=theme,
            asset_bundle=asset_bundle,
        )
        for finding in report_document.key_findings:
            y = self._draw_text_block(
                pdf,
                text=f"• {finding}",
                y=y,
                margin=margin + 8,
                width=effective_width - 8,
                font=font_map["body"],
                size=body_size,
                page_width=page_width,
                page_height=page_height,
                theme=theme,
                asset_bundle=asset_bundle,
            )
            y -= key_gap // 2

        for section in report_document.sections:
            y -= section_gap
            y = self._draw_text_block(
                pdf,
                text=section.title,
                y=y,
                margin=margin,
                width=effective_width,
                font=font_map["subtitle"],
                size=body_size + 1,
                page_width=page_width,
                page_height=page_height,
                theme=theme,
                asset_bundle=asset_bundle,
            )
            for paragraph in section.paragraphs:
                y = self._draw_text_block(
                    pdf,
                    text=paragraph,
                    y=y,
                    margin=margin + 6,
                    width=effective_width - 6,
                    font=font_map["body"],
                    size=body_size,
                    page_width=page_width,
                    page_height=page_height,
                    theme=theme,
                    asset_bundle=asset_bundle,
                )
            for bullet in section.bullets:
                y = self._draw_text_block(
                    pdf,
                    text=f"• {bullet}",
                    y=y,
                    margin=margin + 10,
                    width=effective_width - 10,
                    font=font_map["body"],
                    size=body_size,
                    page_width=page_width,
                    page_height=page_height,
                    theme=theme,
                    asset_bundle=asset_bundle,
                )
            for accent in section.accent_blocks:
                y = self._draw_text_block(
                    pdf,
                    text=f"Акцент: {accent.title}",
                    y=y,
                    margin=margin + 12,
                    width=effective_width - 12,
                    font=font_map["subtitle"],
                    size=body_size,
                    page_width=page_width,
                    page_height=page_height,
                    theme=theme,
                    asset_bundle=asset_bundle,
                )
                for point in accent.points:
                    y = self._draw_text_block(
                        pdf,
                        text=f"– {point}",
                        y=y,
                        margin=margin + 18,
                        width=effective_width - 18,
                        font=font_map["body"],
                        size=body_size,
                        page_width=page_width,
                        page_height=page_height,
                        theme=theme,
                        asset_bundle=asset_bundle,
                    )

        y -= section_gap
        self._draw_text_block(
            pdf,
            text=report_document.disclaimer,
            y=y,
            margin=margin,
            width=effective_width,
            font=font_map["body"],
            size=max(body_size - 1, 8),
            page_width=page_width,
            page_height=page_height,
            theme=theme,
            asset_bundle=asset_bundle,
        )

    def _draw_raw_text_block(
        self,
        pdf: canvas.Canvas,
        *,
        text: str,
        y: float,
        margin: float,
        width: float,
        font: str,
        numeric_font: str,
        size: int,
        page_width: float,
        page_height: float,
        theme: PdfTheme,
        asset_bundle: PdfThemeAssetBundle,
    ) -> float:
        line_height = int(size * theme.typography.line_height_ratio)
        for paragraph in self._split_text_into_visual_lines(text or "", font, size, width):
            if y <= theme.margin:
                pdf.showPage()
                page_randomizer = random.Random(paragraph)
                self._draw_background(pdf, theme, page_width, page_height, page_randomizer, asset_bundle)
                self._draw_decorative_layers(pdf, theme, page_width, page_height, page_randomizer, asset_bundle)
                self._draw_content_surface(pdf, theme, page_width, page_height)
                y = page_height - theme.margin
            line_font = numeric_font if any(ch.isdigit() for ch in paragraph) else font
            pdf.setFillColor(theme.palette[2], alpha=0.96)
            pdf.setFont(line_font, size)
            pdf.drawString(margin, y, paragraph)
            y -= line_height
        return y - max(int(line_height * 0.25), 2)

    def _split_text_into_visual_lines(
        self,
        text: str,
        font: str,
        size: int,
        width: float,
    ) -> list[str]:
        if not text:
            return [""]

        prepared_text = self._prepare_text_for_pdf(text)

        lines: list[str] = []
        source_lines = prepared_text.split("\n")
        for source_line in source_lines:
            if source_line == "":
                lines.append("")
                continue
            lines.extend(self._split_line_by_width(source_line, font, size, width))
        return lines

    def _split_line_by_width(
        self,
        line: str,
        font: str,
        size: int,
        width: float,
    ) -> list[str]:
        if line == "":
            return [""]

        chunks: list[str] = []
        current = ""
        tokens = re.findall(r"\S+\s*|\s+", line)
        for token in tokens:
            candidate = f"{current}{token}"
            token_width = pdfmetrics.stringWidth(token, font, size)
            candidate_width = pdfmetrics.stringWidth(candidate, font, size)

            if not current and token_width > width:
                token_chunks = self._split_long_token_by_width(token, font, size, width)
                chunks.extend(token_chunks[:-1])
                current = token_chunks[-1] if token_chunks else ""
                continue

            if current and candidate_width > width:
                chunks.append(current)
                if token_width > width:
                    token_chunks = self._split_long_token_by_width(token, font, size, width)
                    chunks.extend(token_chunks[:-1])
                    current = token_chunks[-1] if token_chunks else ""
                else:
                    current = token
                continue
            current = candidate
        if current:
            chunks.append(current)
        return chunks

    def _split_long_token_by_width(
        self,
        token: str,
        font: str,
        size: int,
        width: float,
    ) -> list[str]:
        parts: list[str] = []
        current = ""
        for char in token:
            candidate = f"{current}{char}"
            if current and pdfmetrics.stringWidth(candidate, font, size) > width:
                parts.append(current)
                current = char
                continue
            current = candidate
        if current:
            parts.append(current)
        return parts or [""]

    def _prepare_text_for_pdf(self, text: str) -> str:
        if not text:
            return ""

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        prepared_chars: list[str] = []
        for char in normalized:
            if char in _ZERO_WIDTH_CHARS:
                continue
            code = ord(char)
            if code < 32 and char not in {"\n", "\t"}:
                continue
            prepared_chars.append(char)
        return "".join(prepared_chars)

    def _draw_text_block(
        self,
        pdf: canvas.Canvas,
        *,
        text: str,
        y: float,
        margin: float,
        width: float,
        font: str,
        size: int,
        page_width: float,
        page_height: float,
        theme: PdfTheme,
        asset_bundle: PdfThemeAssetBundle,
    ) -> float:
        line_height = int(size * theme.typography.line_height_ratio)
        lines = self._split_text_into_visual_lines(text or "", font, size, width)
        for line in lines:
            if y <= theme.margin:
                pdf.showPage()
                page_randomizer = random.Random(line)
                self._draw_background(pdf, theme, page_width, page_height, page_randomizer, asset_bundle)
                self._draw_decorative_layers(pdf, theme, page_width, page_height, page_randomizer, asset_bundle)
                self._draw_content_surface(pdf, theme, page_width, page_height)
                y = page_height - theme.margin
            line_font = font
            if font != _FONT_FALLBACK_NAME and any(ch.isdigit() for ch in line):
                line_font = font
            pdf.setFillColor(theme.palette[2], alpha=0.96)
            pdf.setFont(line_font, size)
            pdf.drawString(margin, y, line)
            y -= line_height
        return y - max(int(line_height * 0.25), 2)

    def _draw_content_surface(
        self,
        pdf: canvas.Canvas,
        theme: PdfTheme,
        page_width: float,
        page_height: float,
    ) -> None:
        panel_margin = theme.margin - 8
        panel_top_gap = 52
        panel_height = page_height - (panel_margin * 2) - panel_top_gap

        pdf.saveState()
        pdf.setFillColorRGB(1, 1, 1)
        pdf.setFillAlpha(0.08)
        pdf.setStrokeColor(theme.palette[2], alpha=0.35)
        pdf.setLineWidth(0.8)
        pdf.roundRect(
            panel_margin,
            panel_margin,
            page_width - panel_margin * 2,
            max(panel_height, 120),
            14,
            stroke=1,
            fill=1,
        )
        pdf.restoreState()

    def _try_draw_image_layer(
        self,
        pdf: canvas.Canvas,
        *,
        layer_type: str,
        primary: Path,
        fallback: Path,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> bool:
        for candidate, source in ((primary, "main"), (fallback, "fallback")):
            if not candidate.exists():
                self._logger.warning(
                    "pdf_theme_asset_missing",
                    extra={"layer": layer_type, "source": source, "path": str(candidate)},
                )
                continue
            try:
                pdf.drawImage(
                    str(candidate),
                    x,
                    y,
                    width=width,
                    height=height,
                    preserveAspectRatio=False,
                    mask="auto",
                )
                return True
            except Exception as exc:
                self._logger.warning(
                    "pdf_theme_asset_draw_failed",
                    extra={
                        "layer": layer_type,
                        "source": source,
                        "path": str(candidate),
                        "error": str(exc),
                    },
                )
        return False
