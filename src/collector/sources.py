"""数据源采集器：Hacker News / GitHub Trending / RSS。

每个采集器返回统一结构的 dict 列表：
    {source, external_id, title, url, summary, score, lang, meta}
全程超时 + try/except，单源失败不影响其它源。
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape

_UA = "Mozilla/5.0 (compatible; daily-tech-digest/1.0)"


def _ssl_context() -> ssl.SSLContext:
    import os
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    return ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()


def _get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return resp.read().decode("utf-8", "replace")


def _get_json(url: str, timeout: int = 15):
    return json.loads(_get(url, timeout))


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


# --------------------------------------------------------------------------- #
# Hacker News
# --------------------------------------------------------------------------- #
def fetch_hacker_news(top_n: int = 30, min_score: int = 0, timeout: int = 15) -> list[dict]:
    ids = _get_json("https://hacker-news.firebaseio.com/v0/topstories.json", timeout)[:top_n]
    items: list[dict] = []
    for hid in ids:
        try:
            it = _get_json(
                f"https://hacker-news.firebaseio.com/v0/item/{hid}.json", timeout
            )
        except Exception:
            continue
        if not it or it.get("type") != "story":
            continue
        score = int(it.get("score") or 0)
        if score < min_score:
            continue
        items.append({
            "source": "hackernews",
            "external_id": f"hn-{hid}",
            "title": _clean(it.get("title")),
            "url": it.get("url") or f"https://news.ycombinator.com/item?id={hid}",
            "summary": "",
            "score": score,
            "lang": None,
            "meta": {
                "comments": int(it.get("descendants") or 0),
                "by": it.get("by"),
                "hn_url": f"https://news.ycombinator.com/item?id={hid}",
            },
        })
    return items


# --------------------------------------------------------------------------- #
# GitHub Trending
# --------------------------------------------------------------------------- #
def fetch_github_trending(since: str = "daily", top_n: int = 25, timeout: int = 15) -> list[dict]:
    try:
        return _parse_trending_html(_get(f"https://github.com/trending?since={since}", timeout), top_n)
    except Exception:
        return _github_search_fallback(top_n, timeout)


def _parse_trending_html(html: str, top_n: int) -> list[dict]:
    chunks = html.split('<article class="Box-row">')[1:]
    items: list[dict] = []
    for chunk in chunks[:top_n]:
        m = re.search(r'<h2 class="h3 lh-condensed">.*?href="/([^"]+)"', chunk, re.S)
        if not m:
            continue
        repo = m.group(1).strip().strip("/")
        if repo.count("/") != 1:
            continue
        desc_m = re.search(r'<p class="col-9[^"]*">(.*?)</p>', chunk, re.S)
        lang_m = re.search(r'itemprop="programmingLanguage">([^<]+)</span>', chunk)
        star_m = re.search(r'/stargazers"[^>]*>\s*<svg[^>]*aria-label="star".*?</svg>\s*([\d,]+)', chunk, re.S)
        if not star_m:
            star_m = re.search(r'stargazers"[^>]*>.*?([\d,]+)\s*</a>', chunk, re.S)
        stars = int(star_m.group(1).replace(",", "")) if star_m else 0
        items.append({
            "source": "github",
            "external_id": f"gh-{repo}",
            "title": repo,
            "url": f"https://github.com/{repo}",
            "summary": _clean(desc_m.group(1)) if desc_m else "",
            "score": stars,
            "lang": lang_m.group(1).strip() if lang_m else None,
            "meta": {"stars": stars},
        })
    return items


def _github_search_fallback(top_n: int, timeout: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    url = (
        "https://api.github.com/search/repositories?"
        f"q=created:>={since}&sort=stars&order=desc&per_page={top_n}"
    )
    data = _get_json(url, timeout)
    items = []
    for r in data.get("items", []):
        items.append({
            "source": "github",
            "external_id": f"gh-{r['full_name']}",
            "title": r["full_name"],
            "url": r["html_url"],
            "summary": _clean(r.get("description")),
            "score": int(r.get("stargazers_count") or 0),
            "lang": r.get("language"),
            "meta": {"stars": int(r.get("stargazers_count") or 0)},
        })
    return items


# --------------------------------------------------------------------------- #
# RSS
# --------------------------------------------------------------------------- #
def fetch_rss(feeds: list[dict], per_feed_limit: int = 15, timeout: int = 15) -> list[dict]:
    items: list[dict] = []
    for feed in feeds:
        try:
            items.extend(_parse_feed(feed, per_feed_limit, timeout))
        except Exception as exc:  # noqa: BLE001 - 单个 feed 失败不致命
            print(f"  [warn] RSS 源不可达，跳过: {feed.get('name')} ({exc})")
    return items


def _parse_feed(feed: dict, limit: int, timeout: int) -> list[dict]:
    root = ET.fromstring(_get(feed["url"], timeout))
    # 同时兼容 RSS <item> 与 Atom <entry>
    entries = root.iter("item")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    atom = root.findall(".//a:entry", ns)
    out: list[dict] = []

    def add(title, link, summary, guid):
        out.append({
            "source": "rss",
            "external_id": f"rss-{guid or link}",
            "title": _clean(title),
            "url": link,
            "summary": _clean(summary)[:500],
            "score": 0,
            "lang": None,
            "meta": {"feed": feed.get("name")},
        })

    count = 0
    for it in entries:
        if count >= limit:
            break
        add(it.findtext("title"), it.findtext("link"),
            it.findtext("description"), it.findtext("guid"))
        count += 1
    if count == 0 and atom:  # Atom feed
        for e in atom[:limit]:
            link_el = e.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else None
            add(e.findtext("a:title", default="", namespaces=ns), link,
                e.findtext("a:summary", default="", namespaces=ns),
                e.findtext("a:id", default="", namespaces=ns))
    return out
