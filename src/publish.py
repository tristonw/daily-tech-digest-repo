"""发布模块：合成音频 + 构建 GitHub Pages 播客播放页。

- synth_all(): 为所有有真实内容的脚本合成缺失的 MP3（沙箱内会因端点拦截跳过）。
- build_site(): 生成 site/index.html（移动端友好的在线播放页）+ 拷贝音频。
"""
from __future__ import annotations

import html
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import brief, config
from .podcast import tts

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})-script\.md$")


def _episodes() -> list[dict]:
    eps = []
    for f in sorted(config.PODCASTS_DIR.glob("*-script.md"), reverse=True):
        m = _DATE_RE.search(f.name)
        if not m:
            continue
        text = f.read_text(encoding="utf-8")
        if "（待生成）" in text:  # 占位脚本，跳过
            continue
        date = m.group(1)
        eps.append({
            "date": date,
            "mp3": config.PODCASTS_DIR / f"{date}.mp3",
            "teaser": brief._podcast_teaser(date, []),
        })
    return eps


def _has_audio(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0


def synth_all(insecure_ssl: bool = False) -> dict:
    done, failed = [], []
    for ep in _episodes():
        if _has_audio(ep["mp3"]):
            done.append(ep["date"])
            continue
        try:
            tts.synthesize(ep["date"], insecure_ssl=insecure_ssl)
            done.append(ep["date"])
        except Exception as exc:  # noqa: BLE001
            failed.append(ep["date"])
            print(f"  [warn] {ep['date']} 音频合成失败: {exc}")
    return {"done": done, "failed": failed}


_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>每日科技播客</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
         background:#0f1115; color:#e6e6e6; line-height:1.6; }
  header { padding:32px 20px 16px; text-align:center; border-bottom:1px solid #222; }
  header h1 { margin:0 0 6px; font-size:1.6rem; }
  header p { margin:0; color:#8a8f98; font-size:.9rem; }
  main { max-width:760px; margin:0 auto; padding:20px; }
  .ep { background:#171a21; border:1px solid #232833; border-radius:12px; padding:18px 20px; margin:16px 0; }
  .ep h2 { margin:0 0 8px; font-size:1.15rem; }
  .teaser { color:#b6bcc6; margin:0 0 14px; font-size:.95rem; }
  audio { width:100%; }
  .noaudio { color:#8a8f98; font-style:italic; margin:0; }
  footer { text-align:center; color:#666; font-size:.8rem; padding:24px; }
  a { color:#6ea8fe; }
</style>
</head>
<body>
<header>
  <h1>🎙 每日科技播客</h1>
  <p>每天自动汇总科技动态，生成双人对话播客</p>
</header>
<main>
"""

_FOOT = """</main>
<footer>更新于 {updated} · 由每日科技资讯系统自动生成</footer>
</body>
</html>
"""


def build_site(out_dir: Path | None = None) -> Path:
    out = out_dir or (config.ROOT / "site")
    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    cards = []
    for ep in _episodes():
        if _has_audio(ep["mp3"]):
            shutil.copy(ep["mp3"], audio_dir / f"{ep['date']}.mp3")
            player = (f'<audio controls preload="none" '
                      f'src="audio/{ep["date"]}.mp3"></audio>')
        else:
            player = '<p class="noaudio">（音频生成中，稍后刷新）</p>'
        cards.append(
            f'<article class="ep">\n'
            f'  <h2>每日科技播客 · {ep["date"]}</h2>\n'
            f'  <p class="teaser">{html.escape(ep["teaser"] or "")}</p>\n'
            f'  {player}\n'
            f'</article>'
        )

    body = "\n".join(cards) if cards else "<p>暂无节目</p>"
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out_file = out / "index.html"
    out_file.write_text(_HEAD + body + "\n" + _FOOT.format(updated=updated),
                        encoding="utf-8")
    return out_file
