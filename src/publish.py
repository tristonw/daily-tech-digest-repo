"""发布模块：合成音频 + 构建 GitHub Pages 播客播放页。

- synth_all(): 为所有有真实内容的脚本合成缺失的 MP3（沙箱内会因端点拦截跳过）。
- build_site(): 生成 site/index.html（移动端友好的在线播放页）+ 拷贝音频。
"""
from __future__ import annotations

import html
import re
import shutil
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from . import brief, config
from . import notes as _notes
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


def _duration_hhmmss(date: str) -> str:
    """按脚本字数估算时长（中文约 chars_per_minute 字/分钟）。"""
    pcfg = config.load_config()["podcast"]
    cpm = pcfg.get("chars_per_minute", 280)
    script = config.PODCASTS_DIR / f"{date}-script.md"
    chars = 0
    if script.exists():
        for line in script.read_text(encoding="utf-8").splitlines():
            if line.startswith(("主持人A：", "嘉宾B：")):
                chars += len(line.split("：", 1)[1])
    secs = int(chars * 60 / cpm) if chars else 0
    return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


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
            # 打印完整根因（含被包装的底层异常），便于在 CI 日志定位。
            cause = getattr(exc, "__cause__", None)
            print(f"  [error] {ep['date']} 音频合成失败: {type(exc).__name__}: {exc}")
            if cause is not None:
                print(f"          根因: {type(cause).__name__}: {cause}")
    return {"done": done, "failed": failed}


def missing_audio_episodes() -> list[str]:
    """有真实剧本却没有对应 mp3 的期（应当合成却没合成）。"""
    return [ep["date"] for ep in _episodes() if not _has_audio(ep["mp3"])]


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
  <img src="cover.png" alt="封面" style="width:160px;height:160px;border-radius:16px;margin-bottom:12px">
  <h1>🎙 每日科技播客</h1>
  <p>每天自动汇总科技动态，生成双人对话播客</p>
  <p><a href="feed.xml">📡 RSS 订阅</a>（可提交小宇宙 / Apple Podcasts 收录）</p>
  <p style="font-size:.78rem;color:#666">本节目文稿与配音均由 AI 自动生成</p>
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

    # 生成封面图（小宇宙/Apple 收录的硬性条件）
    try:
        from . import cover
        cover.generate(out / "cover.png")
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 封面生成失败（需要 Pillow）: {exc}")

    cards = []
    for ep in _episodes():
        if _has_audio(ep["mp3"]):
            shutil.copy(ep["mp3"], audio_dir / f"{ep['date']}.mp3")
            player = (f'<audio controls preload="none" '
                      f'src="audio/{ep["date"]}.mp3"></audio>')
        else:
            player = '<p class="noaudio">（音频生成中，稍后刷新）</p>'
        notes = _notes.build_notes(ep["date"])
        outline_html = ""
        if notes["outline"]:
            outline_html = ("<details><summary>本期大纲</summary><ul>"
                            + "".join(f"<li>{html.escape(o)}</li>" for o in notes["outline"])
                            + "</ul></details>")
        links_html = ""
        if notes["links"]:
            links_html = ("<details><summary>关键新闻链接</summary><ul>"
                          + "".join(f'<li><a href="{html.escape(u)}" target="_blank" rel="noopener">{html.escape(t)}</a></li>'
                                    for t, u in notes["links"])
                          + "</ul></details>")
        cards.append(
            f'<article class="ep">\n'
            f'  <h2>每日科技播客 · {ep["date"]}</h2>\n'
            f'  <p class="teaser">{html.escape(ep["teaser"] or "")}</p>\n'
            f'  {player}\n'
            f'  {outline_html}{links_html}\n'
            f'</article>'
        )

    body = "\n".join(cards) if cards else "<p>暂无节目</p>"
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out_file = out / "index.html"
    out_file.write_text(_HEAD + body + "\n" + _FOOT.format(updated=updated),
                        encoding="utf-8")
    build_feed(out)
    return out_file


def build_feed(out_dir: Path | None = None) -> Path:
    """生成播客 RSS feed（feed.xml），用于提交小宇宙/Apple Podcasts 等平台收录。"""
    out = out_dir or (config.ROOT / "site")
    out.mkdir(parents=True, exist_ok=True)
    p = config.load_config().get("publish", {})
    base = p.get("site_base_url", "").rstrip("/")
    feed_url = f"{base}/feed.xml"

    items_xml = []
    for ep in _episodes():
        date = ep["date"]
        audio_url = f"{base}/audio/{date}.mp3"
        size = ep["mp3"].stat().st_size if _has_audio(ep["mp3"]) else 0
        pub = format_datetime(datetime(int(date[:4]), int(date[5:7]),
                                       int(date[8:10]), 12, tzinfo=timezone.utc))
        title = f"{p.get('title','每日科技播客')} · {date}"
        notes = _notes.build_notes(date)
        teaser = ep["teaser"] or "每日科技动态汇总"
        desc = (teaser + "\n\n" + notes["text"]) if notes["text"] else teaser
        content_html = (f"<p>{xml_escape(teaser)}</p>" + notes["html"]) if notes["html"] else f"<p>{xml_escape(teaser)}</p>"
        items_xml.append(f"""    <item>
      <title>{xml_escape(title)}</title>
      <description>{xml_escape(desc)}</description>
      <itunes:summary>{xml_escape(desc)}</itunes:summary>
      <content:encoded><![CDATA[{content_html}]]></content:encoded>
      <enclosure url="{xml_escape(audio_url)}" length="{size}" type="audio/mpeg"/>
      <guid isPermaLink="false">{xml_escape(audio_url)}</guid>
      <pubDate>{pub}</pubDate>
      <itunes:duration>{_duration_hhmmss(date)}</itunes:duration>
      <itunes:explicit>{'yes' if p.get('explicit') else 'no'}</itunes:explicit>
    </item>""")

    # 未显式配置封面时，默认用自动生成的 cover.png
    image_url = p.get("image") or f"{base}/cover.png"
    image_tag = f'<itunes:image href="{xml_escape(image_url)}"/>'
    channel_image = (f'<image><url>{xml_escape(image_url)}</url>'
                     f'<title>{xml_escape(p.get("title",""))}</title>'
                     f'<link>{xml_escape(base)}</link></image>')
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>{xml_escape(p.get('title','每日科技播客'))}</title>
    <link>{xml_escape(base)}</link>
    <language>{xml_escape(p.get('language','zh-cn'))}</language>
    <description>{xml_escape(p.get('description',''))}</description>
    <itunes:author>{xml_escape(p.get('author',''))}</itunes:author>
    <itunes:summary>{xml_escape(p.get('description',''))}</itunes:summary>
    <itunes:owner><itunes:name>{xml_escape(p.get('author',''))}</itunes:name>
      <itunes:email>{xml_escape(p.get('email',''))}</itunes:email></itunes:owner>
    <itunes:category text="{xml_escape(p.get('category','Technology'))}"/>
    <itunes:explicit>{'yes' if p.get('explicit') else 'no'}</itunes:explicit>
    {image_tag}
    {channel_image}
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom" href="{xml_escape(feed_url)}" rel="self" type="application/rss+xml"/>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""
    out_file = out / "feed.xml"
    out_file.write_text(feed, encoding="utf-8")
    return out_file
