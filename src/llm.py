"""Anthropic API 封装（urllib，无 SDK 依赖）+ 会话模式回退。

有 ANTHROPIC_API_KEY 时直接调用 API 自动生成；
无 key 时抛 SessionModeNeeded，由调用方导出 prompt 供 Claude Code 会话补全。
"""
from __future__ import annotations

import json
import ssl
import urllib.request

from . import config


class SessionModeNeeded(Exception):
    """无 API key 时抛出，提示走"会话内生成"模式。"""


def available() -> bool:
    return bool(config.anthropic_api_key())


def _ssl_context() -> ssl.SSLContext:
    # 复用环境的 CA（含代理自签名根证书），避免 MITM 代理下握手失败。
    import os
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca:
        return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


def complete(system: str, user: str, max_tokens: int | None = None,
             model: str | None = None) -> str:
    """调用 Anthropic Messages API，system 走 prompt caching。"""
    key = config.anthropic_api_key()
    if not key:
        raise SessionModeNeeded("未配置 ANTHROPIC_API_KEY")

    cfg = config.load_config().get("llm", {})
    model = model or cfg.get("model", "claude-opus-4-7")
    max_tokens = max_tokens or cfg.get("max_tokens", 8192)

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [
            {"type": "text", "text": system,
             "cache_control": {"type": "ephemeral"}},
        ],
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        f"{config.anthropic_base_url()}/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    parts = [b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip()
