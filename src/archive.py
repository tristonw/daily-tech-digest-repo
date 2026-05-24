"""数据归档：控制仓库体积，同时不丢历史。

策略（可在 config.archive 调整）：
- active_days（默认 30）：近 N 天的 data/raw/*.jsonl 保持明文。
- 超过 active_days 的日文件 → 按月压缩进 data/archive/YYYY-MM.jsonl.gz，删除原明文。
- max_age_days（默认 365）：整月早于该期限的归档直接删除。
- runs.jsonl 也修剪到 max_age_days 内。
DB 重建（store.rebuild）会同时读取 raw 与 archive，历史可完整还原（在保留期内）。
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timedelta, timezone

from . import config

_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.jsonl$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})\.jsonl\.gz$")


def _archive_dir():
    d = config.DATA_DIR / "archive"
    d.mkdir(parents=True, exist_ok=True)
    return d


def archive_old(active_days: int | None = None,
                max_age_days: int | None = None) -> dict:
    cfg = config.load_config().get("archive", {})
    active_days = active_days if active_days is not None else cfg.get("active_days", 30)
    max_age_days = max_age_days if max_age_days is not None else cfg.get("max_age_days", 365)
    config.ensure_dirs()
    arch = _archive_dir()
    today = datetime.now(timezone.utc).date()
    active_cutoff = today - timedelta(days=active_days)
    max_cutoff = today - timedelta(days=max_age_days)

    archived = deleted = 0

    # 1) 压缩超过活跃期的日文件 → 按月 gzip
    for f in sorted(config.RAW_DIR.glob("*.jsonl")):
        m = _DAY_RE.match(f.name)
        if not m:
            continue
        d = datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc).date()
        if d >= active_cutoff:
            continue
        month_gz = arch / f"{m[1]}-{m[2]}.jsonl.gz"
        with open(f, "rb") as src, gzip.open(month_gz, "ab") as dst:
            dst.write(src.read())
        f.unlink()
        archived += 1

    # 2) 删除整月早于保留期限的归档
    for gz in sorted(arch.glob("*.jsonl.gz")):
        mm = _MONTH_RE.match(gz.name)
        if not mm:
            continue
        month_start = datetime(int(mm[1]), int(mm[2]), 1, tzinfo=timezone.utc).date()
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        if next_month <= max_cutoff:  # 整月都早于保留期限
            gz.unlink()
            deleted += 1

    # 3) 修剪 runs.jsonl
    _trim_runs(max_cutoff.isoformat())

    return {"archived": archived, "deleted": deleted}


def _trim_runs(cutoff_date_iso: str) -> None:
    runs = config.DATA_DIR / "runs.jsonl"
    if not runs.exists():
        return
    kept = []
    for line in runs.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            started = json.loads(line).get("started_utc", "")
        except ValueError:
            continue
        if started[:10] >= cutoff_date_iso:
            kept.append(line)
    runs.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
