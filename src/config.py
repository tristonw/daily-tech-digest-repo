"""配置加载：合并 config.json 与环境变量。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

# 输出（报告/脚本/早报/节目）的日期按本地时区命名，默认北京时间 UTC+8。
# 这样北京早上 6-7 点生成的内容会标成"当天"，而不是 UTC 的前一天。
TZ_OFFSET_HOURS = 8

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "digest.db"
REPORTS_DIR = ROOT / "reports"
PODCASTS_DIR = ROOT / "podcasts"
PROMPTS_DIR = ROOT / "prompts"


def today_str() -> str:
    """当天日期（按 TZ_OFFSET_HOURS 本地时区），用于输出文件命名。"""
    return (datetime.now(timezone.utc) + timedelta(hours=TZ_OFFSET_HOURS)).strftime(
        "%Y-%m-%d")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, REPORTS_DIR, PODCASTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


def anthropic_base_url() -> str:
    return os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
