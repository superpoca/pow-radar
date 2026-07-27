# pow-radar

一个**只读、静态分析优先**的 GitHub PoW/GPU 挖矿项目监控 MVP。它通过 GitHub REST API 发现候选仓库、采集静态信号、给出四维可解释评分、记录状态变化，并在满足保守条件时发送 P0/P1/P2 告警。

## 安全边界

本项目默认只做以下事情：

- 调用 GitHub REST API 读取仓库元数据、文件树和文本文件内容。
- 静态分析 PoW、GPU、miner、node、wallet、genesis、mainnet、testnet、seed node、release candidate 等信号。
- 保存评分、信号、告警、状态变化历史。
- 可选地发送 Telegram 告警。

本项目**不会**做以下事情：

- 不会执行被监控仓库代码。
- 不会自动下载并运行矿工、钱包、节点或远程脚本。
- 不会导入私钥、助记词、聊天 ID 或真实 token。
- 不会自动投入算力或资金。

如果检测到可疑安装脚本、远程执行模式或不可验证二进制来源，系统会走硬过滤或风险标记。

## 功能范围

- Python 3.11+，Typer CLI。
- PostgreSQL / SQLite，基于 SQLAlchemy 2.x。
- 可重复初始化：`pow-radar init-db` 或首次运行时自动 `create_all`。
- GitHub API 分页、超时、基础重试、限流等待。
- 数据模型：`projects`、`github_snapshots`、`scores`、`signals`、`alerts`、`status_changes`。
- 告警按 `event_hash` 去重，重复运行幂等。
- 状态机：`DISCOVERED`、`WATCHLIST`、`QUALIFIED`、`TESTNET`、`PRE-MINE`、`MINING-READY`、`ACTIVE-MINING`、`REJECTED`、`ARCHIVED`。
- Telegram 未配置时安全跳过，不会导致任务失败。

## 本地启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
cp /home/runner/work/pow-radar/pow-radar/.env.example .env
pow-radar init-db
pow-radar discover
pow-radar collect
pow-radar score
pow-radar detect-signals
pow-radar send-alerts
pow-radar daily-report
```

### 主要环境变量

见 `/home/runner/work/pow-radar/pow-radar/.env.example`：

- `GITHUB_TOKEN`：推荐配置，提升 GitHub API 限额。
- `DATABASE_URL`：默认 SQLite，本地建议 `sqlite:///pow-radar.db`。
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`：未配置时自动跳过告警发送。
- `KEYWORDS_FILE` / `RULES_FILE`：YAML 配置路径。
- `GITHUB_TIMEOUT_SECONDS` / `GITHUB_MAX_PAGES`：API 超时与分页上限。

## 数据库与初始化

- 开发/测试：SQLite。
- 部署：PostgreSQL。
- 初始化方案：SQLAlchemy 模型 + `schema_versions` 表，重复执行安全。
- TODO：后续可引入 Alembic 进行显式版本迁移；当前 MVP 以可重复初始化和可测试为主。

## 评分规则

默认四维评分：

- 团队可信度：30
- 开发真实程度：25
- GPU 挖矿可行性：25
- 头矿时机价值：20

默认重点门槛：

- 总分 `>= 75`
- 团队 `>= 18`
- GPU `>= 16`
- 且没有硬拒绝

硬过滤包括：

- 低改动 fork
- 长期不活跃
- 无可验证 PoW
- 恶意远程执行/安装脚本

完整阈值见 `/home/runner/work/pow-radar/pow-radar/config/score_rules.yaml`。

## P0 保守判定

P0 不会只依赖 README 或项目方声明。默认至少要求：

1. 节点必要条件存在。
2. PoW 参数存在。
3. 矿工必要条件存在。
4. 钱包必要条件存在。
5. 上述必要条件来自**非 README 的可验证静态来源**（代码/配置/脚本/release 相关文件）。
6. 同时满足多条独立证据标记：如 release、构建路径、矿工/GPU 路径、主网窗口、genesis 参数等。

## README 人工复核清单（P0 收到后必须人工做）

- 核对源码与 release 是否对应。
- 核对二进制哈希/签名是否可验证。
- 核对节点、矿工、钱包和主网参数是否完整。
- 核对预挖、开发者奖励、锁仓和资金用途是否透明。
- 核对是否有独立第三方成功同步、构建或出块证据。
- 不要下载或执行未知脚本或未知二进制。

## API 限流说明

- 使用 GitHub REST API。
- `GITHUB_TOKEN` 未配置时可以运行，但搜索/采集能力更弱。
- 对搜索、contributors、releases、commits 等接口启用分页。
- 遇到 `403 rate limit`、`429`、`5xx` 时会做有限重试与等待。

## CLI

- `pow-radar init-db`
- `pow-radar discover`
- `pow-radar collect`
- `pow-radar score`
- `pow-radar detect-signals`
- `pow-radar send-alerts`
- `pow-radar daily-report`
- `pow-radar weekly-report`
- `pow-radar run-all`

## Docker

```bash
docker compose up --build
```

默认 `app` 容器会执行 `pow-radar run-all`，数据库使用 PostgreSQL 16。

## 定时任务示例

参见 `/home/runner/work/pow-radar/pow-radar/ops/cron.example`。

## 测试

```bash
pytest
```

测试全部离线，不依赖真实 GitHub token、数据库服务或 Telegram。

## TODO / 安全降级

- 当前没有自动接入 GitHub Actions 定时运行示例，只提供 cron/docker-compose 示例。
- 当前不抓取 Discord/Telegram/论坛等非结构化公告，仅做 GitHub 只读静态分析。
- `ACTIVE-MINING` 状态保留给后续结合更多外部证据的版本，当前 MVP 主要产出 `TESTNET`、`PRE-MINE`、`MINING-READY`。
