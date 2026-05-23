"""配置加载：合并 config.json 与环境变量。"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "digest.db"
REPORTS_DIR = ROOT / "reports"
PODCASTS_DIR = ROOT / "podcasts"
PROMPTS_DIR = ROOT / "prompts"


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
