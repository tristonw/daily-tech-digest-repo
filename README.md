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

# 数据仓库统计
python run.py stats
```

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

## 说明

- 采集与分析全部使用 Python 标准库，外部依赖仅 `edge-tts`（音频合成）。
- TTS 需要能访问微软语音端点；若运行环境的网络策略/代理拦截该端点，音频步骤会优雅报错并保留脚本，可在网络可达的环境用 `python run.py podcast --audio-only` 重试。

---

由每日科技资讯系统自动生成
