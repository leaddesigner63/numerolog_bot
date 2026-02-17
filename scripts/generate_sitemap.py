#!/usr/bin/env python3
"""Генерация web/sitemap.xml на основе файлов каталога web/."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
SITEMAP_PATH = WEB_DIR / "sitemap.xml"
BASE_URL = os.getenv("SITEMAP_BASE_URL", "https://aireadu.ru").rstrip("/")


@dataclass(frozen=True)
class UrlMeta:
    changefreq: str
    priority: str


URL_META: dict[str, UrlMeta] = {
    "/": UrlMeta(changefreq="daily", priority="1.0"),
    "/prices/": UrlMeta(changefreq="weekly", priority="0.9"),
    "/faq/": UrlMeta(changefreq="weekly", priority="0.8"),
    "/articles/": UrlMeta(changefreq="daily", priority="0.9"),
    "/contacts/": UrlMeta(changefreq="monthly", priority="0.6"),
}

ARTICLE_META = UrlMeta(changefreq="monthly", priority="0.7")
DEFAULT_META = UrlMeta(changefreq="monthly", priority="0.5")


def file_lastmod(path: Path) -> str:
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return modified_at.date().isoformat()


def path_to_url(path: Path) -> str:
    relative = path.relative_to(WEB_DIR)
    if relative.name == "index.html":
        parent = relative.parent.as_posix()
        if parent == ".":
            return "/"
        return f"/{parent}/"
    if relative.name == "404.html":
        return ""
    return f"/{relative.as_posix()}"


def detect_meta(url_path: str) -> UrlMeta:
    if url_path in URL_META:
        return URL_META[url_path]
    if url_path.startswith("/articles/"):
        return ARTICLE_META
    return DEFAULT_META


def collect_urls() -> list[tuple[str, str, UrlMeta]]:
    entries: list[tuple[str, str, UrlMeta]] = []

    for html_path in sorted(WEB_DIR.rglob("*.html")):
        url_path = path_to_url(html_path)
        if not url_path:
            continue
        if url_path.startswith("/legal/"):
            continue
        meta = detect_meta(url_path)
        entries.append((url_path, file_lastmod(html_path), meta))

    return entries


def render_xml(entries: list[tuple[str, str, UrlMeta]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url_path, lastmod, meta in entries:
        lines.extend(
            [
                "  <url>",
                f"    <loc>{BASE_URL}{url_path}</loc>",
                f"    <lastmod>{lastmod}</lastmod>",
                f"    <changefreq>{meta.changefreq}</changefreq>",
                f"    <priority>{meta.priority}</priority>",
                "  </url>",
            ]
        )
    lines.append("</urlset>")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    entries = collect_urls()
    if not entries:
        raise SystemExit("Не найдены HTML-файлы для sitemap.")
    SITEMAP_PATH.write_text(render_xml(entries), encoding="utf-8")
    print(f"sitemap сгенерирован: {SITEMAP_PATH}")


if __name__ == "__main__":
    main()
