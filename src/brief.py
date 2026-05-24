"""每日早间简报：昨夜采集运维状态 + 今日要点（Top 条目）。

比完整 digest 更短，适合早上快速扫一眼。LLM 可用时生成一段导读，否则用模板。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, llm, store

_LABELS = {"github": "GitHub", "hackernews": "Hacker News", "rss": "RSS"}


def _overnight_ops(hours: int = 16) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    runs = [r for r in store.recent_runs(50) if r["started_utc"] >= since]
    return {
        "runs": len(runs),
        "fetched": sum(r["fetched"] for r in runs),
        "inserted": sum(r["inserted"] for r in runs),
        "sources_ok": _sources_health(runs),
    }


def _sources_health(runs: list[dict]) -> dict:
    health: dict[str, str] = {}
    for r in runs:
        for k, v in r.get("per_source", {}).items():
            if v.get("status") == "ok":
                health.setdefault(k, "ok")
            else:
                health[k] = "error"
    return health


def _balanced_top(rows: list[dict], per_source: int = 3) -> list[dict]:
    """各来源各取热度前 N，避免 GitHub 星数压制 HN/RSS，得到跨源均衡的要点。"""
    buckets: dict[str, list[dict]] = {}
    for r in rows:  # rows 已按 score 降序
        b = buckets.setdefault(r["source"], [])
        if len(b) < per_source:
            b.append(r)
    order = ["github", "hackernews", "rss"]
    out: list[dict] = []
    for src in order:
        out.extend(buckets.get(src, []))
    for src, b in buckets.items():
        if src not in order:
            out.extend(b)
    return out


def _podcast_teaser(date_str: str, items: list[dict]) -> str:
    """今日播客一句话导读：LLM 可用时生成，否则从脚本中提取嘉宾的看点句。"""
    script_path = config.PODCASTS_DIR / f"{date_str}-script.md"
    if not script_path.exists():
        return ""
    text = script_path.read_text(encoding="utf-8")
    if "（待生成）" in text:  # 占位脚本，无可用内容
        return ""
    if llm.available():
        try:
            sys = "用一句不超过40字的中文，为这期科技播客写一句吸引人的导读。只输出这句话。"
            dialogue = "\n".join(l for l in text.splitlines()
                                 if l.startswith(("主持人A：", "嘉宾B：")))
            return llm.complete(sys, dialogue[:1500], max_tokens=120).strip()
        except Exception:  # noqa: BLE001
            pass
    # 回退：取嘉宾B第一句带"看点/剧透"的台词，否则取其首句
    b_lines = [l.split("：", 1)[1] for l in text.splitlines() if l.startswith("嘉宾B：")]
    for ln in b_lines:
        if "看点" in ln:
            return ln[ln.find("看点") + 2:].lstrip("：:，, ").strip() or ln.strip()
    return b_lines[0].strip() if b_lines else ""


def generate(date_str: str | None = None, window_hours: int = 24) -> Path:
    date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    since = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    items = _balanced_top(store.query_window(since), per_source=3)
    ops = _overnight_ops()

    config.ensure_dirs()
    briefs_dir = config.ROOT / "briefs"
    briefs_dir.mkdir(exist_ok=True)
    out = briefs_dir / f"{date_str}-brief.md"

    health_str = " ｜ ".join(
        f"{_LABELS.get(k,k)} {'✅' if s=='ok' else '⚠️'}"
        for k, s in ops["sources_ok"].items()) or "（无运行记录）"

    top_lines = []
    for it in items[:8]:
        tag = f"⭐{it['score']}" if it.get("score") else ""
        top_lines.append(f"- [{it['title']}]({it.get('url','')}) {tag} · {_LABELS.get(it['source'], it['source'])}")

    narrative = ""
    if llm.available() and items:
        try:
            sys = ("你是科技简报编辑。用 3-4 句中文，为下面的今日科技要点写一段"
                   "提纲挈领的早间导读，点出最值得关注的 1-2 件事。只输出导读正文。")
            usr = "\n".join(f"- {it['title']}（{_LABELS.get(it['source'],it['source'])}, 热度{it.get('score',0)}）" for it in items)
            narrative = llm.complete(sys, usr, max_tokens=400)
        except Exception:  # noqa: BLE001
            narrative = ""

    md = [
        f"# ☀️ 每日科技早报 - {date_str}",
        "",
        f"_生成于 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "## 🛠 采集运维状态（过去约 16 小时）",
        "",
        f"- 采集运行 **{ops['runs']}** 次，抓取 {ops['fetched']} 条，新增 **{ops['inserted']}** 条",
        f"- 数据源健康：{health_str}",
        f"- 数据仓库累计：{store.stats()['total']} 条",
        "",
        "## 📌 今日要点",
        "",
    ]
    if narrative:
        md += [f"> {narrative}", ""]
    md += top_lines if top_lines else ["（时间窗内暂无数据，请检查采集是否正常）"]

    teaser = _podcast_teaser(date_str, items)
    md += ["", "## 🎙 今日播客"]
    if teaser:
        md.append(f"> {teaser}")
    md.append(f"- 脚本：`podcasts/{date_str}-script.md`")

    md += [
        "",
        "## 🔗 延伸",
        f"- 完整汇总：`reports/{date_str}.md`",
        "- 运维看板：`DASHBOARD.md`",
        "",
        "---",
        "_由每日科技资讯系统自动生成_",
        "",
    ]
    out.write_text("\n".join(md), encoding="utf-8")
    return out
