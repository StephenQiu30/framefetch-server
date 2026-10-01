<div align="center">
  <img src="frontend/public/logo.png" alt="帧取 FrameFetch 开源媒体工作流 Logo" width="88" />
  <h1>帧取 · FrameFetch</h1>
  <p><strong>开源、自托管的公开视频下载、剧本文档处理与 AI 分析工作流</strong></p>
  <p><em>Open-source, self-hosted media download, screenplay processing and AI video analysis workflow.</em></p>
  <p>
    <a href="https://github.com/StephenQiu30/video-server/actions/workflows/ci.yml"><img src="https://github.com/StephenQiu30/video-server/actions/workflows/ci.yml/badge.svg" alt="CI 状态" /></a>
    <a href="https://github.com/StephenQiu30/video-server/releases"><img src="https://img.shields.io/github/v/release/StephenQiu30/video-server?color=111111" alt="Latest release" /></a>
    <a href="https://github.com/StephenQiu30/video-server/stargazers"><img src="https://img.shields.io/github/stars/StephenQiu30/video-server?style=flat&color=111111" alt="GitHub stars" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-111111.svg" alt="MIT License" /></a>
    <img src="https://img.shields.io/badge/Python-3.12-3776AB.svg" alt="Python 3.12" />
    <img src="https://img.shields.io/badge/Next.js-16-000000.svg" alt="Next.js 16" />
    <img src="https://img.shields.io/badge/Docker-Compose-2496ED.svg" alt="Docker Compose" />
  </p>
  <p>
    <a href="#最新动态">最新动态</a> ·
    <a href="#快速开始">快速开始</a> ·
    <a href="#适用场景">适用场景</a> ·
    <a href="#产品能力">产品能力</a> ·
    <a href="#常见问题">常见问题</a> ·
    <a href="#界面预览">界面预览</a> ·
    <a href="#架构">架构</a> ·
    <a href="README.en.md">English</a>
  </p>
</div>

![帧取 FrameFetch 开源自托管视频工作流公开落地页](docs/images/landing.png)

> 截图由 `agent-browser` 在本地预览环境中采集；涉及媒体的界面使用仓库自带视觉回归素材，所有图片均不包含真实用户数据、凭据或第三方图片热链。

## 帧取是什么

帧取（FrameFetch）是一个面向创作者、内容研究者和开发者的开源媒体工作流。它把公开媒体链接、本地视频或剧本文档转换为可观察、可恢复的异步任务：解析来源、选择真实格式、隔离下载与校验、保存制品，并按需生成结构化 AI 分析报告。

项目处理用户有权获取的 HTTP(S) 非 DRM 内容。R0 只执行匿名 L1；账号可访问的非加密内容按设计 17 在身份层重建后逐平台验收。加密媒体不解密、不取得内容密钥。

## 最新动态

**解析引擎重建 R0**

- 清退旧会话链、运营治理和解析计划／尝试账本，Runner 暂时仅执行匿名 L1 yt-dlp。
- 保留单 Activity Temporal 解析、RabbitMQ 下载、受控出口与最终制品校验；平台完整文件状态以[设计 17](docs/design/17-解析引擎重建.md)的验收为准。
- 公开样本移到 `backend/scripts/fixtures/fixed_public_cases.json`，供冷启动矩阵使用。身份层在 R4 重建。

**[v0.2.0](https://github.com/StephenQiu30/video-server/releases/tag/v0.2.0) · 容器自持平台会话**

- 媒体执行复用隔离 Runner 与受控出口，平台能力以真实文件验收为准。
- Web 体验：头像上传与个人资料、统一的解析结果双栏卡片、可恢复错误提示与 shadcn 组件整理。

从 v0.1.0 升级前请先阅读 [Release 说明](https://github.com/StephenQiu30/video-server/releases/tag/v0.2.0)中的不兼容变更。

## 适用场景

- **短视频与影视拆解**：导入自己的成片或已获授权的公开视频，生成分镜、场景时间轴与关键帧证据，复盘镜头节奏与叙事结构。
- **剧本与文案研究**：导入 Markdown、Fountain、TXT、PDF、DOCX 剧本文档，在同一工作区阅读、分析或改写，并导出 Markdown / DOCX 报告。
- **团队素材库**：在自己的服务器上集中保存经过格式、时长与 SHA-256 校验的媒体文件，按用户与角色管理任务和存储。
- **自托管视频下载器**：用 Web、API 或 iOS / Android 客户端提交授权的公开媒体链接，异步下载并实时查看进度，不依赖任何官方托管服务。
- **二次开发**：以 OpenAPI 为唯一契约，在 FastAPI、Next.js 与 Flutter 之上扩展新的 Provider、分析能力或客户端。

**English summary:** FrameFetch is an open-source, self-hosted video downloader and media workflow for authorized public content. It combines FastAPI, Next.js, PostgreSQL, RabbitMQ, MinIO, yt-dlp/FFmpeg adapters, screenplay ingestion and optional AI video analysis. See the [English README](README.en.md) for the complete overview.

## 视频解析与 AI 分析如何配合

1. 检查已获授权的公开媒体链接，或导入自己的本地视频、剧本文档。
2. 确认来源和格式，跟踪处理任务；媒体制品与 AI 分析分别记录状态。
3. 按需执行视频分镜、场景或剧本文档分析，结合时间轴与关键帧证据复核结果。
4. 导出 Markdown / DOCX 报告，用于内容研究、创作整理与团队审阅。

Web 实例提供公开页面：`/guide/` 使用指南、`/self-hosting/` 自托管部署指南、`/about/` 项目定位与边界，以及面向生成式搜索的 `/llms.txt`；完整实现与配置见下方能力表和[设计文档索引](docs/design/README.md)。模型可用性与输出内容取决于已配置的分析能力和 AI 服务。

### 常见问题

**帧取和 yt-dlp、FFmpeg 有什么关系？** yt-dlp 与 FFmpeg 是媒体适配和处理链路中的工具。FrameFetch 在其上提供 Web / API、用户与任务管理、隔离 Worker、制品存储、文档处理和可选 AI 分析，不保证所有提取器支持的平台在当前部署中都可用。

**开源免费是否包含模型与服务器费用？** MIT 许可证开放源代码；服务器、存储、流量和外部模型可能产生费用，不包含免费托管或模型额度。

**自托管是否代表所有数据仅在本地？** 数据保存在部署者配置的基础设施中；使用外部 AI Provider 时，分析所需内容会发送到该服务。启用前请确认素材授权与服务的数据处理约定。

**Web 和手机端在哪个仓库？** 本仓库维护 API、Next.js Web 和 Worker；[video-app](https://github.com/StephenQiu30/video-app) 是连接本服务的 Flutter iOS / Android 客户端，不在手机端运行离线 AI。

## 产品能力

| 能力 | 当前实现 |
| --- | --- |
| 公开媒体解析 | 从公开链接或单链接分享文案中识别来源、媒体信息和真实可用格式 |
| 可靠异步下载 | API → Transactional Outbox → RabbitMQ → Download Worker → 隔离 Media Runner |
| 制品校验与存储 | 通过重新解析、语义格式校验、FFmpeg/ffprobe、大小、时长和 SHA-256 校验后写入 MinIO |
| 实时任务状态 | WebSocket 增量事件、版本检查、断线重连与 resync；实时连接不作为任务事实源 |
| 剧本文档工作流 | 导入 Markdown、Fountain、TXT、PDF、DOCX，提供阅读、目录、分页和分析入口 |
| 可选 AI 分析 | 宿主机 Codex Agent 或管理员配置的模型 Provider；报告可导出 Markdown/DOCX |
| 运维与管理 | 用户与角色、Provider 状态、下载分析、持久文件分页和显式清理 |
| 原生移动端 | 独立的 [FrameFetch Flutter iOS/Android 客户端](https://github.com/StephenQiu30/video-app) |

### 为什么采用工作流架构

- **可恢复**：PostgreSQL 保存任务事实，Transactional Outbox 保证数据库状态与消息意图一致。
- **可隔离**：下载、媒体命令和 AI 长任务不在 HTTP 请求进程中执行；Runner 经过受控出口代理。
- **可验证**：Provider 返回值不会直接成为最终制品，Worker 会重新解析并验证媒体身份、格式和文件完整性。
- **可扩展**：Provider、Runner、应用用例、OpenAPI 客户端和前端 feature 组件保持清晰边界。
- **可自托管**：Docker Compose 只管理业务服务并复用已有基础环境，不依赖官方托管服务。

## 界面预览

![帧取 FrameFetch 登录后的公开媒体解析、视频格式选择与异步下载工作区](docs/images/home.png)

<p align="center"><strong>登录后的媒体解析与真实格式选择工作区</strong></p>

<table>
  <tr>
    <td width="50%"><img src="docs/images/providers.png" alt="帧取 FrameFetch 平台 Provider 能力与最近验证状态页面" /></td>
    <td width="50%"><img src="docs/images/login.png" alt="帧取 FrameFetch 账户登录与安全会话页面" /></td>
  </tr>
  <tr>
    <td align="center"><strong>Provider 能力与验证状态</strong></td>
    <td align="center"><strong>账户登录与安全会话</strong></td>
  </tr>
</table>

主要 Web 路由包括媒体解析与下载、任务历史与详情、剧本文档阅读与分析、Provider 状态、账户设置，以及管理员用户、文件、分析和 AI Provider 管理。实际可用平台和状态以部署实例的 `/providers` 页面及真实完整文件验收为准。

## 快速开始

本机开发使用 `docker-compose.yml`，生产使用 `docker-compose-prod.yml`。公开账号平台先匿名解析，明确认证失败后按已批准范围复用当前 Chrome 会话；固定公开平台不读取材料。提取器存在、Cookie 存在与服务健康均不代表媒体可下载，必须以真实文件结果验收。

### 前置条件

- Docker Engine 与 Docker Compose
- 本机已运行 PostgreSQL、RabbitMQ、Redis 和 MinIO，已有配置直接复用
- 用于生产部署时，需要自行提供强随机密钥和公开访问地址

### 本机启动（macOS，单人自用）

```bash
git clone https://github.com/StephenQiu30/video-server.git
cd video-server
test -f .env || cp .env.example .env

# 确认 .env 连接本机已运行的 PostgreSQL、RabbitMQ、Redis 与 MinIO

# 启动：migrate 容器先应用幂等的 backend/sql/schema.sql，其余服务随后启动
docker compose up -d --build --wait --remove-orphans
```

所有容器化后台循环（Outbox 投递、解析与下载、导入、报告发布）运行在一个 `worker` 容器中，使用一个 RabbitMQ 账号 `RABBITMQ_WORKER_USER` / `RABBITMQ_WORKER_PASS`，权限是原 outbox、download、import、report 四个角色的并集，不授予 `.*`。从旧的多 Worker 拓扑升级时，先创建该账号（生产环境替换账号名与密码，并写入环境文件）：

```bash
DL='(?:^video\.(events|events\.dead|download|download\.dead)$)|^video\.download-intent(?:\.dead)?$'
rabbitmqctl add_user video-worker '<password>'
rabbitmqctl set_permissions -p video video-worker "$DL" "$DL" "$DL|^video\.import$|^video\.analysis-report$"
```

`--remove-orphans` 会移除已退役的 `outbox`、`worker-*`、`provider-canary`、`provider-lease-redis` 与 `workspace-init` 容器，旧的 outbox／download／import／report 账号随后可删除。

R0 不安装平台身份来源；当前仅执行匿名 L1。

全新空库还没有登录账号时，在部署机终端执行一次首管理员初始化（需使用可连接 PostgreSQL 的 `DATABASE_URL`，密码交互输入，不进入命令行历史）：

```bash
uv run --project backend python -m app.workers.bootstrap_admin \
  --env-file .env --username your-admin --email you@example.com
```

命令只在用户表为空时创建管理员；已有任何用户时拒绝，不开放 HTTP 初始化接口。若要让其他用户自行注册，先在 `.env` 配置真实 SMTP 并启用 `SMTP_ENABLED=true`。健康检查只证明服务可运行，不证明每个平台有真实媒体证据。

### Temporal 首次配置与重启

解析调度使用固定版本的单节点 Temporal Server，复用现有 PostgreSQL 实例中的 `framefetch_temporal` 和 `framefetch_temporal_visibility` 两个专用库。首次安装时由数据库管理员创建 `framefetch_temporal` 登录角色、交互设置强密码，再建立两个同属该角色的库；已存在时直接复用，不重置密码或重建库：

```bash
psql -d postgres -c 'CREATE ROLE framefetch_temporal LOGIN'
psql -d postgres -c '\password framefetch_temporal'
createdb -O framefetch_temporal framefetch_temporal
createdb -O framefetch_temporal framefetch_temporal_visibility
```

将同一个密码保存到部署环境文件的 `TEMPORAL_POSTGRES_PASSWORD`，文件权限设为 `0600`。`TEMPORAL_POSTGRES_USER` 默认 `framefetch_temporal`；容器使用已有的 `POSTGRES_HOST/PORT`。`temporal-schema` 使用对应版本官方工具幂等初始化，工作进程首次连接时幂等创建 `framefetch` 命名空间。普通 `docker compose up -d --build --wait` 重启复用配置与数据库，不重新生成密码。CLI／宿主 Worker 地址默认为 `127.0.0.1:17233`，容器内部为 `temporal:7233`；不会占用其他项目默认 7233 端口。

首次切换前停止 API 接单并排空解析任务，再配套发布 API、worker 和 `migrate` 容器。R0 会删除旧治理表与解析管控列；先备份现有业务库，确认在途任务已排空。更新使用 `up --build`，不能只 `start` 旧版已退出的迁移容器。回退也需先排空新执行并恢复匹配的结构备份，不允许两套解析执行者并存。

备份业务库时同步备份两个 Temporal 库，稳定环境密钥单独保管。该服务不设置公共访问，单节点停机期间任务暂停；端口健康不等于平台可以下载。Skill 分析同样由 Temporal 调度，宿主 AI Worker 连接 `TEMPORAL_ADDRESS`（默认 `127.0.0.1:17233`）而不再连接 RabbitMQ；报告发布、下载与导入长期使用 RabbitMQ，分工见[工作流设计](docs/design/15-工作流与平台下载目标.md)。

### 平台身份与升级

宿主身份服务位于 `backend/app/workers/identity/`，扩展源码位于 `browser-extension/`，遵循[设计 17 第 3.4 节](docs/design/17-解析引擎重建.md#34-身份层)。普通用户 LaunchAgent 只监听 `127.0.0.1:19101`；WebSocket `/extension` 校验固定扩展 Origin 与双向 HMAC，`POST /cookies` 只接受 Runner Bearer。扩展先认证服务端，再按服务端声明的 Registry 域读取当前普通 Profile 的非分区 Cookie；服务端每次请求实时取材料，5 秒超时，不保存 Cookie。无扩展连接、超时、无必要账号材料分别返回 `extension_disconnected`、`extension_timeout`、`credential_missing`，Runner 保留这些子因。

从 `backend/` 执行一次安装：

```bash
uv run python -m app.workers.identity.cli install
uv run python -m app.workers.identity.cli check
```

`install` 生成独立配对密钥和 Runner Bearer，宿主配置默认为 `~/Library/Application Support/FrameFetch/identity.env`；也可用 `--env-file /绝对路径/identity.env` 指定已有独立 `0600` 身份配置，保留其 Runner Bearer 并补建配对密钥。已有安装升级会保留两份密钥，只更新扩展文件并重启本服务。不得把项目 `.env` 当作宿主身份配置。安装注册 `gui/<uid>` 下的普通 LaunchAgent，不要求 Aqua 会话、钥匙串授权或完全磁盘访问；服务运行依赖此 checkout 的 backend 与 uv 虚拟环境，不要删除它们。`uninstall` 停止并移除本 LaunchAgent，保留配对文件以便重装。

在 Chrome 120+ 打开 `chrome://extensions`，开启开发者模式，选择“加载已解压的扩展程序”，目录为 **`~/Library/Application Support/FrameFetch/extension/`**（install 输出绝对路径）。只加载到日常登录的一个普通 Profile；扩展只申请 cookies、alarms 及 Registry required/optional 平台 Cookie 域和本机 WebSocket 权限。加载后 `check` 报告实际连接状态与扩展版本；Chrome 停止或尚未加载时显示 `connected=false`、`version=null`。升级后在扩展页点一次“重新加载”，或重启 Chrome。

扩展目录 `0700`、文件 `0600`，密钥和端口仅写入安装目录的 `config.js`，不在 web_accessible_resources 中、不进入源码或发行包。**信任边界**：这些权限隔离网页与其他用户，不能隔离同一 macOS 用户下可读写该目录的恶意进程。扩展和 cookie-source 共享配对密钥；Runner Bearer 是另一份独立凭据，不能复用。双向 HMAC 防止无配对密钥的本机假服务骗取 Cookie；不会赋予内容导出权利或扩大 content_scope。

Compose 仅向 `session-runner` 注入宿主配置中相同的 `COOKIE_SOURCE_TOKEN`（通过调用 Compose 的进程环境传入，禁止输出令牌）；API、worker、egress-proxy 和 bgutil 不持有它。不要把整个宿主身份配置作为容器 env_file，配对密钥不进入任何容器。当前 Compose 与 squid 配套固定使用端口 `19101`，调整端口须同步精确代理 ACL。Runner 身份客户端显式使用受控代理，不使用环境代理、不跟随重定向；squid 只放行 `POST host.docker.internal:19101/cookies`，强制直连，不经过 Clash／住宅上游。其他宿主端口、私网和 IP 字面量仍被拒绝。身份传输是明文 HTTP，egress-proxy 属于敏感信任组件，配置关闭访问日志、缓存和响应体存储。安装只启动宿主服务，Runner 的配套令牌与重建按运行时锁协议在真实验收时确认。

扩展使用 20 秒心跳、30 秒 alarm 和上限 30 秒的指数退避，并同步注册启动事件。保活机制依据 [Chrome WebSocket 文档](https://developer.chrome.com/docs/extensions/how-to/web-platform/websockets)；真实关闭 DevTools、睡眠唤醒与各类重启恢复仍须实测。

R2 调用约定（不改动 `ladder.py` 或 3.8 的签名）：

- `await fetch_identity(site, task_id, deadline)` 返回 `IdentityMaterial(cookie_file, digest)`；失败统一抛出 `LayerFailure(identity_unavailable)`，不自动重试。deadline 传本次操作的原截止时间。
- required 在每次解析／下载操作开始时获取；optional 仅在分类后的 `login_required` 证据出现后，同任务获取一次并重试同层；none 永不调用。身份策略不扩张 content_scope。
- 将材料及 `material.cookie_file` 放入不可变 `RunContext` 的副本（P1 的 `with_material`，未接入时可用 `dataclasses.replace`），执行层消费此副本。成功时写 `identity_used=true`、`identity_digest=material.digest`，并通过 `Resolution.run_context` 返回材料；下载前重新获取并核对摘要。
- 失败／取消路径调用 `material.cleanup()`；成功路径由 service 持有到 HTTP／浏览器下载交接结束后再清理。不要在 `run_ladder` 返回之前销毁材料。`IdentityOperation` 仅适用于上下文范围覆盖完整操作及交接的调用者：进入时处理 required，`after_login_required()` 处理 optional 一次，退出统一清理；只包围阶梯函数会提前删除成功材料。直接使用 `fetch_identity` 时调用方承担相同的 finally 所有权。

Cookie 文件位于 Linux tmpfs `/tmp/framefetch-identity/<operation>/cookies.txt`，目录 `0700`、文件 `0600`；Runner lifespan 接单前清空此目录。摘要仅使用必要账号 Cookie 的稳定 HMAC，忽略访客 Cookie 与过期时间续期。当前保留已核对的 Instagram 和腾讯视频必要字段；其他平台字段未核对时返回 `identity_cookie_rules_unverified`。材料存在不证明账号有效或完整文件可用。真实 Chrome 重连、网络隔离、异常退出与需要身份的正例留待扩展加载后专项验收；阶段状态与实际证据见设计 17 第 8 节。

升级前暂停接单并排空媒体操作，备份业务库，幂等执行当前 schema.sql，再配套重建 API、worker、session-runner 与前端。移除旧 broker 由 Compose 的 `--remove-orphans` 完成，不删除用户业务记录或制品。生产入口：

```bash
docker compose --env-file .env.prod -f docker-compose-prod.yml up -d --build --wait --remove-orphans
```

启动后访问：

- Web 应用：<http://localhost:8101>
- Swagger UI：<http://localhost:8111/docs>
- OpenAPI：<http://localhost:8111/openapi.json>

健康检查：

```bash
curl --fail http://127.0.0.1:8111/health/live
curl --fail http://127.0.0.1:8111/health/ready
curl --fail --head http://127.0.0.1:8101/
```

只需要下载与剧本文档导入时，可在 `.env` 中设置 `ANALYSIS_ENABLED=false`。完整的启动、停止、已有基础环境复用和故障恢复方式见[可靠性与运行](docs/design/13-可靠性与运行.md)。更新代码时先执行 `git pull --ff-only`，再按上面的命令构建启动 Compose；`docker compose restart` 不会应用新代码、镜像或环境配置。

### 启用 AI 分析

AI Worker 独立运行，不包含在业务 Compose 中。默认线路可以复用宿主机已登录的 Codex App Server；管理员也可在 Web 中配置受支持的模型 Provider。宿主机 Agent 的统一管理入口为：

```bash
cd backend
uv sync --frozen --dev
uv run python -m app.workers.analysis.agent_cli doctor
uv run python -m app.workers.analysis.agent_cli install
uv run python -m app.workers.analysis.agent_cli status
```

生产业务使用 `.env.prod` 时，宿主机 Agent 必须读取同一环境文件：

```bash
uv run python -m app.workers.analysis.agent_cli doctor --env-file ../.env.prod
uv run python -m app.workers.analysis.agent_cli install --env-file ../.env.prod
```

不要把 Codex/Claude OAuth 目录复制或挂载进容器。启用第三方模型前，请使用已获授权样本完成一次真实分析验收，并确认模型服务条款和组织数据策略。

## 架构

```mermaid
flowchart LR
  Browser[Web / Mobile Client] --> Frontend[Next.js :8101]
  Frontend --> API[FastAPI :8111]
  API --> DB[(PostgreSQL)]
  DB --> Outbox[Transactional Outbox]
  Outbox --> Temporal[Temporal]
  Temporal --> Resolve[Resolve Activity]
  Resolve --> Runner
  Outbox --> MQ[RabbitMQ]
  MQ --> Download[Download Worker]
  MQ --> Documents[Import / Report Workers]
  Download --> Runner[Isolated Media Runner]
  Runner --> Proxy[Controlled Egress Proxy]
  Download --> Storage[(MinIO)]
  Documents --> Storage
  Temporal --> HostAI[Host AI Agent]
  HostAI --> Storage
  API -. WebSocket events .-> Browser
```

| 层 | 技术 |
| --- | --- |
| Frontend | Next.js 16、React 19、TypeScript、Tailwind CSS、Radix UI |
| Backend | Python 3.12、FastAPI、SQLAlchemy、PostgreSQL |
| Async | Transactional Outbox、Temporal、RabbitMQ、Redis、幂等 Worker 与 lease/heartbeat |
| Media | FFmpeg、ffprobe、yt-dlp 适配层、隔离 Runner、Squid egress proxy |
| Storage | MinIO 对象存储与短时预签名访问地址 |
| Contract | OpenAPI 是 Web、Flutter 与服务端之间的唯一接口契约 |

完整的系统设计收录在 [docs/design/README.md](docs/design/README.md)。

## 安全与合规边界

- 只处理你拥有相应权利的内容，并遵守内容来源、所在地和部署环境适用的法律与平台规则。
- R0 只执行匿名 L1，保留内容权益和非 DRM 校验；后续账号路径以设计 17 及真实完整文件为准。私网 URL、任意 yt-dlp 参数和 shell 输入始终禁止。
- 普通业务请求不接收原始 Cookie。身份目标见设计 17 第 3.4 节，R0 不启用身份服务；设计 17 第 3.7 节的十二字段 ExecutionContext 不保存凭据。
- Edge Agent 只能传输用户已合法取得并明确选择的明文文件，不能读取平台会话、拦截流量、提取密钥或转换受保护媒体。
- 外部媒体访问必须经过阻断私网的出口代理；入口 URL 校验不能替代网络隔离。

发现安全问题时，请不要在公开 Issue 中披露利用细节、密钥或用户内容；按 [安全策略](SECURITY.md) 使用私有渠道报告。

## 当前限制

- 腾讯视频、优酷等账号平台的身份层待 R4 重建，完整文件须按设计 17 重新验收。
- 项目仍在持续演进，目前提供自托管源码和 Compose 运行方式，不承诺官方 SaaS、公共演示站或服务可用性 SLA。
- Provider 能力受来源页面和平台变化影响；平台名称不代表对所有内容、地区或账户权益都可用。
- AI 分析依赖独立宿主机 Agent 或部署方配置的模型服务，关闭 AI 不影响下载和文档导入。
- 预签名 URL 会过期，但最终制品不会因此自动删除；管理员仍需规划 MinIO 容量、备份和显式清理策略。
- 对外部署前必须检查 `.env.prod` 的实际配置，替换所有占位凭据，并完成网络、存储、Runner 和真实文件验收。

## 本地开发

前端需要 Node.js `>=24.15 <25` 与 pnpm 12，后端需要 Python `>=3.12 <3.13` 与 [uv](https://docs.astral.sh/uv/)。代码级质量门禁：

```bash
cd backend
uv sync --frozen --dev
uv run --frozen ruff check app tests
uv run --frozen mypy --strict app
uv run --frozen pytest -q

cd ../frontend
pnpm install --frozen-lockfile
pnpm lint
pnpm test
pnpm build
```

仓库主要目录：

```text
backend/                 FastAPI、领域逻辑、Worker、Runner 与当前态 SQL
frontend/                Next.js App Router、业务组件、Hooks 与 OpenAPI 客户端
docs/                    系统设计文档与 README 截图资源
backend/Dockerfile       API、Worker、Runner 镜像
frontend/Dockerfile      Next.js 独立镜像
docker-compose-env.yml   GitHub CI 隔离测试夹具，不用于本机启动
docker-compose.yml       Web、API、Worker、Runner 与出口代理
docker-compose-prod.yml  生产业务差异
```

## 路线图

各领域的实现状态与技术债统一维护在[状态与待办](docs/design/14-状态与待办.md)，规划中的创作与发布流程见[内容创作与发布](docs/design/11-内容创作与发布.md)。欢迎在 [Issues](https://github.com/StephenQiu30/video-server/issues) 中讨论优先级，带有 `good first issue` / `help wanted` 标签的任务适合首次参与。

## 参与贡献

欢迎通过 Issue 或 Pull Request 参与 Provider 适配、可靠性、前端与移动端体验、AI 报告、测试和文档建设。开始前请阅读：

- [贡献指南](CONTRIBUTING.md)
- [社区行为准则](CODE_OF_CONDUCT.md)
- [仓库协作规范](AGENTS.md)
- [文档索引](docs/design/README.md)
- [安全策略](SECURITY.md)

提交变更时，请保持实现、OpenAPI 契约、测试、运行手册和验收证据一致，并只提交小而完整、可独立验证的改动。

如果帧取对你的创作、研究或自托管实践有帮助，欢迎点亮 **Star**，并关注 [Releases](https://github.com/StephenQiu30/video-server/releases) 获取版本更新；这也是项目持续维护的最大动力。

## 引用

在论文、报告或课程材料中使用帧取时，可点击仓库侧栏的 “Cite this repository”，或直接使用根目录的 [`CITATION.cff`](CITATION.cff)。版本变更见 [Releases](https://github.com/StephenQiu30/video-server/releases)。

## 许可证

FrameFetch 基于 [MIT License](LICENSE) 开源。MIT 许可证授予软件使用、修改和分发权，不代表授予任何第三方媒体内容的下载、复制或分析权。

公开网站的索引配置、生成式搜索可发现性与上线核查见 [Web 体验与 SEO](docs/design/12-Web体验.md)。个人自托管实例默认不开放索引。

冷启动矩阵的两种模式、运行时锁、样本证据与文件校验用法见 [Backend README](backend/README.md#冷启动矩阵设计-17)。
