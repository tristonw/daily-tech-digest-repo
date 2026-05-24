"""模块3b：解析双人对话脚本，多音色合成单个 MP3。

按行解析「主持人A：」/「嘉宾B：」台词，逐段用对应音色合成，
MP3 帧可直接字节拼接，无需 ffmpeg。

支持可切换的 TTS provider（config.podcast.tts.provider）：
- "edge"：edge-tts（免费，但仅授权用于微软 Edge"大声朗读"，
  ⚠ 未授权用于对外发布/商业播客，公开发布前请改用有商用授权的 provider）。
- "azure"：Azure 语音服务 REST（付费订阅含商用授权），密钥取自环境变量
  AZURE_SPEECH_KEY，区域取自 config.podcast.tts.azure.region。
合成前会自动在开头插入一段"AI 生成"口播声明（合规标识，可在 config 关闭）。
"""
from __future__ import annotations

import asyncio
import os
import re
import ssl
import urllib.request
from pathlib import Path

from .. import config

# 角色前缀 -> 配置中的 host key。兼容"主持人A / 嘉宾B / A / 晓宇"等写法。
_LINE_RE = re.compile(r"^\s*(?:主持人|嘉宾|主播|host|guest)?\s*([AB])\s*[:：]\s*(.+)$",
                      re.IGNORECASE)


def _parse_script(text: str, hosts: dict) -> list[tuple[str, str]]:
    """返回 [(voice, text), ...]。同时支持以角色中文名开头的行。"""
    name_to_key = {hosts["A"]["name"]: "A", hosts["B"]["name"]: "B"}
    segments: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("<!--", "#", ">", "-", "*")):
            continue
        key = None
        speech = None
        m = _LINE_RE.match(line)
        if m:
            key, speech = m.group(1), m.group(2)
        else:
            for name, k in name_to_key.items():
                for sep in ("：", ":"):
                    prefix = name + sep
                    if line.startswith(prefix):
                        key, speech = k, line[len(prefix):]
                        break
                if key:
                    break
        if key and speech and speech.strip():
            segments.append((hosts[key]["voice"], speech.strip()))
    return segments


def _patch_edge_tts_ssl(insecure: bool) -> None:
    """让 edge-tts 信任本环境的 CA。

    edge-tts 在 communicate/voices 模块用 certifi 构建了模块级 _SSL_CTX，
    不信任企业代理/MITM 的根证书。这里改用系统 CA 包（含代理根证书）覆盖之，
    使其在代理环境下也能握手成功。
    """
    import os
    import edge_tts.communicate as _c
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE") \
        or "/etc/ssl/certs/ca-certificates.crt"
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    elif os.path.exists(ca):
        ctx = ssl.create_default_context(cafile=ca)
    else:
        return  # 用 edge-tts 默认（certifi）
    _c._SSL_CTX = ctx
    try:
        import edge_tts.voices as _v
        _v._SSL_CTX = ctx
    except Exception:  # noqa: BLE001
        pass


async def _synth_edge(segments: list[tuple[str, str]], out_path: Path,
                      insecure_ssl: bool) -> None:
    import asyncio as _aio

    import edge_tts
    _patch_edge_tts_ssl(insecure_ssl)
    with open(out_path, "wb") as fout:
        for i, (voice, speech) in enumerate(segments, 1):
            # 免费端点偶发 503 限流，逐段重试，避免整集失败。
            for attempt in range(4):
                try:
                    buf = bytearray()
                    communicate = edge_tts.Communicate(speech, voice)
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            buf += chunk["data"]
                    fout.write(buf)
                    break
                except Exception:  # noqa: BLE001
                    if attempt == 3:
                        raise
                    await _aio.sleep(2 ** attempt)
            if i % 10 == 0:
                print(f"    …已合成 {i}/{len(segments)} 段")


def _synth_azure(segments: list[tuple[str, str]], out_path: Path) -> None:
    """Azure 语音服务 REST 合成（付费订阅含商用授权）。"""
    key = os.environ.get("AZURE_SPEECH_KEY")
    if not key:
        raise RuntimeError("provider=azure 需设置环境变量 AZURE_SPEECH_KEY。")
    azure = config.load_config()["podcast"]["tts"].get("azure", {})
    region = azure.get("region", "eastus")
    fmt = azure.get("output_format", "audio-24khz-48kbitrate-mono-mp3")
    endpoint = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    with open(out_path, "wb") as fout:
        for i, (voice, speech) in enumerate(segments, 1):
            ssml = (
                "<speak version='1.0' xml:lang='zh-CN'>"
                f"<voice name='{voice}'>{_xml_escape(speech)}</voice></speak>"
            )
            req = urllib.request.Request(
                endpoint, data=ssml.encode("utf-8"),
                headers={
                    "Ocp-Apim-Subscription-Key": key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": fmt,
                    "User-Agent": "daily-tech-digest",
                }, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                fout.write(resp.read())
            if i % 10 == 0:
                print(f"    …已合成 {i}/{len(segments)} 段")


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def synthesize(date_str: str, insecure_ssl: bool = False) -> Path:
    pcfg = config.load_config()["podcast"]
    hosts = pcfg["hosts"]
    tts_cfg = pcfg.get("tts", {})
    provider = tts_cfg.get("provider", "edge")
    script_path = config.PODCASTS_DIR / f"{date_str}-script.md"
    if not script_path.exists():
        raise FileNotFoundError(f"未找到播客脚本：{script_path}，请先运行 podcast。")

    segments = _parse_script(script_path.read_text(encoding="utf-8"), hosts)
    if not segments:
        raise ValueError("脚本中未解析到任何 A/B 台词，请检查脚本格式。")

    # 合规：在开头插入"AI 生成"口播声明（用主持人A音色）。
    disclaimer = tts_cfg.get("ai_disclaimer")
    if disclaimer:
        segments.insert(0, (hosts["A"]["voice"], disclaimer))

    print(f"  provider={provider}，共 {len(segments)} 段，开始合成…")
    if provider == "edge":
        print("  ⚠ edge-tts 语音未授权用于对外发布/商业播客；"
              "公开发布前请将 config.podcast.tts.provider 改为 azure 等有商用授权的 provider。")

    out_path = config.PODCASTS_DIR / f"{date_str}.mp3"
    try:
        if provider == "azure":
            _synth_azure(segments, out_path)
        elif provider == "edge":
            asyncio.run(_synth_edge(segments, out_path, insecure_ssl))
        else:
            raise ValueError(f"未知的 TTS provider: {provider}")
    except (RuntimeError, ValueError):
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "音频合成失败（TTS 端点不可达或证书校验失败）。"
            "脚本已保留，可在 TTS 端点可达的环境重试，或加 --insecure-ssl。"
            f"\n原始错误：{exc}"
        ) from exc
    size_kb = out_path.stat().st_size // 1024
    print(f"  ✓ 音频已生成: {out_path}（{size_kb} KB）")
    return out_path
