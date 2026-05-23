"""模块2 应用层：从数据仓库取时间窗数据，生成 digest 报告。

LLM 可用 -> 调用 Anthropic API 生成结构化分析。
LLM 不可用 -> 生成模板版 digest（保证有产出），并导出 prompt 供 Claude Code 会话补全。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config, llm, store


def _window_items(window_hours: int, max_per_source: int) -> dict[str, list[dict]]:
    since = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    rows = store.query_window(since)
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["source"], [])
        if len(grouped[r["source"]]) < max_per_source:
            grouped[r["source"]].append(r)
    return grouped


def _items_to_text(grouped: dict[str, list[dict]]) -> str:
    lines: list[str] = []
    labels = {"github": "GitHub Trending", "hackernews": "Hacker News", "rss": "RSS 资讯"}
    for src, items in grouped.items():
        lines.append(f"\n## 来源：{labels.get(src, src)}（{len(items)} 条）")
        for it in items:
            extra = []
            if it.get("score"):
                extra.append(f"热度{it['score']}")
            if it.get("lang"):
                extra.append(it["lang"])
            meta = it.get("meta", {})
            if meta.get("comments"):
                extra.append(f"{meta['comments']}评论")
            if meta.get("feed"):
                extra.append(meta["feed"])
            tag = f"（{', '.join(extra)}）" if extra else ""
            lines.append(f"- {it['title']} {tag}\n  {it.get('url','')}")
            if it.get("summary"):
                lines.append(f"  摘要：{it['summary']}")
    return "\n".join(lines)


def _template_digest(date_str: str, grouped: dict[str, list[dict]]) -> str:
    total = sum(len(v) for v in grouped.values())
    out = [
        f"# 每日科技资讯报告 - {date_str}",
        "",
        f"**生成时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"**数据规模**: {total} 条（来自 {len(grouped)} 个来源）  ",
        "**生成方式**: 模板版（未启用 LLM，可由 Claude Code 会话增强）",
        "",
        "---",
    ]
    section_titles = {
        "github": "## 🔥 GitHub 热门项目",
        "hackernews": "## 📰 Hacker News 要点",
        "rss": "## 🌐 行业资讯",
    }
    for src in ("github", "hackernews", "rss"):
        items = grouped.get(src)
        if not items:
            continue
        out += ["", section_titles.get(src, f"## {src}"), ""]
        for i, it in enumerate(items, 1):
            bits = []
            if it.get("score"):
                bits.append(f"⭐ {it['score']}")
            if it.get("lang"):
                bits.append(it["lang"])
            meta = it.get("meta", {})
            if meta.get("comments"):
                bits.append(f"💬 {meta['comments']}")
            suffix = f" — {' | '.join(bits)}" if bits else ""
            out.append(f"{i}. [{it['title']}]({it.get('url','')}){suffix}")
            if it.get("summary"):
                out.append(f"   - {it['summary']}")
    out += ["", "---", "", "*由每日科技资讯系统自动生成*"]
    return "\n".join(out)


def analyze(date_str: str | None = None, window_hours: int | None = None) -> Path:
    cfg = config.load_config()["analyzer"]
    window_hours = window_hours or cfg.get("window_hours", 24)
    max_per_source = cfg.get("max_items_per_source", 15)
    date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    grouped = _window_items(window_hours, max_per_source)
    total = sum(len(v) for v in grouped.values())
    print(f"  时间窗内数据：{total} 条 / {len(grouped)} 个来源")
    if total == 0:
        print("  [warn] 时间窗内无数据，请先运行 collect。")

    config.ensure_dirs()
    out_path = config.REPORTS_DIR / f"{date_str}.md"
    data_text = _items_to_text(grouped)

    if llm.available():
        system = (config.PROMPTS_DIR / "digest_system.txt").read_text(encoding="utf-8")
        user = f"日期：{date_str}\n以下是当日采集到的原始条目：\n{data_text}"
        print("  调用 Anthropic API 生成 digest…")
        content = llm.complete(system, user)
        out_path.write_text(content, encoding="utf-8")
        print(f"  ✓ 已生成（LLM）: {out_path}")
    else:
        out_path.write_text(_template_digest(date_str, grouped), encoding="utf-8")
        prompt_path = config.RAW_DIR / f"{date_str}-digest.prompt.txt"
        system = (config.PROMPTS_DIR / "digest_system.txt").read_text(encoding="utf-8")
        prompt_path.write_text(
            system + "\n\n=== 当日原始条目 ===\n" + data_text, encoding="utf-8")
        print(f"  ✓ 已生成模板版 digest: {out_path}")
        print(f"  ↳ 会话模式 prompt 已导出: {prompt_path}")
        print("    （配置 ANTHROPIC_API_KEY 后将自动生成高质量分析，"
              "或由 Claude Code 会话读取该 prompt 生成并覆盖报告）")
    return out_path
