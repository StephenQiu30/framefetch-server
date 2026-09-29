# Server 项目协作规范

本文件适用于整个仓库，是代码代理和贡献者修改本项目时必须遵循的约定。实现、测试、文档和提交都应反映仓库当前状态，不保留无实际用途的旧结构或兼容层。

## 工程标准与目录

目标目录、模块职责、命名与接口生成规则统一由 [PROJECT.md](PROJECT.md) 定义。不得根据现有目录反推规范；新增或重构遵循目标标准，既有代码按完整业务用例逐步迁移并验证，不把文档更新视为迁移完成。

后端按 PROJECT.md 的完整目录规范组织：main.py 注册 api/routes，api/deps.py 提供 Depends，core 管理配置与生命周期；models、schemas、repositories、services、integrations、workers 各有明确职责。业务规则就近放入 services，不设置平行 domain 或批量重导出层。目录迁移须同时覆盖调用入口、事务行为、测试与部署入口。

前端使用官方 Next.js/shadcn；REST 请求与接口类型由 Swagger 自动生成到 src/api，统一调用 lib/request.ts 的 Axios 封装。前后端是独立服务，分别监听 8101、8111；长任务由独立 Worker 执行。

## 前端官方实现规范

- 工程基线使用官方 create-next-app（App Router、TypeScript、Tailwind、src 目录）和 shadcn CLI；使用 pnpm 与唯一 pnpm-lock.yaml。
- 根 `design.md` 是唯一的界面视觉设计标准来源，颜色、排版、间距、圆角、边界与页面布局均以该文件为准；其他文档不得另定视觉标准。
- 基础组件沿用现有 shadcn/ui、Radix 与 Phosphor 实现，业务页面通过组件组合实现功能。`components.json` 记录当前工程配置，不构成另一份视觉规范；官方文档用于组件 API、交互和可访问性校验。
- 基础控件保留焦点、错误、键盘和覆盖层语义；视觉实现按 `design.md` 调整，避免全局 CSS 强制覆盖或使组件变形。
- 验证包含 pnpm lint、pnpm format:check、pnpm test、pnpm build，以及桌面和 390px 的真实浏览器交互。

## 架构与数据边界

- 后端模块职责遵循 PROJECT.md；路由不反向导入主应用，共享依赖通过 Depends 提供，业务逻辑按复用需求提取，不为目录整齐增加转发层。
- API、下载 Worker、媒体 Runner、AI Worker 是独立进程。PostgreSQL 是状态事实来源；跨 PostgreSQL/RabbitMQ 使用 transactional outbox，消费者必须支持幂等和 lease/heartbeat。
- PostgreSQL 只通过 `backend/sql/schema.sql` 维护当前态结构。本机直接复用已运行的 PostgreSQL，按结构变更需要在已有项目数据库中幂等执行该 SQL；不得为启动或验证项目另起基础服务或覆盖现有数据。空库验证只能使用已有服务中的隔离测试数据库或远端 CI。项目不维护迁移目录、历史 schema 或旧版本兼容逻辑。结构变化时同步更新可重复执行的当前态 SQL、ORM 和测试，并同时使用空数据库与已有当前态数据库验证。
- OpenAPI 是前后端接口契约的唯一来源，通过 `/openapi.json` 提供，并由 `/docs` 展示 Swagger UI；不维护平行 DTO、手写生成类型或旧 API 适配层。
- 只实现当前需求，不添加旧目录、旧 API、旧 Provider 或旧数据库的兼容分支。文件按业务内聚性和事务边界拆分，不以固定行数机械拆分，不为缩短文件引入转发层或多重继承。

## 安全与运行约束

- 帧取为单人自用工具。需要登录态的站点只从部署者本机 Chrome 按次现读 Cookie（宿主机 `chrome_agent` → 无状态 `session-broker` → `session-runner` tmpfs），不落库、不另开浏览器保活、不定时重新导入。按用户最新批准，`NATIVE_PUBLIC_PROVIDERS` 中的平台固定使用原生公开接口，其余在线解析必须使用站点会话；Chrome 未登录时明确失败并提示登录，不得回退匿名／访客路线。未验证真实文件不得宣称某平台修复完成。

- 仅处理用户有权下载和分析的内容。公开内容路线只处理能够正向证明为公开、免费、非 DRM 的 HTTP(S) 内容；按用户确认的 032 个人范围，腾讯视频和优酷可在单平台持久会话线路中尝试处理账号可访问的完整非 DRM 单视频，必须保留原始完整时长并通过最终文件校验；不能把账号可见性标成官方导出授权。其他受限平台内容仍需官方授权 Provider/Connector 按资产明确返回下载或导出授权，且输出未加密时才可生成 Artifact。Edge Agent 只能传输用户已经合法取得并显式选择的 clear 文件与脱敏声明，不得访问平台会话、网络流量、缓存或保护材料，也不得生成客户端签名、取得内容密钥或转换受保护媒体。不得借技术路径扩张会员/购买、private、follow-only 或地域权益；私网 URL、任意 yt-dlp 参数和 shell 输入始终禁止。普通业务 JSON 禁止上传原始 Cookie；受控 Provider 会话只能按 005 的 allowlist、独立 Runner、只读 Secret、权益防火墙和验收门禁启用。
- 在线媒体入口复用单个 `session-runner`；固定公开平台不领取或携带账号材料，会话平台只能按任务领取绑定任务与站点的一次性封装租约，不持有常驻凭据，不得获得数据库、队列、对象存储或 AI 凭据。Runner 均须经过阻断私网的 egress proxy；入口 URL 校验不能替代网络隔离。
- Worker 开工前重新解析语义下载计划；Provider format id 不能作为唯一恢复依据。
- AI 任务独立于下载任务；AI 失败不得改变下载成功状态。模型输出必须通过严格 schema、连续分镜时间轴和 shot evidence 校验，普通日志不得记录完整 Prompt、抽帧或原始模型响应。
- 基础设施 Secret 只来自类型化配置和环境变量；管理员在 Web 中维护的 AI Provider Key 只允许进入记录绑定的加密数据库字段，并仅在 Analysis Worker 内存中解密。任何 Secret 都不得进入前端、API 响应、异常、快照、测试夹具或普通日志。外部操作必须设置大小、时长、并发和超时上限，取消时终止整个子进程组。
- 复用本机 OAuth 的 AI Worker 是 Compose 拓扑之外的宿主组件：必须由已登录 Codex 或 Claude CLI 的宿主机用户启动，容器不得挂载或复制 CLI 认证目录。
- Compose 只管理业务服务：`docker-compose.yml` 用于本机业务、Worker、Runner 和出口代理，`docker-compose-prod.yml` 用于生产业务。本机启动和验证直接复用当前 `.env` / `.env.prod` 与已运行的 PostgreSQL、RabbitMQ、Redis、MinIO，不另建基础环境、不覆盖已有环境文件。容器通过 `POSTGRES_HOST/PORT`、`RABBITMQ_HOST/PORT`、`REDIS_HOST/PORT`、`MINIO_HOST/PORT` 连接宿主机服务，默认主机为 `host.docker.internal`，端口和凭据以现有配置为准。`docker-compose-env.yml` 仅保留给没有宿主服务的 GitHub CI，不属于本机启动入口。MinIO 全部业务进程共用一组 `MINIO_ACCESS_KEY` 与 `MINIO_SECRET_KEY`；所有业务服务显式设置稳定的 `container_name`。只有配置文件不存在时才从示例创建。不要提交 `.env`、制品、缓存、日志、临时目录、虚拟环境或 `node_modules/`。

## 实现与验证

- 修改前先阅读相邻代码、对应 README 和测试，优先复用现有模型、端口、组件与工具函数。
- 删除失效文件、引用、依赖和文档，不保留“以后可能使用”的空目录、转发层或重复实现。
- 根据改动范围执行最小充分验证；修复缺陷时补充能稳定复现问题的测试。
- 发现重复规则、过度设计或不合理行为时，记录清晰的证据、影响、最小修复和回归验证；触及相关模块时按优先级处理。不得只为减少行数合并不同业务边界，也不得以代码整理为由扩大当前授权范围。修复必须附回归证据，未验收不关闭登记项。
- GitHub Actions 只执行确定性的后端与前端系统测试边界；完整 Compose 启停、真实 Provider、依赖公告扫描和发布演练按变更范围在本地或发布验收中执行。下列命令是各模块的本地检查入口。
- 后端命令从 `backend/` 执行：

```bash
uv sync --frozen --dev
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run pytest
```

- 前端命令从 `frontend/` 执行：

```bash
pnpm install --frozen-lockfile
pnpm format:check
pnpm lint
pnpm test
pnpm build
```

- 涉及接口契约时验证 OpenAPI 生成结果和前后端契约测试；涉及运行时、依赖或容器时验证业务 Compose 和生产 Compose 可以解析，按需验证镜像构建和已有服务的健康接口；CI 夹具只做静态解析，不在本机启动。
- 不得隐瞒失败的检查。无法在当前平台完成的验证应在交付说明中写明原因、已执行范围和剩余风险。

## 文档规范

- 根 `README.md` 说明仓库入口和运行方式；`backend/README.md`、`frontend/README.md` 说明模块用法；详细事实放在 `docs/`，不要在多个文件复制大段内容。
- 系统设计只维护在 `docs/design/`（按主题分文件，索引见 README.md），是本项目唯一保留的设计文档；不再维护 PRD、Plan、验收、调研与运维手册等过程文档，运行说明写入 README，过程记录通过 Git 历史追溯。BACKLOG 仅作任务导航和历史记录。
- 文档明确区分审查基线、目标要求、实现状态和验收事实；目标规格不得冒充当前实现。历史方案通过 Git 追溯，不保留已废弃内容作为“兼容说明”。

## Git 与任务交付

- 开始任务和提交前都执行 `git status --short`，识别并保留用户已有改动；不得覆盖、删除或顺带提交与当前任务无关的文件。
- 一个“小任务”应是可独立说明、可独立验证、可安全回滚的一组改动。完成并通过相关检查后立即提交，不把多个无关任务积累到同一提交。
- 提交信息建议使用 Conventional Commits，格式为 `<type>(<scope>): <中文描述>`；不需要作用域时使用 `<type>: <中文描述>`，禁止使用空作用域 `feat(): ...`。提交说明只服务于协作可读性，不作为 GitHub Actions 的 CI 阻断条件。
- `type` 使用小写英文：新功能 `feat`、缺陷修复 `fix`、重构 `refactor`、文档 `docs`、测试 `test`、性能 `perf`、构建 `build`、持续集成 `ci`、维护 `chore`、纯格式 `style`、回退 `revert`。
- `scope` 使用稳定且非空的小写英文模块名，例如 `api`、`frontend`、`backend`、`runner`、`worker`、`docs` 或 `deps`；无法准确归属时省略作用域，不得临时发明含糊缩写。
- 冒号后使用简洁、明确的中文动作描述，不加句号，例如 `feat(api): 增加下载任务取消接口`、`fix(frontend): 修复任务状态轮询泄漏`、`docs: 补充本地开发说明`。
- 破坏性变更在类型或作用域后添加 `!`，例如 `feat(api)!: 移除旧下载接口`，并在提交正文中使用 `BREAKING CHANGE: <中文说明>` 描述迁移影响。
- 提交前检查暂存区，只暂存当前任务文件；禁止提交 Secret、缓存、构建产物、日志、临时文件或无意义格式化改动。
- 提交完成后再次执行 `git status --short`，正常情况下工作区必须为空。若任务开始时已有用户未提交改动，应原样保留并在交付时明确说明，不能为了“干净”而擅自清理。
- 只有用户明确要求时才推送远端、创建分支或发起 PR。不得擅自改写已有提交、强制推送或使用破坏性 Git 操作。
- 最终交付说明使用中文，至少包含修改摘要、验证结果、提交哈希和工作区状态；存在未完成项或已知风险时必须明确列出。

## 下载持久化与 API 生命周期

下载流程不得建立重复的数据库 DTO、Store 或字段复制层。事务必须有明确的所有者，目录调整不得改变现有提交、回滚及 Outbox 原子性。API 工厂只定义应用；外部运行时资源在 FastAPI lifespan 启动时创建，启动失败和停止时释放。测试可在不连接外部服务的情况下导入入口并生成 OpenAPI。

API 使用 `runtime.py` 定义类型化的 `ApiServices`，在 `app.state.services` 中只挂载一次，通过 FastAPI 依赖函数读取；`lifespan.py` 管理资源所有权和释放，不逐项复制服务到动态 State。外部注入的运行时由调用方管理。

API readiness 检查业务核心依赖，不把单个平台 Runner 的健康作为全局可用条件。API、下载 Worker 和 Canary 的启动不得等待所有 Provider 健康；Worker/Canary 仍等待共享工作目录初始化。broker readiness 只表示中继资源已初始化；来源可读和平台接受会话分别由按需查询与真实任务验证，不通过空转扫描、预热或无人消费的上报实现就绪。下载 Worker 与 Runner 的容器停止宽限必须覆盖 Worker 有限排空预算。当前设计见 docs/design/08-平台会话.md 与 docs/design/13-可靠性与运行.md。

前端目录职责以 PROJECT.md“前端目录与文件规则”为准。接口类型直接使用生成的 API.*，不新增 services、utils、types 聚合目录或纯转发文件。
