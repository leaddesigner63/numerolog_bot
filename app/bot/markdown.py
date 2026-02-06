from __future__ import annotations

import re
from html import escape as html_escape


def render_markdown_to_html(text: str) -> str:
    if not text:
        return ""

    placeholders: list[tuple[str, str, str]] = []

    def stash(kind: str, value: str) -> str:
        token = f"§§MD_{len(placeholders)}§§"
        placeholders.append((token, kind, value))
        return token

    text = re.sub(
        r"```(.*?)```",
        lambda match: stash("block", match.group(1)),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"`([^`\n]+)`",
        lambda match: stash("inline", match.group(1)),
        text,
    )

    text = html_escape(text)

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(
        r"\|\|(.+?)\|\|",
        r'<span class="tg-spoiler">\1</span>',
        text,
        flags=re.DOTALL,
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<u>\1</u>", text, flags=re.DOTALL)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text, flags=re.DOTALL)
    text = re.sub(
        r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
        r"<i>\1</i>",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(r"_(.+?)_", r"<i>\1</i>", text, flags=re.DOTALL)

    for token, kind, value in placeholders:
        escaped_value = html_escape(value)
        if kind == "block":
            replacement = f"<pre><code>{escaped_value}</code></pre>"
        else:
            replacement = f"<code>{escaped_value}</code>"
        text = text.replace(token, replacement)

    return text
