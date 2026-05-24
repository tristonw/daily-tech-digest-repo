# Daily Tech Digest · 每日科技资讯系统

每天持续采集科技新闻/动态，自动汇总分析，并生成一期约 15 分钟的双人对话播客（脚本 + 多音色音频）。

## 三大模块

1. **新闻收集模块** (`src/collector`)：持续/定时从 GitHub Trending、Hacker News、科技 RSS 采集，增量去重后累积进 SQLite 数据仓库。
2. **新闻汇总分析模块** (`src/analyzer`)：基于数据仓库中近期累积的数据，生成结构化 digest 报告（`reports/`）。
3. **播客脚本与音频生成模块** (`src/podcast`)：把 digest 改写成主持人 A/B 双人对话稿（`podcasts/*-script.md`），再用多音色 TTS 合成 MP3（`podcasts/*.mp3`）。

三个模块通过共享数据仓库 `data/digest.db` 解耦。

## 安装

```bash
pip install -r requirements.txt   # 仅音频合成需要 edge-tts；采集/分析/存储全用标准库
```

## 使用

```bash
# 模块1：采集（单次 / 持续循环）
python run.py collect --once
python run.py collect --watch --interval 1800     # 持续不断地爬，每 30 分钟一轮

# 模块2：汇总分析（默认取近 24h 累积数据）
python run.py analyze [--window-hours 24] [--date YYYY-MM-DD]

# 模块3：播客脚本 / 音频
python run.py podcast                  # 仅生成脚本
python run.py podcast --with-audio     # 脚本 + 合成 MP3
python run.py podcast --audio-only     # 用已有脚本只合成 MP3
python run.py podcast --force          # 强制重建脚本（覆盖已有）

# 一键：采集 -> 分析 -> 播客
python run.py daily [--with-audio]

# 运维看板：刷新 DASHBOARD.md（GitHub 可直接查看）并打印实时状态
python run.py dashboard

# 每日早间简报（运维状态 + 今日要点）
python run.py brief

# 合成音频并构建 GitHub Pages 在线播放页
python run.py publish              # 合成音频 + 构建 site/
python run.py publish --skip-audio # 仅构建站点

# 数据仓库统计
python run.py stats
```

## 完整 RSS 分发方案（小宇宙 / Apple Podcasts / Spotify）

播客平台不"上传文件"，而是**收录 RSS feed**：你的 MP3 托管在公开 URL（本项目用 GitHub Pages），写进 feed 的 `<enclosure>`，平台从 feed 自动拉取。一次配置，全网分发。

端到端链路（全自动）：
```
collect → analyze → podcast(脚本) → publish(piper 合成 MP3 + 封面 + feed.xml) → 部署 GitHub Pages
```

产出的 feed 地址：
```
https://<用户名>.github.io/daily-tech-digest-repo/feed.xml
```

`feed.xml` 已包含平台收录所需字段：频道标题/作者/邮箱/分类/语言、`itunes:image`（封面）、`itunes:explicit`，每期 `<item>` 含 `<enclosure>`（MP3 URL + 字节大小）、`guid`、`pubDate`、`itunes:duration`、`atom:link self`。

**一次性提交步骤：**
1. 在 `config.json → publish` 填真实 `email`（平台验证归属用）；`site_base_url` 设为你的 Pages 地址。
2. 触发 `Publish Podcast Site` 工作流（或本地 `python run.py publish`）生成并部署 feed。
3. 浏览器打开 `…/feed.xml` 确认可访问。
4. 在小宇宙 App / 创作者后台「提交播客」填入 feed 地址；同一地址可同时提交 Apple Podcasts、Spotify 等。
5. 之后每日工作流更新 feed，新节目被各平台自动收录。

## 在线收听（GitHub Pages）

`pages.yml` 工作流每天（01:00 UTC）在 GitHub Actions 里合成音频、构建播放页并发布到 GitHub Pages，得到一个公开可访问的在线播放页：

```
https://<用户名>.github.io/daily-tech-digest-repo/
```

手机/电脑浏览器打开即可在线收听，无需下载。首次需要在仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**（工作流也会尝试自动开启）。本地预览：`python run.py publish` 后打开 `site/index.html`。

## 运维可见性

- **`DASHBOARD.md`**（仓库根目录）：每次采集后自动刷新，含健康度（最近一次采集距今多久）、累计运行次数、各数据源清单与状态、近 14 天采集量、最近运行明细。直接在 GitHub 上打开即可看到"采集是否在后台正常运行"。
- **`briefs/YYYY-MM-DD-brief.md`**：每日早报，含过去约 16 小时的采集运维状态 + 跨来源均衡的今日要点 + 完整报告/播客链接。由每日工作流在早上生成。
- 每次采集都会记录一条运行日志（时间、抓取/新增/更新数、各源健康、耗时）。

## 数据持久化（无二进制冲突）

- **真相源（提交进 git）**：`data/raw/YYYY-MM-DD.jsonl`（带 `collected_utc` 时间戳的采集快照）+ `data/runs.jsonl`（运行日志）。两者都是追加式纯文本，可被 git 自动合并。
- **派生缓存（不入库）**：`data/digest.db` 已在 `.gitignore` 中。任何命令运行前会自动检测，缺失时（如全新 clone）从上述 JSONL **自动重建**。
- 手动重建：`python run.py rebuild`。
- 这样多个工作流/分支并发提交也不会产生二进制合并冲突。

### 归档策略（控制仓库体积，不丢历史）

`config.json → archive` 配置，`daily.yml` 每日自动执行 `python run.py archive`：
- **近 30 天**（`active_days`）：`data/raw/*.jsonl` 保持明文。
- **超过 30 天**：日文件按月压缩进 `data/archive/YYYY-MM.jsonl.gz`，删除原明文。
- **超过 365 天**（`max_age_days`）：整月归档删除；`runs.jsonl` 同步修剪。
- DB 重建（`rebuild`）会同时读取 `raw` 与 `archive`，保留期内历史可完整还原。

## 内容生成的两种模式

`analyze` 与 `podcast` 的内容生成（LLM 部分）支持两种驱动方式，自动切换：

- **API 自动模式**：设置环境变量 `ANTHROPIC_API_KEY` 后，脚本直接调用 Anthropic API（默认模型见 `config.json`）自动生成高质量 digest 与双人播客稿，可独立定时运行。
- **会话内生成模式**（无 key 时回退）：生成模板版 digest / 占位脚本，并把组装好的 prompt 导出到 `data/raw/DATE-*.prompt.txt`，由每日的 Claude Code 会话读取并生成、覆盖产出。会话已生成的脚本在再次运行时不会被占位内容覆盖（除非 `--force`）。

## 配置

编辑 `config.json` 可调整：采集源开关与数量、RSS feed 列表、采集间隔、播客目标时长与主持人音色、LLM 模型等。

## 调度（让"持续/每天"成立）

- 本地/服务器常驻：`python run.py collect --watch`
- 定时增量（推荐生产）：用 cron 或 GitHub Actions 周期性运行 `collect`，每日运行 `analyze` + `podcast`，并提交更新后的 `data/digest.db`、`reports/`、`podcasts/`。
- Claude Code on the web 定时会话：定时触发会话执行 `daily`，无 API key 时由会话补全内容。

## 目录结构

```
config.json            # 配置
run.py                 # 统一入口
src/
  store.py             # 共享数据仓库（SQLite，去重 upsert / 时间窗查询）
  llm.py               # Anthropic API 封装 + 会话模式回退
  collector/           # 模块1：采集
  analyzer/            # 模块2：分析
  podcast/             # 模块3：脚本 + TTS
prompts/               # digest / podcast 提示词模板
data/digest.db         # 累积数据仓库
data/raw/              # 每日 JSONL 快照 + 会话模式 prompt 导出
reports/               # 汇总 digest
podcasts/              # 双人对话脚本 + MP3
```

## 合规与风险控制

- **内容过滤**：`config.json → content_filter` 按关键词剔除时政/敏感条目（仅作用于 digest / 早报 / 播客等对外产物，原始采集数据完整保留）。可按需增删 `block_keywords`。
- **AI 生成标识**：RSS feed、播放页均标注"由 AI 生成"；音频开头自动插入一段 AI 声明（`config.podcast.tts.ai_disclaimer`）。符合《互联网信息服务深度合成管理规定》对合成内容标识的要求。
- **TTS provider 可切换**（`config.podcast.tts.provider`）：
  - `piper`（**默认，推荐**）：自托管开源 TTS（MIT 许可），**输出音频可商用、零授权风险，完全免费**。中文双音色 = `zh_CN-chaowen-medium`（男）+ `zh_CN-huayan-medium`（女），模型首次运行自动从 HuggingFace 下载。依赖见 `requirements-piper.txt`（含 PyTorch CPU 版 + lameenc 编码 MP3，无需 ffmpeg）。
  - `azure`：Azure 语音服务 REST（付费订阅含商用授权，免费层每月约 50 万字符），密钥用环境变量 `AZURE_SPEECH_KEY`，区域在 `config.podcast.tts.azure.region`。
  - `edge`（备用）：edge-tts 免费，⚠ **仅授权用于微软 Edge"大声朗读"，未授权用于对外发布/商业播客**——仅供本地试听。

### 自托管 TTS（provider=piper）安装

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-piper.txt
python run.py podcast --audio-only --date YYYY-MM-DD   # 生成 MP3
```
- **版权**：仅做摘要、评论与链接回源，不复制原文；公开发布前请确认来源条款并咨询专业意见。

## 说明

- 采集与分析全部使用 Python 标准库，外部依赖仅 `edge-tts`（音频合成）。
- TTS 需要能访问微软语音端点；若运行环境的网络策略/代理拦截该端点，音频步骤会优雅报错并保留脚本，可在网络可达的环境用 `python run.py podcast --audio-only` 重试。

---

由每日科技资讯系统自动生成
