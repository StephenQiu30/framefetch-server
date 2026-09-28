# Backend

FastAPI API、下载/分析领域逻辑、异步 Worker、当前态数据库 SQL 和 Python 测试位于本模块。

所有 Python 与 `uv` 命令都应从 `backend/` 执行。数据库当前结构定义在可重复执行的 `sql/schema.sql`；由部署者按需在已有项目数据库中幂等加载；业务启动不创建基础服务，也不重复初始化已有环境。项目不维护迁移历史或旧 schema 兼容路径。本目录 `Dockerfile` 构建 API、Worker 与 Runner 镜像；前端使用 frontend/Dockerfile 独立构建。

## 站点会话（046）

需要登录态的平台统一为“站点会话”：部署者在本机执行一次 `uv run python -m app.workers.session.seed import --site <站点>`，从 Chrome 读取该站点 Cookie、以 `SITE_SESSION_ENCRYPTION_KEY` 加密写入 PostgreSQL `site_sessions`。之后全部在容器内运行：

- `session-broker`（`app/workers/session/broker_app.py`）唯一持有密钥，维护状态机、调度保活，并为每个 Runner 任务签发绑定任务与站点的一次性加密租约。
- `session-browser`（`app/workers/session/browser_app.py`，Dockerfile `session-browser` 目标）为每个站点保存持久 Chromium Profile，验证登录、保活并采集平台轮换后的 Cookie；没有数据库与密钥。
- `session-runner`（`RUNNER_ACCESS_MODE=operator_managed`）只在 tmpfs 中为单次操作写入 `0600` Cookie jar，操作结束即删除。

已导入会话的站点一律走会话路线，不回退匿名。密钥必须稳定并与数据库备份分开保管；丢失后需要重新导入。运维步骤见 [站点会话运行手册](../docs/operations/011-站点会话运行手册.md)。

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

完整文件职责与依赖规则以根 PROJECT.md 为准。直接从定义模块导入业务符号；不维护平行 domain、顶层 runner、顶层技能资源或大量重导出。Runner 仍使用原来的隔离容器与会话边界。

公共接口不维护无实际兼容需求的版本目录或 URL 前缀。服务启动后可通过 `/docs` 访问 Swagger UI，通过 `/openapi.json` 获取供前端生成客户端的 OpenAPI 契约。

业务接口要求邮箱账户登录。注册前调用 `POST /api/auth/registration-code`（App 使用 `/api/app/v1/auth/registration-code`）发送验证码，再调用对应的 `/registration-code/verify` 验证邮箱，最后提交唯一用户名、邮箱、密码和 `verification_code`；验证码 10 分钟有效、重发间隔 60 秒，最多校验错误 5 次。SMTP 接受后 `email_sent=true`，不代表已到达收件箱。未配置邮件时注册不能绕过验证；既有账户继续使用邮箱密码登录。`SMTP_*` 配置由根目录 `.env` 提供。密码使用 Argon2 哈希。Web 使用单一随机 `HttpOnly` Cookie，PostgreSQL `web_sessions` 仅保存 SHA-256 摘要、空闲／绝对截止和撤销时间；默认空闲 7 天、绝对 30 天，普通请求最多每分钟续一次空闲期，不轮换 Cookie，WebSocket 心跳不续期。读取会话与退出遇到存储故障返回 503，不清除 Cookie，不把故障当成未登录。Web 的 `/api/auth/refresh` 已移除，浏览器不再刷新 JWT 或自动重放业务请求。App 的 Access／Refresh Bearer 协议、Redis 原子轮换独立保留；Web 与 Native 认证端点不相互接受凭据，共享业务端点在显式 Bearer 失败时不回退 Cookie。`AUTH_WEB_COOKIE_NAME`、`AUTH_WEB_IDLE_TTL_SECONDS`、`AUTH_WEB_ABSOLUTE_TTL_SECONDS` 由根 `.env` 配置；生产和 staging Cookie 使用 Secure。初始管理员邮箱属于保留账号，只有注册请求同时携带与 `AUTH_BOOTSTRAP_ADMIN_SECRET` 匹配的 `X-Admin-Bootstrap-Secret` 请求头时才会创建管理员；普通匿名注册永远只创建普通用户。角色和启用状态以 PostgreSQL 为准，管理员可通过 `/api/admin/users` 管理账号，并通过 `/api/admin/providers` 维护平台状态目录的名称、排序与可见性。平台目录不控制域名匹配、Extractor、Runner 参数或会话能力。


Web 登录、注册、退出和 Cookie 写操作都校验精确 Origin（缺失时使用 Referer），缺失、`null`、异源或端口不符均拒绝。API 只信任配置的代理 IP／CIDR 转发的 Host／Proto；Next 同源代理覆盖调用方伪造的 forwarded host。WebSocket 同样走浏览器同源代理并校验来源，存储异常关闭为可重试的 1013，确认撤销／过期才使用 4401。签名上传沿用独立 capability、长度与目标校验，不消耗 Web Cookie 权限。

当前用户可通过 `/api/users/me/avatar` 上传、读取和移除头像。上传只接受最大 4 MB 的 JPEG、PNG 或 WebP，服务端校验图片、裁切为 256×256 WebP 并去除原文件元数据；头像保存在当前用户数据库记录中，仅本人鉴权读取。部署此版本前先幂等应用 `sql/schema.sql`，使已有 `users` 表增加头像列。

浏览器登录、注册和退出通过同源 Web Locks 串行写 Cookie，避免另一标签页迟到的响应覆盖新身份。等待最多 30 秒；等待期间身份变化则取消这次操作，普通读取不占锁。Web 入口须使用 HTTPS（本地开发可用 localhost／回环地址）和支持 Web Locks 的现代浏览器；不支持时明确提示，不降级成无协调的凭据写入。

此次 Web 协议需要前后端配套发布：先执行当前 `backend/sql/schema.sql`，再同时替换 API 和 Web 镜像；旧 Web 会话需重新登录一次，原有用户、任务、App 协议保留。普通服务重启复用 PostgreSQL 会话事实。回滚优先回到仍支持不透明会话的已验证镜像；不得只降级某一端，或把旧双 JWT Web 重新接入现有会话。若必须退回切换前版本，应停写并明确重新登录、旧凭据失效与 App 受影响范围，不能承诺透明回滚。完整执行证据与尚未完成的验收见 [P9.11](../docs/plan/044-开源部署无感解析Plan.md#p9-11)。

Media Runner 通过 `app/workers/runner/plugins/yt_dlp_plugins/` 加载随项目交付的可信站点提取器。MediaTrack 适配仅处理无需登录的公开审片视频和 API 明确授权的播放转码；抖音适配用数字视频 ID 构造固定公开分享页并修正 landscape 下载规格的短边尺寸语义，TikTok 适配只使用其第一方嵌入播放器 item API 和 yt-dlp 默认客户端，明确无 item/HTTPS 格式、API 临时故障与响应结构漂移分别返回链接不可用、临时不可用和提取器回归，不回退网页挑战；快手适配把公开作品规范化到第一方移动分享页并限制短链重定向域，Tumblr 适配优先读取当前 `www.tumblr.com` 公开页而不强制改写到旧 blog 子域。小红书适配识别第一方 `300031` 笔记失效和 `300012` 平台验证边界，避免把失效内容误报成提取器故障。视频号适配只接受公开 `weixin.qq.com/sph/...` 单视频，读取第一方公开信息，并可在受控线路使用专用元宝会话解析；只接受批准腾讯媒体域上的非加密媒体，保护材料直接拒绝。所有适配都继续经过受控代理、作品身份校验、大小/时长限制、重新 inspect、FFmpeg 和 ffprobe 校验，不支持图集截断、账号内容、无水印承诺或原文件权限绕过。

主流视频源使用声明式 Provider Profile 接入：`provider_catalog_*.py` 按策略族登记能力和运行参数，`ProviderRegistry.prepare()` 一次解析得到贯穿 inspect/download 的不可变 `ProviderRequest`，`YtDlpCommandBuilder` 只消费该请求生成固定参数，错误由有序 `FailureRule` 归一化。已有 yt-dlp extractor 的公开单视频平台通常只需增加一个 Profile、契约测试和 metadata/media canary；需要自定义解析时再按 yt-dlp 官方插件目录增加可信 extractor，不修改通用命令执行器。未知站点使用无凭据 Generic extractor；导入了站点会话的任何站点（包括未适配站点）改走 `session-runner`。

管理员可通过只读接口 `GET /api/admin/provider-runtime/engine-catalog` 查询匿名 Runner 实际安装的提取器及项目插件，获取安装版本、固定依赖是否匹配和清单摘要；extractor 数量不代表可下载的平台数。首次读取在独立子进程中有界枚举，后续复用当前进程快照，更新镜像后重新生成；不访问平台、不读取账号材料。API 或 Runner 缺失时返回服务不可用，不改变本站身份。平台策略、部署就绪和真实下载证据仍分别由 Profile、管理员运行诊断 API 与实际下载验证决定。

微博公开单视频支持普通帖子、移动端 status/detail、`video.weibo.com` 视频页和 `t.cn` 分享短链。短链插件在取得有效微博视频地址后立即交给微博提取器，避免通用网页跳转进入访客页面；使用无账号凭据的受控 Runner，容器重启后重新解析即可。分阶段接入设计见 [017 设计](../docs/design/017-其他短视频平台分阶段接入设计.md)。

视觉分析默认通过宿主机 Codex App Server stdio 协议运行，也支持 `claude -p` adapter 和 Web 管理的 DeepSeek/LangChain 视觉 API，以及 OpenRouter / OpenAI 兼容 Chat Completions API；各适配器统一实现 `VideoAnalyzer` 端口并返回唯一当前态结果契约。每个 Codex 调用创建独立 ephemeral thread，完成后关闭进程，不依赖长期连接。DeepSeek 由 Worker 使用 FFmpeg 均匀生成最多 64 张、总原始证据不超过 24 MiB 的顺序 JPEG，以 base64 内联图片调用视觉模型，不暴露对象地址或客户端文件路径。分析能力由 `app/services/analysis/skills/*/SKILL.md` 注册；不运行 ASR。第三方 Endpoint、模型与 Key 只通过管理员 Web Profile 配置，Key 使用 Fernet 加密后存入 PostgreSQL 并仅在 Worker 内存中解密，不使用第三方 AI `.env`。报告以 Markdown 为唯一内容源，可安全预览和导出 Markdown/DOCX。Worker 必须在可访问 FFmpeg、队列和对象存储的宿主机运行；默认 Codex 路径还要求同一系统用户已完成官方登录。

内置 `local-codex` 不可删除或改造为第三方结构；模型和线路仅由数据库 Web Profile 决定，`.env` 只保留宿主机 CLI 二进制路径。

## 资源准入

在线解析统一使用容器自持站点会话，未配置或撤销时明确拒绝，不回退匿名／访客路线。导入、自动维护、重启恢复和人工重新登录边界见 [站点会话运行手册](../docs/operations/011-站点会话运行手册.md)。

持久解析入口为 `POST /api/download-intents`，接单提交后返回 202；查询和取消使用同一资源 ID。API 不等待上游解析。下载 Worker 的独立解析消费槽通过 `download.intent.requested` 事件执行，失联租约和重试由同一恢复循环收敛；解析总预算 180 秒、最多三次执行。用户取消后 Worker 停止 HTTP 操作，Runner 断连处理终止实际子进程。新入口和双客户端切换状态见 [044 Plan](../docs/plan/044-开源部署无感解析Plan.md#p9-02)。解析按每日任务计量、零下载字节，同幂等键重放不重复计量。Worker 与 API 使用相同 `REQUEST_FINGERPRINT_SECRET`，生产环境禁止开发默认值。

高成本路由显式声明速率策略，PostgreSQL 在资源/run/outbox 创建事务内统一检查账户及全局配额。配置入口为 `RATE_LIMIT_POLICIES` 与 `QUOTA_LIMITS`；幂等重放不重复扣减，取消释放活跃名额，物理清理完成后释放保留存储。报告超限是可见的终态失败；取消后迟到的报告只进入清理流程。完整计量口径和生产边界见 [上线准入设计](../docs/design/006-上线产品能力补全设计.md)。

分片上传使用 AWS SDK 的 SigV4 查询签名绑定每片精确长度，MinIO 在接收时拒绝长度不匹配；Next.js 上传代理保留 `Content-Length`。可用隔离 MinIO 运行 `TEST_MINIO_ENDPOINT=... TEST_MINIO_ACCESS_KEY=... TEST_MINIO_SECRET_KEY=... uv run pytest tests/integration/test_upload_size_boundary.py`；设置 `TEST_NEXT_UPLOAD_ORIGIN` 可一并验证独立前端代理。

## 运行与就绪

本机必须先提供 PostgreSQL、RabbitMQ、Redis 和 MinIO，并预置数据库 schema、消息拓扑、对象存储身份与 bucket。随后从仓库根目录启动前端、API 和业务 Worker；业务 Compose 只连接已有基础设施，沿用当前 `.env`，不再启动另一套环境：

```bash
docker compose --env-file .env -f docker-compose.yml up -d --build --wait
docker compose --env-file .env -f docker-compose.yml ps --all
```

这是完整项目唯一的运行入口，不需要宿主进程。站点会话暂不可用只影响对应站点，不阻断核心 API。
更新代码时先独立执行 `git pull --ff-only`，再重复该命令；不要使用不会应用镜像或配置变化的
`docker compose restart`。固定 Provider 探针仍是独立验收步骤。

本地开发复用 Homebrew 的 PostgreSQL、RabbitMQ、Redis 和 MinIO，业务进程仍只通过根 Compose 启动。根目录 `.env` 应分别使用标准端口 `5432`、`5672`、`6379` 和 `9000`。确认 `brew services list` 中四项均为 `started` 后，从根目录执行：

```bash
docker compose --env-file .env -f docker-compose.yml up -d --build --wait
```

该入口启动前端、API、Media Runner、Outbox、下载/导入/报告 Worker、Provider Canary 与站点会话服务；所有进程读取根目录 `.env`。只启动 API 时，HTTP 查询仍可用，但 Outbox 不会发布、异步任务不会被消费，平台状态也无法取得 Runner 上下文。

只调试无异步依赖的 API 路由时，才使用 Python 模块入口：

```bash
uv sync --frozen --dev
uv run python -m app.main
```

该命令是后端模块调试入口，不替代完整本地拓扑中的 Worker、Runner 与前端构建。

当 `.env` 的 `RUNNER_OPERATOR_BASE_URLS` 声明 Provider Operator 时，需要使用受控
会话的平台还必须启动对应 Profile：

```bash
docker compose --env-file .env -f docker-compose.yml \
  --profile youtube-operator --profile douyin-operator \
  --profile reddit-operator --profile wechat-channels-operator up -d --build
```

API readiness 与媒体 Runner 健康隔离。在线解析只使用 `session-runner`，未导入会话的平台明确拒绝执行。API、
下载 Worker 与 Canary 不等待平台健康；Worker/Canary 仅等待共享工作目录初始化。
站点会话的可用性由 broker 状态、探针和真实任务证明，容器健康不代表平台接受会话。
开发环境只需启用 `.env` 实际声明的平台 Profile。腾讯与优酷的实验个人线路仅在生产 Compose 提供，接入范围和未完成验证见 [032 设计](../docs/design/032-腾讯视频与优酷个人下载设计.md)。

固定 Provider 诊断矩阵和真实媒体探针命令见
`docs/operations/007-固定Provider探针运行手册.md`。

`GET /api/providers` 将 Registry 发布验收基线、近期固定探针和已经生成完整制品的
真实下载合并展示。长期无人使用或未配置探针不会撤销已验收能力；近期重复失败仍会
自动降级对应平台。真实任务投影只使用非敏感 Provider 上下文与完成时间，不读取或
公开来源 URL、账号和 Cookie。`browser` 只是本机动态来源标识；关联的近期成功
表示该来源曾在相同非敏感上下文生成完整制品，不是当前 Cookie 内容 cohort，也不能单独证明
当前会话可用或将 `access_required` 提升为 `verified`。

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

API 固定监听 `8111`，前端固定监听 `8101`。API `/health/live` 只证明进程存活；`/health/ready` 还会在有界超时内检查数据库结构、MinIO、RabbitMQ 与 Redis。宿主机 AI Worker 内部重连消费者并由系统服务监督进程；短暂故障期间任务保持 queued，恢复后继续消费。没有 AI Worker 的部署必须显式设置 `ANALYSIS_ENABLED=false` 并重建 API。

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

管理员可在 AI 服务中选择 OpenRouter 或 OpenAI 兼容 API。OpenRouter 使用官方固定 Base URL，读取公开模型目录后选择模型；视频要求图像输入与结构化输出。通用兼容线路自行填写模型、Base URL 和 Key，服务须支持图像与 JSON 输出。API 线路无需 CLI，但现有宿主分析 Worker、FFmpeg 与基础服务仍需运行。修改服务地址或引擎时必须重新提供 Key。设计、能力边界及验收见 [037](../docs/design/037-统一AI执行与OpenRouter接入设计.md)。

Web JSON 响应及全局异常统一遵循 [PROJECT.md §3.1](../PROJECT.md#31-全局响应与异常)。持久化代码在 repositories 内按业务聚合；业务路由使用 ApiResponseRoute，生成契约随注解自动更新。

## 系统操作日志

管理员日志入口、记录范围、故障语义和部署验证见[系统操作日志运行说明](../docs/operations/system-operation-logs.md)。
