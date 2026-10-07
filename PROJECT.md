# framefetch-server 工程规范

本文规定 `framefetch-server` 的技术栈、进程拓扑、目录职责、接口链路与命名规则。协作与交付见 [AGENTS.md](AGENTS.md)，运行方式见 [README.md](README.md)，界面视觉见 [design.md](design.md)。`framefetch-app` 与 `framefetch-electron` 是独立仓库，各自维护规范。

## 1. 技术栈

| 范围 | 标准 |
| --- | --- |
| 后端 | Python 3.12、FastAPI、Pydantic；uv 与 `uv.lock` 管理依赖 |
| 持久化 | PostgreSQL、SQLAlchemy 异步 Session；当前态结构只在 `backend/sql/schema.sql` |
| 编排 | Temporal：解析与 Skill 分析；RabbitMQ：下载、导入、报告发布与实时事件 |
| 媒体 | yt-dlp 与可信插件、bgutil PO Token、浏览器运行时、受控出口代理 |
| 前端 | Next.js App Router、React、TypeScript strict、Tailwind CSS、shadcn/ui（Radix）、Phosphor |
| 前端依赖 | pnpm；`packageManager` 固定版本，唯一 `pnpm-lock.yaml` |
| 接口契约 | FastAPI 注解生成 OpenAPI；`@umijs/openapi` 生成前端 `src/api` |
| 身份 | 用户普通 Chrome 中的 MV3 扩展 `Framefetch` 与宿主 cookie-source |
| 检查 | 后端 Ruff、mypy、pytest；前端 Biome、TypeScript、Vitest、Next.js build；扩展 `node --test` |

精确版本只在依赖清单与锁文件中维护。新依赖必须承担明确职责，脚手架默认带入但未使用的依赖应删除。

## 2. 进程拓扑

| 进程 | 运行位置 | 职责 |
| --- | --- | --- |
| `api` | Compose，8111 | HTTP 提交、查询、取消；不执行长任务 |
| `frontend` | Compose，8101 | Next.js standalone，运行时代理与上传流式代理 |
| `workspace` | Compose，8130 | 文档站点（Nextra standalone），只读挂载 `workspace/content/` |
| `worker` | Compose | 监督 Outbox、下载、导入、报告发布与 Temporal 解析 Worker |
| `session-runner` | Compose | 隔离的媒体执行进程，不持有数据库、队列、对象存储或 AI 凭据 |
| `egress-proxy` | Compose | 媒体流量的唯一出口 |
| `youtube-pot-provider` | Compose | YouTube PO Token |
| `migrate` | Compose | 幂等执行 `schema.sql` |
| AI Worker | 宿主 LaunchAgent | 使用宿主已登录的 Codex/Claude CLI 执行 Skill 分析 |
| cookie-source | 宿主 LaunchAgent，`127.0.0.1:19101` | 与身份扩展通信，为 Runner 提供单次操作的身份材料 |

- PostgreSQL 是业务状态的唯一事实来源。跨 PostgreSQL、Temporal、RabbitMQ 的写入使用 transactional outbox；dispatcher 按确定 Workflow ID 直接启动 Temporal，不经 RabbitMQ 中转。
- 同一业务只由一个引擎调度。分工细节见[工作流编排](workspace/content/design/13-工作流编排.md)，解析引擎见[解析引擎](workspace/content/design/14-解析引擎.md)。
- 新增后台循环并入 `worker` 作为独立监督组件；只有需要不同凭据或信任边界时才新增容器。
- 所有业务容器显式设置稳定的 `container_name`。

## 3. 仓库结构

```text
framefetch-server/
├── backend/                  FastAPI、Worker、Runner、当前态 SQL 与测试
├── frontend/                 Next.js Web
├── extension/                身份扩展源码；manifest.json 与 config.local.json 由安装命令生成，不入库
├── workspace/                文档工作区：Nextra 站点，content/ 为 prd/、design/、plan/
├── assets/                   README 配图
├── docker-compose.yml        本机业务容器
├── docker-compose-prod.yml   生产业务容器
├── docker-compose-env.yml    一次性基础设施夹具，不属于本机启动入口
└── .env.example              配置模板
```

### 3.1 文档工作区

- `workspace/content/` 是产品需求、系统设计与执行计划的唯一位置，也是 Obsidian 库根目录；`.obsidian/app.json` 固定使用相对路径的标准 Markdown 链接，保证 GitHub、Obsidian 与站点解析一致。
- 站点使用 Nextra（`workspace/`，pnpm 独立管理），以 Compose 服务 `workspace` 部署在 8130，本地编辑预览用 `pnpm dev`（8131）。
- 页面、侧栏与全文搜索在请求时读取只读挂载的 `content/`：正文用 Nextra 编译，导航读取目录与纯数据对象 `_meta.js`，搜索直接查询当前 Markdown。修改、原子替换、新增或删除文档后无需重建或重启容器；可见的阅读页每 2 秒检查内容修订并自动刷新，搜索同时更新。目录首页沿用 `README.md`，目录地址重定向到它；指向 `content/` 之外的仓库文件的链接改写为 GitHub 地址。
- 站点只读取 `content/`，不维护第二份文档；`_meta.js` 只决定导航顺序与标题。
- [workspace/AGENTS.md](workspace/AGENTS.md) 规定文档归档、命名、内容职责、索引与证据要求；编写或更新 workspace 文档时遵循该规范。
- 在 `workspace/` 执行 `pnpm check` 检查文档链接与锚点，执行 `pnpm typecheck`、`pnpm test` 与 `pnpm build` 验证运行时内容、导航、搜索与站点构建；本地与 CI 使用同一组命令。

## 4. 后端

### 4.1 目录

```text
backend/
├── Dockerfile
├── pyproject.toml / uv.lock
├── sql/schema.sql            当前态数据库结构
├── egress/                   出口代理配置
├── scripts/                  有实际调用方的运维脚本
├── tests/                    unit、integration、contract、architecture
└── app/
    ├── main.py               应用工厂与路由注册
    ├── api/                  路由、Depends、异常映射、中间件、OpenAPI 声明
    │   └── routes/           按业务组织的 APIRouter
    ├── core/                 配置、数据库、公开错误码、安全、运行资源装配与 lifespan
    ├── models/               SQLAlchemy 实体
    ├── schemas/              Pydantic HTTP 契约
    ├── repositories/<业务>/  数据访问与事务所有权
    ├── services/<业务>/      业务操作与内部类型；复杂业务可含 rules/，分析业务含 skills/
    ├── integrations/         存储、队列、邮件、AI 等外部系统适配
    └── workers/
        ├── main.py           worker 进程入口
        ├── outbox/ download/ imports/ report/ dlq/
        ├── analysis/         宿主 AI Worker
        ├── identity/         cookie-source 与扩展安装命令
        └── runner/           媒体执行进程；engine/ 阶梯内核，plugins/ 可信 yt-dlp 插件
```

### 4.2 职责

| 目录 | 放入 | 不放入 |
| --- | --- | --- |
| api | 路由、请求认证、HTTP 协议适配 | SQL、长任务实现 |
| core | 配置、运行资源装配与生命周期 | 单一业务的字段、展示转换与用例 |
| models | ORM 表、索引、约束 | 响应 DTO、业务流程 |
| schemas | 请求校验与响应字段 | 数据库访问、内部状态快照 |
| repositories | 数据操作、事务、原子状态变更 | HTTP 对象、平台下载、AI 调用 |
| services | 业务操作、内部类型、纯规则 | FastAPI、数据库与外部 SDK 的具体实现 |
| integrations | 外部系统调用与结果适配 | 重复的业务规则、通用转发接口 |
| workers | 消费、调度、进程入口、媒体执行 | Web 路由、重复的业务状态 |

### 4.3 规则

- `app/` 根目录只有 `main.py` 与 `__init__.py`。新增顶级包须说明无法归入既有职责的原因并同步本文。
- `__init__.py` 不重导出业务符号，调用方从定义模块直接导入；`models` 的导入注册用于构建完整 metadata，属于必要初始化。
- 不设平行 `domain/` 目录；不为每个接口机械创建 Service/Repository/DTO 全套文件；不建只为改名的包装或转发文件。
- 业务类型、HTTP schema、ORM 模型各守边界；只有形状与语义完全相同时才复用，不得为减少文件暴露数据库内部字段。
- 事务有明确所有者；目录调整不得改变提交、回滚、Outbox 原子性或权限校验。
- 路由不反向导入主应用。共享依赖通过 Depends 提供；运行资源由 `core/runtime.py` 定义为类型化的 `ApiServices`，在 `lifespan` 中创建并挂载到 `app.state.services`，停止时释放。导入应用和生成 OpenAPI 不连接外部服务。
- API readiness 只检查业务核心依赖，不把单个平台或 Runner 的健康作为全局就绪条件；平台可用性按任务验证。
- `worker` 与 `session-runner` 的停止宽限覆盖下载有限排空预算；外部操作都设置大小、时长、并发与超时上限，取消时终止整个进程组。
- 异步路径不执行阻塞 IO 或 CPU 密集工作。
- Python 文件与函数 `snake_case`，类 `PascalCase`。自有接口、模块与类按职责命名，不使用 `/vN`、`V2`、`_v2`；媒体内部接口统一为 `/internal/<职责>`。外部平台协议地址与依赖版本按实际保留。
- `__pycache__` 与空目录不入库。

### 4.4 数据库

- `backend/sql/schema.sql` 是唯一结构来源，可重复执行，描述当前态。
- 不维护迁移目录、历史 schema 或旧版本兼容逻辑。结构变化同步更新 SQL、ORM 与测试，并分别用空库和已有当前态库验证。
- 不新增 SQLite 业务库、Cookie 库、文件任务账本、第二调度器或通用 Agent 框架。

## 5. 接口契约

唯一链路：**路由装饰器 + Pydantic 模型 → `/openapi.json` → `@umijs/openapi` → `frontend/src/api/`**。`/docs` 提供 Swagger UI。

- 不手写 JSON/YAML 契约或平行接口文档。每个公开操作有唯一 `operation_id` 与业务 tag；字段、错误、分页、可空与二进制响应都在注解中声明。
- `frontend/src/api/` 只由生成器写入，禁止手改、复制 DTO 或建别名层。生成配置只在 `frontend/openapi2ts.config.ts`。
- CI 从后端源码导出 schema，重新生成并检查 Git 差异；不得用运行中的旧服务验证新代码。
- 文件流、Range、WebSocket、健康探针与指标按各自协议实现，不由 REST 生成器代替。
- 原生 App 使用 `/api/app/v1` 契约；修改须连同 `framefetch-app` 一起验收。

### 5.1 响应与异常

- Web 业务 JSON 统一为 `{ code, message, data }`：成功 `code` 为 `ok`；失败 `data` 为 `null`，并保留真实 HTTP 状态码。
- `core/error_codes.py` 定义公开 `ErrorCode`；`api/errors.py` 是业务异常到公开状态码与安全消息的唯一映射，路由不重复 try/except 转换。
- `register_exception_handlers` 在应用工厂中注册一次，覆盖业务错误、配额、HTTPException、请求与响应校验及未捕获异常；中间件的大小与超时限制复用同一响应函数。
- 保留 `Retry-After`、`Allow`、认证 Cookie 清理与安全响应头。未捕获错误只输出安全消息。
- Web 路由使用 `ApiResponseRoute`，`schemas/response.py` 的泛型模型参与序列化，使 Swagger 直接描述封装后的契约。
- 前端 `src/lib/request.ts` 统一解包 `data` 并把错误映射为 `ApiError`；页面不自行拆包。

## 6. 前端

```text
frontend/
├── components.json           shadcn CLI 配置
├── openapi2ts.config.ts      唯一接口生成配置
├── src/
│   ├── app/                  路由、布局、loading、error、元数据
│   ├── api/                  生成的请求函数与 API.* 类型
│   ├── components/
│   │   ├── ui/               官方 shadcn 组件源码
│   │   ├── layout/           站点框架与页面状态组件
│   │   └── <业务>/           业务组件及其专用 Hook
│   ├── hooks/                跨业务共享的 React Hook
│   └── lib/                  request.ts、upload/ 等跨业务非 React 代码
├── public/                   实际使用的静态资源
└── tests/                    unit、architecture、fixtures、helpers
```

- 业务组件与 Hook 直接调用生成 API，类型直接用 `API.*`；前端独有类型在所属业务附近定义。不设 `services/`、`utils/`、`types/` 聚合层，不建 barrel 或纯转发文件。
- `src/lib/request.ts` 是唯一 Axios 封装，负责 Cookie、认证恢复、超时、取消与错误归一化；`src/lib/upload/` 承担多步上传与导入编排。
- Web 身份只用 PostgreSQL 持久化的不透明 HttpOnly Cookie；不做 JWT 刷新，不自动重放业务请求，依赖故障不清空身份。登录跳转只允许同源路径。
- 优先 Server Component；只有交互、状态或浏览器能力需要时才用 Client Component。Server-only 代码不得经共享模块进入浏览器。
- 单页面状态留在组件内；需要复用时拆为就近的 Hook，跨业务且依赖 React 生命周期时才进入 `hooks/`。
- 普通文件 `kebab-case.ts(x)`，Hook 文件 `use-*.ts`、函数 `useXxx`；Next.js 特殊文件与生成 API 保持工具约定。
- 基础组件按需通过 shadcn CLI 安装，不预存未使用组件，不放假用户、模拟业务入口或演示资产。

### 6.1 页面状态

| 场景 | 组件 |
| --- | --- |
| 页面或列表无数据 | `components/layout/page-empty-notice.tsx`（内部为 shadcn `Empty`）；筛选无结果用 `compact` |
| 首次请求失败、无可用数据 | `PageErrorNotice`，居中并提供重试 |
| 已有数据刷新失败、需持续展示的可恢复错误 | `FeedbackNotice` |
| 普通操作结果 | Sonner `toast()` |

- 空状态说明下一步，存在明确恢复动作时提供按钮；不得把请求错误降级为空状态。
- 标题层级随页面结构（页面已有 `h1` 时用 `h2`）；图标用 Phosphor 并标记 `aria-hidden`；异步反馈使用 `aria-live` 或组件自带的 alert 语义。
- 表单校验、删除确认与加载占位各按自身语义实现，不套用页面空状态。

## 7. 清理规则

- 新建文件前明确其职责与实际调用方。禁止空目录、纯转发文件、重复类型、备用实现与无用途 barrel。
- 删除前核对源码、动态加载、框架入口、构建配置与测试：没有普通 import 不等于无用，被测试引用也不等于生产必需。
- 删除时同步清理 Dockerfile `COPY`、Compose 命令、依赖、测试夹具与文档入口。
- 目录调整一次覆盖全部引用、导入入口、测试与部署入口，不保留旧路径；不改变公开 URL、权限、数据库语义与消息格式。
