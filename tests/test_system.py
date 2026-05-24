"""系统测试：覆盖数据仓库、采集解析、分析、播客脚本解析等确定性逻辑。

不依赖网络（用 fixture 与临时 DB）。运行：
    python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest
from pathlib import Path

from src import store
from src.collector import sources
from src.analyzer import app as analyzer
from src.podcast import tts


GITHUB_FIXTURE = """
<div data-hpc>
  <article class="Box-row">
    <h2 class="h3 lh-condensed">
      <a data-hydro-click="{...}" href="/octocat/hello-world">octocat / hello-world</a>
    </h2>
    <p class="col-9 color-fg-muted my-1 pr-4">A friendly demo repo.</p>
    <span itemprop="programmingLanguage">Python</span>
    <a href="/octocat/hello-world/stargazers" class="Link Link--muted d-inline-block">
      <svg aria-label="star" role="img"></svg>
      12,345
    </a>
  </article>
  <article class="Box-row">
    <h2 class="h3 lh-condensed">
      <a href="/acme/widgets">acme / widgets</a>
    </h2>
    <p class="col-9 color-fg-muted my-1 pr-4">Widgets for everyone.</p>
    <span itemprop="programmingLanguage">TypeScript</span>
    <a href="/acme/widgets/stargazers" class="Link Link--muted d-inline-block">
      <svg aria-label="star" role="img"></svg>
      678
    </a>
  </article>
</div>
"""

RSS_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>RSS One</title><link>https://ex.com/1</link>
    <description>First &amp; foremost</description><guid>g1</guid></item>
  <item><title>RSS Two</title><link>https://ex.com/2</link>
    <description>Second</description><guid>g2</guid></item>
</channel></rss>
"""

ATOM_FIXTURE = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Atom One</title>
    <link href="https://ex.com/a1"/><summary>Summary A1</summary><id>a1</id></entry>
</feed>
"""


class TestStore(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.dbp = Path(self.db)

    def tearDown(self):
        self.dbp.unlink(missing_ok=True)

    def _item(self, ext, score=10, **kw):
        d = {"source": "test", "external_id": ext, "title": f"T-{ext}",
             "url": f"https://x/{ext}", "summary": "s", "score": score,
             "lang": None, "meta": {}}
        d.update(kw)
        return d

    def test_insert_and_dedup(self):
        r1 = store.upsert_many([self._item("a"), self._item("b")], db_path=self.dbp)
        self.assertEqual((r1["inserted"], r1["updated"]), (2, 0))
        # 重复 upsert -> 全部更新，不新增
        r2 = store.upsert_many([self._item("a"), self._item("b")], db_path=self.dbp)
        self.assertEqual((r2["inserted"], r2["updated"]), (0, 2))
        self.assertEqual(store.stats(db_path=self.dbp)["total"], 2)

    def test_score_kept_max(self):
        store.upsert_many([self._item("a", score=50)], db_path=self.dbp)
        store.upsert_many([self._item("a", score=10)], db_path=self.dbp)
        rows = store.query_window("1970-01-01T00:00:00Z", db_path=self.dbp)
        self.assertEqual(rows[0]["score"], 50)  # 取最大热度

    def test_query_window_orders_by_score(self):
        store.upsert_many(
            [self._item("a", score=5), self._item("b", score=99)], db_path=self.dbp)
        rows = store.query_window("1970-01-01T00:00:00Z", db_path=self.dbp)
        self.assertEqual(rows[0]["external_id"], "b")

    def test_window_excludes_old(self):
        store.upsert_many([self._item("a")], db_path=self.dbp)
        rows = store.query_window("2999-01-01T00:00:00Z", db_path=self.dbp)
        self.assertEqual(rows, [])


class TestRunMetrics(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.dbp = Path(self.db)

    def tearDown(self):
        self.dbp.unlink(missing_ok=True)

    def test_record_and_run_stats(self):
        store.record_run("2026-05-24T00:00:00Z", "2026-05-24T00:00:05Z", 5000,
                         fetched=60, inserted=10, updated=50,
                         per_source={"github": {"fetched": 16, "status": "ok"}},
                         db_path=self.dbp)
        rs = store.run_stats(db_path=self.dbp)
        self.assertEqual(rs["total_runs"], 1)
        self.assertIsNotNone(rs["last_run"])
        runs = store.recent_runs(db_path=self.dbp)
        self.assertEqual(runs[0]["per_source"]["github"]["fetched"], 16)

    def test_daily_new_counts(self):
        store.record_run("2026-05-24T01:00:00Z", "2026-05-24T01:00:01Z", 1000,
                         fetched=5, inserted=5, updated=0, per_source={},
                         db_path=self.dbp)
        # 远期记录不计入近 1 天窗口（用大 days 容纳测试日期）
        rows = store.daily_new_counts(days=36500, db_path=self.dbp)
        self.assertTrue(any(r["new_items"] == 5 for r in rows))


class TestBriefBalance(unittest.TestCase):
    def test_balanced_top_mixes_sources(self):
        from src import brief
        rows = (
            [{"source": "github", "title": f"g{i}", "score": 100000 - i, "url": ""} for i in range(5)]
            + [{"source": "hackernews", "title": f"h{i}", "score": 500 - i, "url": ""} for i in range(5)]
            + [{"source": "rss", "title": f"r{i}", "score": 0, "url": ""} for i in range(5)]
        )
        top = brief._balanced_top(rows, per_source=2)
        srcs = {r["source"] for r in top}
        self.assertEqual(srcs, {"github", "hackernews", "rss"})
        self.assertEqual(len(top), 6)  # 每源 2 条


class TestRebuildUpsert(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.dbp = Path(self.db)

    def tearDown(self):
        self.dbp.unlink(missing_ok=True)

    def test_chronological_replay(self):
        item = {"source": "hn", "external_id": "x", "title": "t",
                "url": "u", "summary": "s", "score": 10, "meta": {}}
        with store._connect(self.dbp) as conn:
            store._rebuild_upsert(conn, item, "2026-05-01T00:00:00Z")
            item2 = dict(item, score=99)
            store._rebuild_upsert(conn, item2, "2026-05-03T00:00:00Z")
            row = conn.execute("SELECT * FROM items").fetchone()
        self.assertEqual(row["first_seen_utc"], "2026-05-01T00:00:00Z")  # 保留首见
        self.assertEqual(row["last_seen_utc"], "2026-05-03T00:00:00Z")   # 更新末见
        self.assertEqual(row["score"], 99)                                # 取最大热度


class TestContentFilter(unittest.TestCase):
    def test_blocks_political_keywords(self):
        from src import filters
        cfg = {"enabled": True, "block_keywords": ["trump", "选举"]}
        items = [
            {"title": "Trump announces new policy", "summary": ""},
            {"title": "New AI coding agent released", "summary": ""},
            {"title": "某地选举结果", "summary": ""},
            {"title": "GitHub trending tool", "summary": "great for devs"},
        ]
        kept = filters.filter_items(items, cfg)
        titles = [it["title"] for it in kept]
        self.assertEqual(len(kept), 2)
        self.assertIn("New AI coding agent released", titles)
        self.assertNotIn("Trump announces new policy", titles)

    def test_disabled_passthrough(self):
        from src import filters
        items = [{"title": "Trump", "summary": ""}]
        self.assertEqual(len(filters.filter_items(items, {"enabled": False})), 1)
        self.assertEqual(len(filters.filter_items(items, None)), 1)


class TestShowNotes(unittest.TestCase):
    def test_outline_and_links_extraction(self):
        import tempfile
        from src import config, notes
        with tempfile.TemporaryDirectory() as d:
            from pathlib import Path
            rep = Path(d) / "reports"
            pod = Path(d) / "podcasts"
            rep.mkdir(); pod.mkdir()
            orig_r, orig_p = config.REPORTS_DIR, config.PODCASTS_DIR
            config.REPORTS_DIR, config.PODCASTS_DIR = rep, pod
            try:
                (rep / "2026-01-01.md").write_text(
                    "# 报告\n[A 项目](https://github.com/x/a) 和 "
                    "[B 新闻](https://ex.com/b)\n再次 [A 项目](https://github.com/x/a)\n",
                    encoding="utf-8")
                (pod / "2026-01-01-script.md").write_text(
                    "# 标题\n<!-- outline:\n- 开场\n- 话题一\n- 收尾\n-->\n"
                    "主持人A：你好。\n", encoding="utf-8")
                n = notes.build_notes("2026-01-01")
                self.assertEqual(n["outline"], ["开场", "话题一", "收尾"])
                self.assertEqual(len(n["links"]), 2)  # 去重后 2 条
                self.assertIn("github.com/x/a", n["html"])
            finally:
                config.REPORTS_DIR, config.PODCASTS_DIR = orig_r, orig_p


class TestArchive(unittest.TestCase):
    def test_archive_and_rebuild_preserves_history(self):
        import json as _json
        from datetime import datetime, timedelta, timezone
        from pathlib import Path
        from src import archive, config, store
        d = Path(tempfile.mkdtemp())
        orig = (config.DATA_DIR, config.RAW_DIR, config.DB_PATH)
        config.DATA_DIR, config.RAW_DIR = d, d / "raw"
        config.RAW_DIR.mkdir(parents=True)
        config.DB_PATH = d / "digest.db"
        try:
            today = datetime.now(timezone.utc).date()
            def mk(day):
                with open(config.RAW_DIR / f"{day}.jsonl", "w", encoding="utf-8") as f:
                    f.write(_json.dumps({"source": "hn", "external_id": f"{day}-x",
                                         "title": "t", "score": 1,
                                         "collected_utc": f"{day}T00:00:00Z"}) + "\n")
            recent = today.isoformat()
            old = (today - timedelta(days=60)).isoformat()
            mk(recent); mk(old)
            r = archive.archive_old(active_days=30, max_age_days=365)
            self.assertEqual(r["archived"], 1)  # 旧文件被归档
            self.assertFalse((config.RAW_DIR / f"{old}.jsonl").exists())
            self.assertTrue(list((d / "archive").glob("*.jsonl.gz")))
            # 重建后两条历史都在（归档 + 明文）
            store.rebuild(config.DB_PATH)
            self.assertEqual(store.stats(config.DB_PATH)["total"], 2)
        finally:
            config.DATA_DIR, config.RAW_DIR, config.DB_PATH = orig


class TestPublishRequiresAudio(unittest.TestCase):
    def test_missing_audio_detected(self):
        from pathlib import Path
        from src import config, publish
        d = Path(tempfile.mkdtemp())
        orig = config.PODCASTS_DIR
        config.PODCASTS_DIR = d
        try:
            # 一个真实剧本（非占位）但没有 mp3
            (d / "2026-02-02-script.md").write_text(
                "# t\n主持人A：你好。\n嘉宾B：你好。\n", encoding="utf-8")
            missing = publish.missing_audio_episodes()
            self.assertIn("2026-02-02", missing)
            # 占位剧本不应被计入
            (d / "2026-02-03-script.md").write_text(
                "主持人A：（待生成）占位。\n", encoding="utf-8")
            self.assertNotIn("2026-02-03", publish.missing_audio_episodes())
        finally:
            config.PODCASTS_DIR = orig


class TestGitHubParser(unittest.TestCase):
    def test_parse_trending_html(self):
        items = sources._parse_trending_html(GITHUB_FIXTURE, top_n=10)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first["external_id"], "gh-octocat/hello-world")
        self.assertEqual(first["title"], "octocat/hello-world")
        self.assertEqual(first["lang"], "Python")
        self.assertEqual(first["score"], 12345)
        self.assertEqual(first["summary"], "A friendly demo repo.")
        self.assertEqual(items[1]["score"], 678)

    def test_top_n_limit(self):
        self.assertEqual(len(sources._parse_trending_html(GITHUB_FIXTURE, top_n=1)), 1)


class TestRSSParser(unittest.TestCase):
    def test_rss(self):
        orig = sources._get
        sources._get = lambda url, timeout=15: RSS_FIXTURE
        try:
            items = sources._parse_feed({"name": "Feed", "url": "x"}, limit=10, timeout=5)
        finally:
            sources._get = orig
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "RSS One")
        self.assertEqual(items[0]["external_id"], "rss-g1")
        self.assertIn("foremost", items[0]["summary"])  # HTML 实体已解码

    def test_atom(self):
        orig = sources._get
        sources._get = lambda url, timeout=15: ATOM_FIXTURE
        try:
            items = sources._parse_feed({"name": "Feed", "url": "x"}, limit=10, timeout=5)
        finally:
            sources._get = orig
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Atom One")
        self.assertEqual(items[0]["url"], "https://ex.com/a1")


class TestPodcastParser(unittest.TestCase):
    HOSTS = {
        "A": {"name": "晓宇", "voice": "voiceA"},
        "B": {"name": "思琪", "voice": "voiceB"},
    }

    def test_role_prefixes(self):
        text = (
            "主持人A：第一句。\n"
            "嘉宾B：第二句。\n"
            "A：第三句。\n"
            "晓宇：第四句。\n"
            "思琪：第五句。\n"
            "# 这是标题，应忽略\n"
            "> 引用，应忽略\n"
        )
        segs = tts._parse_script(text, self.HOSTS)
        self.assertEqual(len(segs), 5)
        self.assertEqual(segs[0], ("A", "第一句。"))
        self.assertEqual(segs[1], ("B", "第二句。"))
        self.assertEqual(segs[2][0], "A")
        self.assertEqual(segs[3][0], "A")  # 晓宇 -> A
        self.assertEqual(segs[4][0], "B")  # 思琪 -> B

    def test_empty_lines_ignored(self):
        segs = tts._parse_script("\n\n主持人A：内容\n\n", self.HOSTS)
        self.assertEqual(len(segs), 1)


class TestAnalyzer(unittest.TestCase):
    def test_template_digest(self):
        grouped = {
            "github": [{"title": "o/r", "url": "https://g/r", "score": 100,
                        "lang": "Go", "summary": "desc", "meta": {}}],
            "hackernews": [{"title": "HN", "url": "https://h", "score": 50,
                            "lang": None, "summary": "", "meta": {"comments": 9}}],
        }
        md = analyzer._template_digest("2026-01-01", grouped)
        self.assertIn("# 每日科技资讯报告 - 2026-01-01", md)
        self.assertIn("[o/r](https://g/r)", md)
        self.assertIn("⭐ 100", md)
        self.assertIn("💬 9", md)

    def test_items_to_text(self):
        grouped = {"rss": [{"title": "X", "url": "https://x", "score": 0,
                            "lang": None, "summary": "sum", "meta": {"feed": "F"}}]}
        text = analyzer._items_to_text(grouped)
        self.assertIn("RSS 资讯", text)
        self.assertIn("https://x", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
