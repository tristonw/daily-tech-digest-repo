"""运维看板：渲染 DASHBOARD.md（GitHub 可直接查看）与 CLI 实时视图。

回答两个问题：采集到底有没有在后台跑、都在采哪些源。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import config, store

_SOURCE_LABELS = {
    "github": "GitHub Trending",
    "hackernews": "Hacker News",
    "rss": "科技 RSS",
}
_SOURCE_SHORT = {"github": "GH", "hackernews": "HN", "rss": "RSS"}


def _source_registry() -> list[dict]:
    """从 config 读取已配置的数据源（含 RSS feed 明细）。"""
    c = config.load_config()["collector"]
    rows = []
    if c.get("hacker_news", {}).get("enabled"):
        rows.append({"source": "Hacker News", "detail": "topstories API",
                     "enabled": True})
    if c.get("github_trending", {}).get("enabled"):
        rows.append({"source": "GitHub Trending",
                     "detail": f"trending?since={c['github_trending'].get('since','daily')}",
                     "enabled": True})
    if c.get("rss", {}).get("enabled"):
        for feed in c["rss"].get("feeds", []):
            rows.append({"source": f"RSS · {feed.get('name')}",
                         "detail": feed.get("url"), "enabled": True})
    return rows


def _freshness(last_run: dict | None) -> str:
    if not last_run:
        return "⚠️ 尚无采集记录"
    last = datetime.strptime(last_run["started_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)
    mins = (datetime.now(timezone.utc) - last).total_seconds() / 60
    if mins < 240:
        tag = "🟢 正常运行中"
    elif mins < 720:
        tag = "🟡 略有延迟"
    else:
        tag = "🔴 可能已停止"
    return f"{tag}（最近一次 {mins/60:.1f} 小时前）"


def _bar(n: int, max_n: int, width: int = 24) -> str:
    if max_n <= 0:
        return ""
    return "█" * max(1, round(n / max_n * width)) if n else ""


def render_markdown() -> Path:
    rs = store.run_stats()
    st = store.stats()
    daily = store.daily_new_counts(14)
    runs = store.recent_runs(12)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# 📊 采集运维看板",
        "",
        f"_最后更新：{now}_",
        "",
        "## 运行状态",
        "",
        f"- **健康度**：{_freshness(rs['last_run'])}",
        f"- **累计采集运行**：{rs['total_runs']} 次（近 24h：{rs['runs_24h']} 次，近 7 天：{rs['runs_7d']} 次）",
        f"- **数据仓库累计条目**：{st['total']} 条",
    ]
    if st["by_source"]:
        parts = [f"{_SOURCE_LABELS.get(k,k)} {v}" for k, v in st["by_source"].items()]
        lines.append(f"- **各来源累计**：{' ｜ '.join(parts)}")

    lines += ["", "## 数据源清单", "", "| 数据源 | 地址/说明 | 状态 |", "|---|---|---|"]
    for r in _source_registry():
        lines.append(f"| {r['source']} | `{r['detail']}` | {'✅ 启用' if r['enabled'] else '⛔ 关闭'} |")

    lines += ["", "## 近 14 天采集量（新增条目）", "", "```"]
    if daily:
        max_n = max((d["new_items"] or 0) for d in daily)
        for d in daily:
            n = d["new_items"] or 0
            lines.append(f"{d['day']}  {n:>4}  {_bar(n, max_n)}  ({d['runs']} 次运行)")
    else:
        lines.append("（暂无数据）")
    lines.append("```")

    lines += ["", "## 最近运行明细", "",
              "| 开始时间(UTC) | 抓取 | 新增 | 更新 | 耗时 | 各源 | 状态 |",
              "|---|---|---|---|---|---|---|"]
    for r in runs:
        ps = r.get("per_source", {})
        ps_str = " ".join(
            f"{_SOURCE_SHORT.get(k,k)}:{v.get('fetched',0)}"
            f"{'⚠️' if v.get('status')!='ok' else ''}"
            for k, v in ps.items())
        dur = f"{r.get('duration_ms',0)/1000:.1f}s"
        status = "✅" if r.get("status") == "ok" else "⚠️ 部分"
        lines.append(
            f"| {r['started_utc']} | {r['fetched']} | {r['inserted']} | "
            f"{r['updated']} | {dur} | {ps_str} | {status} |")

    lines += ["", "---", "", "_由采集器在每次运行后自动刷新。本地查看：`python run.py dashboard`_", ""]

    out = config.ROOT / "DASHBOARD.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def render_cli() -> None:
    rs = store.run_stats()
    st = store.stats()
    print("== 采集运维看板 ==")
    print(f"健康度: {_freshness(rs['last_run'])}")
    print(f"运行次数: 累计 {rs['total_runs']} | 近24h {rs['runs_24h']} | 近7天 {rs['runs_7d']}")
    print(f"仓库累计: {st['total']} 条 -> {st['by_source']}")
    print("最近运行:")
    for r in store.recent_runs(5):
        print(f"  {r['started_utc']}  抓取{r['fetched']} 新增{r['inserted']} "
              f"更新{r['updated']}  [{r['status']}]")
