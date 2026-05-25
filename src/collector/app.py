"""模块1 应用层：单次增量采集 collect_once() + 持续循环 watch()。"""
from __future__ import annotations

import signal
import time
from datetime import datetime, timezone

from .. import config, store
from . import sources


def collect_once(verbose: bool = True) -> dict:
    """抓取所有启用的源，upsert 入库，写 JSONL 快照，并记录运维指标。"""
    cfg = config.load_config()["collector"]
    timeout = cfg.get("http_timeout", 15)
    collected: list[dict] = []
    per_source: dict[str, dict] = {}
    started = datetime.now(timezone.utc)

    def _run_source(key: str, label: str, fn):
        try:
            items = fn()
            collected.extend(items)
            per_source[key] = {"fetched": len(items), "status": "ok"}
            if verbose:
                print(f"  {label}: {len(items)} 条")
        except Exception as exc:  # noqa: BLE001
            per_source[key] = {"fetched": 0, "status": "error", "error": str(exc)}
            print(f"  [warn] {label} 采集失败: {exc}")

    if cfg.get("hacker_news", {}).get("enabled"):
        hn_cfg = cfg["hacker_news"]
        _run_source("hackernews", "HackerNews", lambda: sources.fetch_hacker_news(
            hn_cfg.get("top_n", 30), hn_cfg.get("min_score", 0), timeout))
    if cfg.get("github_trending", {}).get("enabled"):
        gh_cfg = cfg["github_trending"]
        _run_source("github", "GitHub Trending", lambda: sources.fetch_github_trending(
            gh_cfg.get("since", "daily"), gh_cfg.get("top_n", 25), timeout))
    if cfg.get("rss", {}).get("enabled"):
        rss_cfg = cfg["rss"]
        _run_source("rss", "RSS", lambda: sources.fetch_rss(
            rss_cfg.get("feeds", []), rss_cfg.get("per_feed_limit", 15), timeout))

    started_iso = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    result = store.upsert_many(collected)
    date_str = config.today_str()  # 快照按本地(北京)日期分组
    if collected:
        store.write_jsonl_snapshot(collected, date_str, collected_utc=started_iso)
    result["fetched"] = len(collected)

    finished = datetime.now(timezone.utc)
    status = "ok" if all(s.get("status") == "ok" for s in per_source.values()) else "partial"
    store.record_run(
        started_utc=started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        finished_utc=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
        duration_ms=int((finished - started).total_seconds() * 1000),
        fetched=result["fetched"], inserted=result["inserted"],
        updated=result["updated"], per_source=per_source, status=status,
    )
    if verbose:
        print(f"  => 抓取 {result['fetched']} 条，新增 {result['inserted']}，"
              f"更新 {result['updated']}（耗时 {(finished-started).total_seconds():.1f}s）")
    return result


_STOP = False


def watch(interval: int | None = None) -> None:
    """持续循环采集，每 interval 秒一次（满足"不断地爬"）。Ctrl-C 优雅退出。"""
    global _STOP
    interval = interval or config.load_config()["collector"].get(
        "watch_interval_seconds", 1800)

    def _handle(signum, frame):  # noqa: ANN001
        global _STOP
        _STOP = True
        print("\n收到退出信号，结束本轮后停止…")

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    print(f"持续采集已启动，间隔 {interval}s（Ctrl-C 停止）")
    while not _STOP:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{ts}] 采集中…")
        try:
            collect_once()
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] 本轮采集异常: {exc}")
        for _ in range(interval):
            if _STOP:
                break
            time.sleep(1)
    print("已停止。")
