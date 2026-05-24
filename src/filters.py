"""内容合规过滤：剔除时政/敏感条目，降低在国内平台发布的资质风险。

只在生成对外产物（digest / brief / 播客）时过滤；原始采集数据完整保留，
不影响数据仓库与运维看板的归档。
"""
from __future__ import annotations


def is_blocked(item: dict, keywords: list[str]) -> bool:
    text = ((item.get("title") or "") + " " + (item.get("summary") or "")).lower()
    return any(k.lower() in text for k in keywords)


def filter_items(items: list[dict], cfg: dict | None) -> list[dict]:
    """按关键词剔除敏感条目。cfg 为 config 的 content_filter 段。"""
    if not cfg or not cfg.get("enabled"):
        return items
    kws = cfg.get("block_keywords", [])
    if not kws:
        return items
    return [it for it in items if not is_blocked(it, kws)]
