"""生成每期播客的 shownotes：本期大纲 + 关键新闻链接。

- 大纲：从脚本顶部注释里的 `outline:` 块解析（由 /daily-podcast 或 LLM 写入）。
- 关键链接：从当天 digest（reports/DATE.md）里抽取所有 Markdown 链接并去重。
用于 RSS feed 的 <description>/<content:encoded> 与站点节目卡片。
"""
from __future__ import annotations

import html
import re

from . import config

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_OUTLINE_RE = re.compile(r"<!--\s*outline:\s*(.*?)-->", re.S)


def _outline(date: str) -> list[str]:
    p = config.PODCASTS_DIR / f"{date}-script.md"
    if not p.exists():
        return []
    m = _OUTLINE_RE.search(p.read_text(encoding="utf-8"))
    if not m:
        return []
    items = []
    for line in m.group(1).splitlines():
        line = line.strip().lstrip("-•·").strip()
        if line:
            items.append(line)
    return items


def _links(date: str, limit: int = 20) -> list[tuple[str, str]]:
    p = config.REPORTS_DIR / f"{date}.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for m in _LINK_RE.finditer(text):
        title, url = m.group(1).strip(), m.group(2).strip()
        if url in seen:
            continue
        seen.add(url)
        out.append((title, url))
        if len(out) >= limit:
            break
    return out


def build_notes(date: str) -> dict:
    """返回 {text, html, outline, links}。"""
    outline = _outline(date)
    links = _links(date)

    text_lines: list[str] = []
    if outline:
        text_lines.append("本期大纲：")
        text_lines += [f"· {o}" for o in outline]
    if links:
        if text_lines:
            text_lines.append("")
        text_lines.append("关键新闻链接：")
        text_lines += [f"· {t}  {u}" for t, u in links]
    text = "\n".join(text_lines)

    html_parts: list[str] = []
    if outline:
        html_parts.append(
            "<p><strong>本期大纲</strong></p><ul>"
            + "".join(f"<li>{html.escape(o)}</li>" for o in outline)
            + "</ul>")
    if links:
        html_parts.append(
            "<p><strong>关键新闻链接</strong></p><ul>"
            + "".join(
                f'<li><a href="{html.escape(u)}">{html.escape(t)}</a></li>'
                for t, u in links)
            + "</ul>")
    return {"text": text, "html": "".join(html_parts),
            "outline": outline, "links": links}
