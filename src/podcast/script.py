"""模块3a：基于 digest 生成双人对话播客脚本。

LLM 可用 -> 调用 Anthropic API 生成约 15 分钟双人对话稿。
LLM 不可用 -> 导出 prompt 供 Claude Code 会话补全，并写一个含 front-matter 的占位脚本。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .. import config, llm


def _front_matter(date_str: str, target_minutes: int, hosts: dict) -> str:
    a, b = hosts["A"], hosts["B"]
    return (
        f"<!--\n"
        f"date: {date_str}\n"
        f"target_minutes: {target_minutes}\n"
        f"voice_A: {a['name']} ({a['voice']})\n"
        f"voice_B: {b['name']} ({b['voice']})\n"
        f"-->\n\n"
        f"# 每日科技播客 - {date_str}\n\n"
        f"> 主持人A：{a['name']}（{a['voice']}）｜ 嘉宾B：{b['name']}（{b['voice']}）\n\n"
        f"---\n\n"
    )


_PLACEHOLDER_MARK = "（待生成）"


def generate(date_str: str | None = None, force: bool = False) -> Path:
    pcfg = config.load_config()["podcast"]
    date_str = date_str or config.today_str()
    target_minutes = pcfg.get("target_minutes", 15)
    hosts = pcfg["hosts"]

    config.ensure_dirs()
    out_path = config.PODCASTS_DIR / f"{date_str}-script.md"

    # 会话模式下若已存在真实脚本（非占位），不覆盖，避免再次运行清空已生成内容。
    if (not force and not llm.available() and out_path.exists()
            and _PLACEHOLDER_MARK not in out_path.read_text(encoding="utf-8")):
        print(f"  已存在脚本，保留不覆盖: {out_path}（如需重建用 --force）")
        return out_path

    report_path = config.REPORTS_DIR / f"{date_str}.md"
    if not report_path.exists():
        raise FileNotFoundError(
            f"未找到当日 digest：{report_path}，请先运行 analyze。")
    digest = report_path.read_text(encoding="utf-8")

    fm = _front_matter(date_str, target_minutes, hosts)

    if llm.available():
        system = (config.PROMPTS_DIR / "podcast_system.txt").read_text(encoding="utf-8")
        char_target = target_minutes * pcfg.get("chars_per_minute", 280)
        user = (
            f"日期：{date_str}\n目标篇幅：约 {char_target} 字。\n"
            f"主持人A名为{hosts['A']['name']}，嘉宾B名为{hosts['B']['name']}。\n\n"
            f"以下是当日科技汇总报告：\n\n{digest}"
        )
        print("  调用 Anthropic API 生成播客脚本…")
        dialogue = llm.complete(system, user)
        out_path.write_text(fm + dialogue, encoding="utf-8")
        print(f"  ✓ 已生成（LLM）: {out_path}")
    else:
        system = (config.PROMPTS_DIR / "podcast_system.txt").read_text(encoding="utf-8")
        prompt_path = config.RAW_DIR / f"{date_str}-podcast.prompt.txt"
        prompt_path.write_text(
            system + "\n\n=== 当日 digest ===\n" + digest, encoding="utf-8")
        placeholder = (
            fm
            + "主持人A：（待生成）配置 ANTHROPIC_API_KEY 后将自动生成双人对话稿，"
            "或由 Claude Code 会话读取下方 prompt 生成并覆盖本文件。\n"
            f"嘉宾B：会话模式 prompt 已导出至 {prompt_path}。\n"
        )
        out_path.write_text(placeholder, encoding="utf-8")
        print(f"  ✓ 已生成占位脚本: {out_path}")
        print(f"  ↳ 会话模式 prompt 已导出: {prompt_path}")
    return out_path
