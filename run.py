#!/usr/bin/env python3
"""每日科技资讯系统统一入口。

  python run.py collect [--once | --watch] [--interval 1800]
  python run.py analyze [--window-hours 24] [--date YYYY-MM-DD]
  python run.py podcast [--with-audio] [--insecure-ssl] [--date YYYY-MM-DD]
  python run.py daily   [--with-audio]      # collect -> 看板 -> 早报 -> analyze -> podcast
  python run.py dashboard                   # 刷新运维看板 DASHBOARD.md 并打印
  python run.py brief   [--date YYYY-MM-DD] # 生成每日早间简报
  python run.py stats
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone


def _today() -> str:
    from src import config
    return config.today_str()


def cmd_collect(args) -> None:
    from src.collector import app
    from src import dashboard
    if args.watch:
        app.watch(args.interval)
    else:
        print("== 模块1：新闻采集（单次）==")
        app.collect_once()
        dashboard.render_markdown()  # 每次采集后刷新看板


def cmd_analyze(args) -> None:
    from src.analyzer import app
    print("== 模块2：汇总分析 ==")
    app.analyze(args.date, args.window_hours, force=args.force)


def cmd_podcast(args) -> None:
    from src.podcast import script, tts
    date = args.date or _today()
    if not args.audio_only:
        print("== 模块3：播客脚本 ==")
        script.generate(date, force=args.force)
    if args.with_audio or args.audio_only:
        print("== 模块3：音频合成 ==")
        tts.synthesize(date, insecure_ssl=args.insecure_ssl)


def cmd_daily(args) -> None:
    from src.collector import app as collector
    from src.analyzer import app as analyzer
    from src.podcast import script, tts
    from src import dashboard, brief
    date = _today()
    print("== 模块1：新闻采集 ==")
    collector.collect_once()
    print("== 看板刷新 ==")
    dashboard.render_markdown()
    print("== 每日早报 ==")
    print(f"  {brief.generate(date)}")
    print("== 模块2：汇总分析 ==")
    analyzer.analyze(date)
    print("== 模块3：播客脚本 ==")
    script.generate(date)
    if args.with_audio:
        print("== 模块3：音频合成 ==")
        try:
            tts.synthesize(date, insecure_ssl=args.insecure_ssl)
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] {exc}")


def cmd_dashboard(_args) -> None:
    from src import dashboard
    dashboard.render_cli()
    out = dashboard.render_markdown()
    print(f"看板已写入: {out}")


def cmd_brief(args) -> None:
    from src import brief
    print(f"早报已生成: {brief.generate(args.date)}")


def cmd_publish(args) -> None:
    import sys
    from src import publish
    if not args.skip_audio:
        print("== 合成音频 ==")
        r = publish.synth_all(insecure_ssl=args.insecure_ssl)
        print(f"  音频就绪: {len(r['done'])} 期，失败/跳过: {len(r['failed'])} 期")
    print("== 构建播放页 ==")
    out = publish.build_site()
    print(f"  站点已生成: {out}")
    # 关键：若有真实剧本却缺音频，发布视为失败（让 CI 变红、暴露问题），
    # 而不是静默部署一个没有声音的站点/feed。
    missing = publish.missing_audio_episodes()
    if missing and not args.allow_missing_audio:
        print(f"  [error] 以下期缺少音频，发布失败: {', '.join(missing)}")
        print("          （排查上面的合成错误；本地仅构建可加 --allow-missing-audio）")
        sys.exit(1)


def cmd_archive(_args) -> None:
    from src import archive
    r = archive.archive_old()
    print(f"归档完成：压缩 {r['archived']} 个日文件，删除 {r['deleted']} 个超期月归档")


def cmd_rebuild(_args) -> None:
    from src import store
    store.rebuild()
    s = store.stats()
    print(f"已从 JSONL 重建数据仓库：{s['total']} 条 -> {s['by_source']}")


def cmd_stats(_args) -> None:
    from src import store
    s = store.stats()
    print(f"累积条目总数: {s['total']}")
    for src_name, c in s["by_source"].items():
        print(f"  {src_name}: {c}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="每日科技资讯系统")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("collect", help="模块1：采集新闻")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="单次采集（默认）")
    g.add_argument("--watch", action="store_true", help="持续循环采集")
    p.add_argument("--interval", type=int, default=None, help="持续模式间隔秒数")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("analyze", help="模块2：汇总分析")
    p.add_argument("--window-hours", type=int, default=None)
    p.add_argument("--date", default=None)
    p.add_argument("--force", action="store_true", help="强制重建报告（覆盖已有）")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("podcast", help="模块3：播客脚本/音频")
    p.add_argument("--with-audio", action="store_true", help="生成脚本后同时合成 MP3")
    p.add_argument("--audio-only", action="store_true", help="只用已有脚本合成 MP3")
    p.add_argument("--force", action="store_true", help="强制重建脚本（覆盖已有）")
    p.add_argument("--insecure-ssl", action="store_true", help="TTS 跳过证书校验")
    p.add_argument("--date", default=None)
    p.set_defaults(func=cmd_podcast)

    p = sub.add_parser("daily", help="一键：采集->分析->播客")
    p.add_argument("--with-audio", action="store_true")
    p.add_argument("--insecure-ssl", action="store_true")
    p.set_defaults(func=cmd_daily)

    p = sub.add_parser("stats", help="查看数据仓库统计")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("dashboard", help="运维看板：刷新 DASHBOARD.md 并打印")
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("brief", help="生成每日早间简报")
    p.add_argument("--date", default=None)
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("rebuild", help="从 data/*.jsonl 重建数据仓库缓存")
    p.set_defaults(func=cmd_rebuild)

    p = sub.add_parser("archive", help="归档旧采集数据（压缩/清理，控制仓库体积）")
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("publish", help="合成音频并构建 GitHub Pages 播放页")
    p.add_argument("--skip-audio", action="store_true", help="只构建站点，不合成音频")
    p.add_argument("--allow-missing-audio", action="store_true",
                   help="容忍缺音频（仅本地构站点用）；CI 不应加此项")
    p.add_argument("--insecure-ssl", action="store_true", help="TTS 跳过证书校验")
    p.set_defaults(func=cmd_publish)

    args = parser.parse_args(argv)
    # DB 是派生缓存（不入库）；全新 clone 后从 data/*.jsonl 自动重建。
    from src import store
    store.ensure_db()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
