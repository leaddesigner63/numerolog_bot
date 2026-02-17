#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

WEB_DIR = Path('web')
MATRIX_PATH = WEB_DIR / 'keyword_matrix_100.csv'
TARGET_FILES = {
    '/': WEB_DIR / 'index.html',
    '/prices/': WEB_DIR / 'prices' / 'index.html',
    '/faq/': WEB_DIR / 'faq' / 'index.html',
    '/articles/': WEB_DIR / 'articles' / 'index.html',
}


class ParagraphParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_p = False
        self.current: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() == 'p':
            self.in_p = True
            self.current = []

    def handle_endtag(self, tag: str):
        if tag.lower() == 'p' and self.in_p:
            text = re.sub(r'\s+', ' ', ''.join(self.current)).strip().lower()
            self.paragraphs.append(text)
            self.current = []
            self.in_p = False

    def handle_data(self, data: str):
        if self.in_p:
            self.current.append(data)


def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip().lower()


def load_matrix() -> list[dict[str, str]]:
    if not MATRIX_PATH.exists():
        print(f"[FAIL] Нет файла матрицы: {MATRIX_PATH}")
        sys.exit(1)

    with MATRIX_PATH.open('r', encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))

    if len(rows) != 100:
        print(f"[FAIL] Матрица должна содержать ровно 100 строк, найдено: {len(rows)}")
        sys.exit(1)

    seen: set[str] = set()
    for idx, row in enumerate(rows, start=2):
        key = normalize(row.get('key', ''))
        url = row.get('url', '')
        place = normalize(row.get('точное_место', ''))

        if not key or not url or not place:
            print(f"[FAIL] Пустые поля в строке {idx}")
            sys.exit(1)
        if key in seen:
            print(f"[FAIL] Дублирующийся ключ в матрице: '{key}' (строка {idx})")
            sys.exit(1)
        seen.add(key)
        if url not in TARGET_FILES:
            print(f"[FAIL] Недопустимый URL '{url}' в строке {idx}")
            sys.exit(1)

    return rows


def main() -> int:
    rows = load_matrix()
    keys = [normalize(row['key']) for row in rows]

    target_text_parts: list[str] = []
    for path in TARGET_FILES.values():
        target_text_parts.append(normalize(path.read_text(encoding='utf-8')))

    all_site_text = '\n'.join(target_text_parts)

    legal_html_files = sorted((WEB_DIR / 'legal').rglob('*.html'))
    legal_text_parts = [normalize(path.read_text(encoding='utf-8')) for path in legal_html_files]
    legal_text = '\n'.join(legal_text_parts)

    violations: list[str] = []

    for key in keys:
        pattern = re.compile(rf"(?<![a-zа-я0-9]){re.escape(key)}(?![a-zа-я0-9])")
        count = len(pattern.findall(all_site_text))
        if count > 2:
            violations.append(f"Ключ '{key}' встречается {count} раз(а), допустимо не более 2")
        legal_count = len(pattern.findall(legal_text))
        if legal_count:
            violations.append(f"Ключ '{key}' найден в web/legal/* ({legal_count} вхожд.)")

    for url, path in TARGET_FILES.items():
        parser = ParagraphParser()
        parser.feed(path.read_text(encoding='utf-8'))
        for idx, paragraph in enumerate(parser.paragraphs, start=1):
            hits = []
            for key in keys:
                pattern = re.compile(rf"(?<![a-zа-я0-9]){re.escape(key)}(?![a-zа-я0-9])")
                if pattern.search(paragraph):
                    hits.append(key)
            if len(hits) > 1:
                violations.append(
                    f"{path}: абзац #{idx} содержит более 1 ключа: {', '.join(hits[:5])}"
                )

    faq_phrase = 'альтернативный формат: нумерология + ии'
    index_text = normalize(TARGET_FILES['/'].read_text(encoding='utf-8'))
    if faq_phrase not in index_text or 'href="/faq/"' not in TARGET_FILES['/'].read_text(encoding='utf-8').lower():
        violations.append("На главной нет требуемой формулировки для кластера 'натальная карта' со ссылкой на /faq/")

    if violations:
        print('[FAIL] Проверка SEO-матрицы не пройдена:')
        for item in violations:
            print(f' - {item}')
        return 1

    print('[OK] SEO-матрица валидна: 100 строк, ограничения по ключам соблюдены.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
