---
description: 生成当天的科技 digest 与双人播客脚本并提交（供每日定时会话调用）
---

你是这档「每日科技播客」的主笔。请**完整执行**今天这一期的内容生产，严格按步骤来：

## 1. 采集最新数据
运行：`python run.py collect --once`

## 2. 取出当天真实采集条目
运行：`python run.py analyze`（会生成模板版报告并导出 prompt）。
然后读取 `data/raw/<今天日期>-digest.prompt.txt`（日期用 UTC，与 run.py 一致），里面是当天真实采集到的 GitHub / Hacker News / RSS 条目。

## 3. 写高质量 digest（覆盖模板版）
基于上一步的**真实条目**，用中文写一份信息密度高的 digest，覆盖写入 `reports/<日期>.md`，沿用既有板块：
今日概览 / 🔥 GitHub 热门项目 / 📰 Hacker News 要点 / 🌐 行业资讯 / 📊 趋势分析 / 💼 商业化价值 / 🏢 企业风控·保险场景借鉴。
**只用真实条目与链接，不要编造数据。**

## 4. 写双人对话播客脚本
写入 `podcasts/<日期>-script.md`，要求：
- 保留顶部 front-matter（date / voice_A / voice_B）和标题；
- 正文每行以「主持人A：」或「嘉宾B：」开头，纯口语对话；
- 结构：开场 → 3-5 个当天话题 → **企业风控与保险科技专题（约5分钟，讲机遇/风险/挑战）** → 收尾；
- 篇幅中文约 5000 字（约 18 分钟）。

## 5. 合规自检
确认稿子里**没有时政/敏感内容**（参考 `config.json` 的 `content_filter.block_keywords`）。如有，替换成技术/产业话题。

## 6. 校验脚本可解析
运行：`python run.py podcast`（会保留你刚写的脚本）。确认无报错。

## 7. 提交并推送（提交到 main）
`git add reports/ podcasts/*-script.md briefs/ data/ DASHBOARD.md`
（**不要**提交 mp3、site/、data/piper_models、g2pW）
提交信息：`Daily episode <日期>`，然后 `git push origin main`。

## 说明
- **音频合成与 GitHub Pages 发布无需在此处理**：`pages.yml` 工作流会在它的每日计划里用自托管 Piper 自动合成 MP3、生成封面与 feed.xml 并部署，从而把你这次提交的新脚本上架到网站和各播客平台。
- 完成后用一两句话汇报当天主题。
