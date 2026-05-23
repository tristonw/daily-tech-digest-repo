"""共享数据仓库：SQLite 持久化、去重 upsert、时间窗查询、JSONL 快照。

三个模块（采集 / 分析 / 播客）通过这个仓库解耦：
采集器只管把抓到的条目 upsert 进来，分析器只管按时间窗读取。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT,
    summary       TEXT,
    score         INTEGER DEFAULT 0,
    lang          TEXT,
    meta_json     TEXT,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc  TEXT NOT NULL,
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_items_last_seen ON items(last_seen_utc);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def _connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    config.ensure_dirs()
    conn = sqlite3.connect(str(db_path or config.DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_many(items: Iterable[dict], db_path: Path | None = None) -> dict:
    """插入新条目，已存在的更新 score / last_seen / summary。

    返回 {"inserted": n, "updated": m}。
    """
    now = _utcnow()
    inserted = updated = 0
    with _connect(db_path) as conn:
        for it in items:
            source = it["source"]
            external_id = str(it["external_id"])
            row = conn.execute(
                "SELECT id, score FROM items WHERE source=? AND external_id=?",
                (source, external_id),
            ).fetchone()
            meta_json = json.dumps(it.get("meta", {}), ensure_ascii=False)
            if row is None:
                conn.execute(
                    """INSERT INTO items
                       (source, external_id, title, url, summary, score, lang,
                        meta_json, first_seen_utc, last_seen_utc)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        source, external_id, it.get("title", ""), it.get("url"),
                        it.get("summary"), int(it.get("score") or 0), it.get("lang"),
                        meta_json, now, now,
                    ),
                )
                inserted += 1
            else:
                conn.execute(
                    """UPDATE items
                       SET score=?, summary=COALESCE(?, summary),
                           meta_json=?, last_seen_utc=?
                       WHERE id=?""",
                    (
                        max(int(it.get("score") or 0), int(row["score"] or 0)),
                        it.get("summary"), meta_json, now, row["id"],
                    ),
                )
                updated += 1
    return {"inserted": inserted, "updated": updated}


def query_window(
    since_utc: str,
    until_utc: str | None = None,
    sources: list[str] | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """取 [since, until] 时间窗内（按 last_seen_utc）的条目，按 score 降序。"""
    until_utc = until_utc or _utcnow()
    sql = "SELECT * FROM items WHERE last_seen_utc >= ? AND last_seen_utc <= ?"
    params: list = [since_utc, until_utc]
    if sources:
        sql += " AND source IN (%s)" % ",".join("?" * len(sources))
        params.extend(sources)
    sql += " ORDER BY score DESC, last_seen_utc DESC"
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def stats(db_path: Path | None = None) -> dict:
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
        by_source = {
            r["source"]: r["c"]
            for r in conn.execute(
                "SELECT source, COUNT(*) AS c FROM items GROUP BY source"
            ).fetchall()
        }
    return {"total": total, "by_source": by_source}


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    try:
        d["meta"] = json.loads(d.pop("meta_json") or "{}")
    except (ValueError, TypeError):
        d["meta"] = {}
    return d


def write_jsonl_snapshot(items: list[dict], date_str: str) -> Path:
    """把本次采集的条目追加写入 data/raw/DATE.jsonl（git 友好的可读快照）。"""
    config.ensure_dirs()
    path = config.RAW_DIR / f"{date_str}.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    return path
