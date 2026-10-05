# Backend

FastAPI API、下载/分析领域逻辑、异步 Worker、当前态数据库 SQL 和 Python 测试位于本模块。

所有 Python 与 `uv` 命令都应从 `backend/` 执行。数据库当前结构定义在可重复执行的 `sql/schema.sql`；由部署者按需在已有项目数据库中幂等加载；业务启动不创建基础服务，也不重复初始化已有环境。项目不维护迁移历史或旧 schema 兼容路径。本目录 `Dockerfile` 构建 API、Worker 与 Runner 镜像；前端使用 frontend/Dockerfile 独立构建。

## 解析引擎

当前 Runner 通过 Registry 阶梯执行 HTTP 提取、证明准备和浏览器解析，统一使用 egress-proxy 与最终制品校验。宿主身份由 `workers/identity/` 的 cookie-source 和根 `extension/` 的 Chrome 扩展提供。运行命令见[根 README](../README.md)，协议、平台范围和验收状态只在[解析引擎](../workspace/content/design/14-解析引擎.md)与[平台身份](../workspace/content/design/15-平台身份.md)维护。

浏览器卷只保存浏览器原生状态；身份材料只在 Runner 内存与私有 tmpfs 中存在。样本位于 `scripts/fixtures/`，冷启动矩阵使用 `coldstart_cases.json`。组件健康不证明平台完整文件可用。

## 目录约定

```text
app/
├── main.py           FastAPI 工厂、注册和启动入口
├── api/              路由、Depends、HTTP 异常和中间件
├── core/             配置、数据库连接、安全、资源装配和生命周期
├── models/           SQLAlchemy 实体
├── schemas/          Pydantic HTTP 契约
├── repositories/             数据操作和事务
├── services/         业务操作、内部类型及就近维护的 rules/skills
├── integrations/     外部系统适配
└── workers/          Worker、独立 Runner 及各自进程入口
```

完整文件职责与依赖规则以根 PROJECT.md 为准。直接从定义模块导入业务符号；不维护平行 domain、顶层 runner、顶层技能资源或大量重导出。Runner 保留隔离容器与网络边界。

公共接口不维护无实际兼容需求的版本目录或 URL 前缀。服务启动后可通过 `/docs` 访问 Swagger UI，通过 `/openapi.json` 获取供前端生成客户端的 OpenAPI 契约。

业务接口要求邮箱账户登录。注册前调用 `POST /api/auth/registration-code`（App 使用 `/api/app/v1/auth/registration-code`）发送验证码，再调用对应的 `/registration-code/verify` 验证邮箱，最后提交唯一用户名、邮箱、密码和 `verification_code`；验证码 10 分钟有效、重发间隔 60 秒，最多校验错误 5 次。SMTP 接受后 `email_sent=true`，不代表已到达收件箱。未配置邮件时注册不能绕过验证；既有账户继续使用邮箱密码登录。`SMTP_*` 配置由根目录 `.env` 提供。密码使用 Argon2 哈希。Web 使用单一随机 `HttpOnly` Cookie，PostgreSQL `web_sessions` 仅保存 SHA-256 摘要、空闲／绝对截止和撤销时间；默认空闲 7 天、绝对 30 天，普通请求最多每分钟续一次空闲期，不轮换 Cookie，WebSocket 心跳不续期。读取会话与退出遇到存储故障返回 503，不清除 Cookie，不把故障当成未登录。Web 的 `/api/auth/refresh` 已移除，浏览器不再刷新 JWT 或自动重放业务请求。App 的 Access／Refresh Bearer 协议、Redis 原子轮换独立保留；Web 与 Native 认证端点不相互接受凭据，共享业务端点在显式 Bearer 失败时不回退 Cookie。`AUTH_WEB_COOKIE_NAME`、`AUTH_WEB_IDLE_TTL_SECONDS`、`AUTH_WEB_ABSOLUTE_TTL_SECONDS` 由根 `.env` 配置；生产和 staging Cookie 使用 Secure。初始管理员邮箱属于保留账号，只有注册请求同时携带与 `AUTH_BOOTSTRAP_ADMIN_SECRET` 匹配的 `X-Admin-Bootstrap-Secret` 请求头时才会创建管理员；普通匿名注册永远只创建普通用户。角色和启用状态以 PostgreSQL 为准，管理员可通过 `/api/admin/users` 管理账号，并通过 `/api/admin/providers` 维护平台状态目录的名称、排序与可见性。平台目录不控制域名匹配、Extractor、Runner 参数或会话能力。


Web 登录、注册、退出和 Cookie 写操作都校验精确 Origin（缺失时使用 Referer），缺失、`null`、异源或端口不符均拒绝。API 只信任配置的代理 IP／CIDR 转发的 Host／Proto；Next 同源代理覆盖调用方伪造的 forwarded host。WebSocket 同样走浏览器同源代理并校验来源，存储异常关闭为可重试的 1013，确认撤销／过期才使用 4401。签名上传沿用独立 capability、长度与目标校验，不消耗 Web Cookie 权限。

当前用户可通过 `/api/users/me/avatar` 上传、读取和移除头像。上传只接受最大 4 MB 的 JPEG、PNG 或 WebP，服务端校验图片、裁切为 256×256 WebP 并去除原文件元数据；头像保存在当前用户数据库记录中，仅本人鉴权读取。部署此版本前先幂等应用 `sql/schema.sql`，使已有 `users` 表增加头像列。

浏览器登录、注册和退出通过同源 Web Locks 串行写 Cookie，避免另一标签页迟到的响应覆盖新身份。等待最多 30 秒；等待期间身份变化则取消这次操作，普通读取不占锁。Web 入口须使用 HTTPS（本地开发可用 localhost／回环地址）和支持 Web Locks 的现代浏览器；不支持时明确提示，不降级成无协调的凭据写入。

Media Runner 从 `app/workers/runner/plugins/yt_dlp_plugins/` 加载可信站点提取器；平台差异由 Registry、薄插件与浏览器响应解析函数实现，所有媒体任务共用一个 session-runner。内容、阶梯及身份边界见[解析引擎](../workspace/content/design/14-解析引擎.md)，不以 Generic 提取器或 Cookie 的存在自动开放未知站点。

管理员只读接口 `GET /api/admin/provider-runtime/engine-catalog` 查询 Runner 实际安装的提取器、插件与版本快照；不会访问平台或读取账号材料，提取器数量不代表可下载的平台数。

本轮保留原页面与表单，恢复 `GET /api/analysis-skills` 及视频／文档原分析创建语义。目录保留默认提示词等原字段，请求支持中／英文与4000字自定义提示词；实际正式契约由OpenAPI生成。优化内置方法加载、完整来源、依据及输出内容，使用适合任务的原结果契约和报告布局，不建立双源工作台。实现及真实验收状态见执行计划。

API 在 PostgreSQL 事务内保存 AnalysisJob／Run、固定来源与 Outbox，宿主 Worker 在 Temporal `ff-skill` 执行；模型调用复用 Step 日志，未知回执不自动重发，方法实际执行类型与资源约束由内置定义控制。没有作品、母稿、人工版本确认、预算表单、文章写作或图卡制作。活动 creation 接口与执行注册清退，原数据库数据保留；既有 analysis 历史 reader 仍校验 owner。正式实现状态和重新验收见[执行计划](../workspace/content/plan/PLAN-内置Skill能力整合.md)。

内置 `local-codex` 不可删除或改造为第三方结构；模型和线路仅由数据库 Web Profile 决定，`.env` 只保留宿主机 CLI 二进制路径。

## 资源准入

Registry 的阶梯、出口、identity 与 content_scope 统一遵循[解析引擎](../workspace/content/design/14-解析引擎.md)。`POST /api/download-intents` 在事务提交后返回 202，Outbox 直接启动单 resolve Activity 的 InspectionWorkflow，ff-inspect 保留两个槽。解析使用 120 秒总期限，业务库保存 generation、当前状态、结果及 ExecutionContext，不保存预算或操作账本；取消传播到 Runner 进程组。下载 Job 继续通过 RabbitMQ lease/heartbeat 执行。解析按每日任务计量、零下载字节；同幂等键重放不重复计量。

高成本路由显式声明速率策略，PostgreSQL 在资源/run/outbox 创建事务内统一检查账户及全局配额。配置入口为 `RATE_LIMIT_POLICIES` 与 `QUOTA_LIMITS`；幂等重放不重复扣减，取消释放活跃名额，物理清理完成后释放保留存储。报告超限是可见的终态失败；取消后迟到的报告只进入清理流程。完整计量口径和生产边界见 [配额与容量](../workspace/content/design/05-准入配额与容量.md)。

分片上传使用 AWS SDK 的 SigV4 查询签名绑定每片精确长度，MinIO 在接收时拒绝长度不匹配；Next.js 上传代理保留 `Content-Length`。可用隔离 MinIO 运行 `TEST_MINIO_ENDPOINT=... TEST_MINIO_ACCESS_KEY=... TEST_MINIO_SECRET_KEY=... uv run pytest tests/integration/test_upload_size_boundary.py`；设置 `TEST_NEXT_UPLOAD_ORIGIN` 可一并验证独立前端代理。

## 运行与就绪

完整启动与更新统一使用[根 README](../README.md)，复用已有基础服务与环境配置。API readiness 检查核心业务依赖，不等待平台就绪；安装版本与引擎目录只用于诊断，真实平台能力须完整文件验收。

只调试无异步依赖的 API 路由时，才使用 Python 模块入口：

```bash
uv sync --frozen --dev
uv run python -m app.main
```

该命令是后端模块调试入口，不替代完整本地拓扑中的 Worker、Runner 与前端构建。

宿主机 AI Worker 不属于 Compose，默认作为本机 Codex App Server Worker 独立受监督；第三方 Provider 从 Web 管理页选择，不通过额外启动脚本或 `.env` 切换。只使用跨平台 Agent 管理入口：

```bash
uv sync --frozen --dev
uv run python -m app.workers.analysis.agent_cli doctor
uv run python -m app.workers.analysis.agent_cli install
uv run python -m app.workers.analysis.agent_cli status
```

上述命令默认读取仓库根目录 `.env`。当业务容器通过 `.env.prod` 运行时，宿主机
Agent 必须显式使用同一环境文件，避免 API、队列和对象存储落到不同环境：

```bash
uv run python -m app.workers.analysis.agent_cli doctor --env-file ../.env.prod
uv run python -m app.workers.analysis.agent_cli install --env-file ../.env.prod
```

API 固定监听 `8111`，前端固定监听 `8101`。API `/health/live` 只证明进程存活；`/health/ready` 还会在有界超时内检查数据库结构、MinIO、RabbitMQ 与 Redis。宿主机 AI Worker 在 `ff-skill` 队列执行内置 Skill 分析 Workflow，使用协议版本 5 的心跳，与 Temporal 断连时自动重连，并由系统服务监督进程；Worker 离线期间任务保持排队，恢复后继续观察，未知模型调用不会自动重发。没有 AI Worker 的部署必须显式设置 `ANALYSIS_ENABLED=false` 并重建 API。

## 测试目录

`tests/unit/` 按实际模块组织：services（包含业务 rules）、repositories、models、integrations、core/security、schemas 与 workers（包含 runner）；入口和配置测试直接放在 unit 下。`tests/integration/api/` 验证 HTTP 与 WebSocket，`tests/contract/` 验证公开契约及部署配置，`tests/architecture/` 检查模块依赖。移动模块时同步更新测试导入和文档命令。

## 测试数据库

后端不安装或兼容 SQLite。Repository 与集成测试默认读取根 `.env` 的 `DATABASE_URL` 并连接宿主机现有的 PostgreSQL `5432`，不会为测试启动 Docker PostgreSQL；`TEST_DATABASE_URL` 可显式覆盖。没有根 `.env` 时才使用 `postgresql+asyncpg://video:video@127.0.0.1:5432/video`。测试账号必须有创建和删除 schema 的权限；每个测试使用独立随机 schema，并在结束时级联清理。

```bash
uv sync --frozen --dev
uv run pytest
```

## 下载持久化与 API 生命周期

下载 Repository 直接实现应用层端口并返回唯一的应用模型；不建立重复的数据库 DTO、Store 或字段复制层。下载仓库使用显式组合组织事务能力，Outbox 发布由独立的 `SqlAlchemyOutboxRepository` 负责。数据库会话仍由仓库事务管理。API 工厂只定义应用；外部运行时资源在 FastAPI lifespan 启动时创建，启动失败和停止时释放。测试可在不连接外部服务的情况下导入入口并生成 OpenAPI。

API 使用 `runtime.py` 定义类型化的 `ApiServices`，在 `app.state.services` 中只挂载一次，通过 FastAPI 依赖函数读取；`lifespan.py` 管理资源所有权和释放，不逐项复制服务到动态 State。外部注入的运行时由调用方管理。

## 统一 AI API 接入

管理员可在 AI 服务中选择 OpenRouter 或 OpenAI 兼容 API。OpenRouter 使用官方固定 Base URL，读取公开模型目录后选择模型；视频要求图像输入与结构化输出。通用兼容线路自行填写模型、Base URL 和 Key，服务须支持图像与 JSON 输出。API 线路无需 CLI，但现有宿主分析 Worker、FFmpeg 与基础服务仍需运行。修改服务地址或引擎时必须重新提供 Key。设计、能力边界及验收见 [AI 分析](../workspace/content/design/09-AI分析.md)。

Web JSON 响应及全局异常统一遵循 [PROJECT.md §3.1](../PROJECT.md#51-响应与异常)。持久化代码在 repositories 内按业务聚合；业务路由使用 ApiResponseRoute，生成契约随注解自动更新。

## 系统操作日志

管理员日志入口、记录范围、故障语义和部署验证见[解析与处理记录](../workspace/content/design/06-解析意图.md)。


Temporal 回归默认复用已有服务：地址来自 `TEST_TEMPORAL_ADDRESS`，未设置时使用 `Settings.temporal_address`（默认 `127.0.0.1:7233`）。例如执行 `TEST_TEMPORAL_ADDRESS=127.0.0.1:7233 uv run pytest tests/integration/test_intent_messaging.py tests/integration/test_builtin_skill_workflow.py`。本地测试不启动另一套 Temporal；仅显式设置 `TEST_TEMPORAL_START_LOCAL=true` 时，SDK 才启动隔离测试服务，复用已有 CLI，无 CLI 时下载 v1.8.2；GitHub CI 使用此选项。测试只使用 `framefetch-test` 命名空间和 PostgreSQL 隔离 schema，不消费业务命名空间。测试覆盖确认丢失、Worker 重启、取消、History replay 以及模型调用中断后不重发，不替代真实平台与模型验收。

## 冷启动矩阵

从仓库根目录运行；先完成 `uv sync --frozen --dev`，宿主机须安装 Docker Compose、ffprobe 和 ffmpeg。矩阵使用现有账号，凭据通过 `COLDSTART_EMAIL` / `COLDSTART_PASSWORD` 或 `COLDSTART_COOKIE` 环境变量传入，禁止写到命令参数、样本或日志中。账号登录属于本站鉴权，与平台 `needs_identity` 独立。

```bash
backend/.venv/bin/python backend/scripts/coldstart_matrix.py --platforms bilibili
backend/.venv/bin/python backend/scripts/coldstart_matrix.py --all
```

两种模式都自动等待 `/tmp/framefetch-runtime.lock`，取得锁后从固定容器的 Compose project label 识别现有项目，避免 worktree 名引起新网络或容器冲突，再从当前 worktree 构建并重建 api、worker、session-runner。`--env-file` 默认为现有 `.env`，不修改该文件；不执行 schema.sql，也不启动或重置 PostgreSQL、RabbitMQ、Temporal、MinIO。Runner 和 Worker 换用本次专属工作卷，Runner 使用本次专属浏览器卷以及空的 tmpfs/HOME/XDG 缓存；日常卷不清理。运行结束（含错误、Ctrl-C 和 SIGTERM）恢复日常卷，删除本次临时卷并释放锁。SIGKILL 或宿主机断电无法执行清理，需核实 owner 和进程后人工恢复，不能删除其他阶段仍持有的锁。

身份冷启动验收带 `--cookie-source-label <实际 LaunchAgent label>` 重启已安装的 cookie-source；省略该参数时没有验证身份服务冷启动，需要身份的样本保持阻塞。
重启后最多等待 45 秒，通过携带 Runner Bearer 的宿主 `/status` 确认扩展已重新认证连接，再开始样本；等待过程中不读取 Cookie。错误令牌或重连超时会使本轮退出 2，并执行日常卷恢复与临时卷清理。

脚本仅调用正式 HTTP API：创建下载意图、轮询 Temporal 解析结果、查询 InspectionResponse、选择达到最低规格的格式、创建 RabbitMQ 下载、取回发布的 Artifact。文件通过鉴权 `/api/downloads/{id}/file` 下载，核对 Content-Length 与 ETag/SHA-256，再进行 ffprobe 和 `ffmpeg -xerror` 全片解码。独立完整时长的容差与 Runner 相同：`max(3 秒, 2% × 完整时长)`；若部署修改了 Runner 容差，使用 `--duration-tolerance` 传入同一个值。规格核对包括尺寸、编解码器、容器、帧率档与动态范围；身份和出口读取正式响应中的 execution_context。

`--platforms a,b` 只运行指定 registered 平台，要求每个平台至少两部不同作品；`--all` 要求样本平台集合与正式 `GET /api/providers` 的 registered 集合严格相等，缺少或多出平台都报错。当前该 API 暴露 25 个 Registry profiles；Generic fallback 和未配置的 PeerTube 不在该集合中。启用新的 registered 平台后必须补充样本，否则全量模式不能运行。脚本不导入 Runner，也不从静态平台状态推断通过。

样本在 `scripts/fixtures/coldstart_cases.json`，每条包含作品 ID、范围、正例/受保护负例、needs_identity、时长来源、可访问性证据和最低规格。视频号 `official_share` 只要求注明日期的匿名分享／元宝／微信官方 feed 元数据对应证据；候选文件时长用于交付一致性校验，报告明确公开免费标签、独立原长与原作品完整性未证实，规则见[平台身份第 6 节](../workspace/content/design/15-平台身份.md#6-视频号元宝解析)。其他范围仍要求独立原长与原有内容范围证据。`verified` 证据须有核实日期；其他范围的独立时长不得来自被测流或历史 yt-dlp 测试预期。当前 fixture 包含待核实候选：缺失该范围要求的证据会在 JSON/Markdown 明确保留，即使文件交付也只能记为阻塞。视频号不把候选文件时长写成独立原长。缺少必需证据的候选不满足[解析引擎第 12 节](../workspace/content/design/14-解析引擎.md#12-冷启动矩阵)的有效正例要求，需要在平台可访问后替换或补齐证据。受保护负例只有独立保护证据成立且 API 返回 content_protected 才记为 `protected_negative`，不参与平台通过判定。平台通过要求全部正例完整通过，至少两部不同作品。

结果、文件、ffprobe、完整解码日志及构建/恢复日志存到 `artifacts/coldstart/<UTC 时间>/`，可用 `--output artifacts/coldstart/<唯一名称>` 指定；目录必须不存在，避免覆盖旧证据。`matrix.json` 与 `matrix.md` 每条完成后更新，保存实际上下文、时长、大小、SHA-256、耗时和安全的失败证据。退出码：0 为选中平台全部通过，1 为完成矩阵但有失败/阻塞，2 为配置、启动或恢复错误。平台通过只依据有效样本的完整交付；阶段运行不能代替全平台验收。

矩阵脚本检查：

```bash
cd backend
uv run ruff check app tests scripts/coldstart_matrix.py
uv run ruff format --check app tests scripts/coldstart_matrix.py
uv run mypy app scripts/coldstart_matrix.py
uv run pytest
```

YouTube 的 L2 只启用 bgutil HTTP PO Token 提供者；L3 只启用 WPC，
由 yt-dlp 在 session-runner 内启动 nodriver Chromium，使用 Xvfb 提供显示。
两层的代理均来自当前任务的 EgressBinding，账号 Cookie 仍由 cookie-source
实时提供给 yt-dlp，WPC Profile、HOME 与缓存在操作私有 tmpfs 中，结束或取消后删除。
WPC 不复用 Playwright context，也不操作宿主 Chrome。
共享环境冷启动验收使用 `coldstart_matrix.py --platforms youtube --reuse-cookie-source`，
复用已经连接的宿主身份服务；该模式只冷启动 API、Worker、Runner，报告如实记录
宿主服务未重启。Runner 仍须通过环境变量 `COOKIE_SOURCE_TOKEN` 配置该服务的
独立 Bearer；复用标志不会安装服务、读取配对密钥或绕过身份校验。
`--reuse-cookie-source` 只允许与 `--platforms` 一起使用，`--all` 会在构建、重启或创建结果目录前拒绝此组合，避免把宿主热服务当作最终冷启动证据。
机房出口必须实际注入登录身份，仍须两条独立公开、免费、非 DRM
正例通过完整文件校验；当前可用性与实测结果见[验证状态](../workspace/content/design/14-解析引擎.md#13-验证状态)。
