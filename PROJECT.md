# 项目工程规范

本文规定 `video-server` 的目标工程标准，自 2026-09-18 起生效。标准依据框架官方约定和本项目已明确的需求制定，禁止依据现有目录反推规范。新增与重构代码必须遵守；现有代码仅作为迁移和验收对象。Flutter App 为独立项目，单独维护规范。

本文负责技术、目录和依赖规则；AGENTS.md 负责协作与交付；README.md 负责运行方式；design.md 是界面视觉设计的唯一标准来源。发生架构冲突时，以本文和用户最新要求为准。

## 1. 技术标准

| 范围 | 规定 |
| --- | --- |
| 后端 | Python、FastAPI、Pydantic；使用 uv 和 uv.lock 管理依赖 |
| 持久化 | PostgreSQL、SQLAlchemy 异步 Session；数据模型与 HTTP 模型分离 |
| 前端 | 官方 create-next-app：Next.js App Router、React、TypeScript strict、Tailwind CSS |
| 组件 | 官方 shadcn CLI 与 Radix 组件；不自行实现平行基础组件库 |
| 前端依赖 | pnpm；packageManager 固定版本，唯一 pnpm-lock.yaml |
| 接口契约 | FastAPI 注解自动生成 OpenAPI，Swagger UI 展示同一份契约 |
| 接口调用 | @umijs/openapi 生成 src/api，统一使用 Axios src/lib/request.ts |
| 长任务 | 独立 Worker；HTTP 只提交、查询、取消。解析与 Skill 分析使用 Temporal，报告发布、下载与导入使用 RabbitMQ；分工见设计 15，不允许同一业务双引擎调度 |
| 检查 | 后端 Ruff、mypy、pytest；前端 Biome、TypeScript、Vitest、Next.js build |

具体版本通过依赖清单与锁文件固定；禁止在本文维护另一份版本快照。新依赖必须承担明确职责，不因脚手架默认包含就保留。

媒体获取重设计继续使用现有技术栈；通过轻量 Chrome 扩展与现有 Python Native Messaging 来源按任务复用日常 Chrome 会话，删除 Playwright 专用浏览器依赖，不引入 SQLite 或新的任务存储。PostgreSQL 是业务事实来源，Temporal／RabbitMQ 各自拥有既定任务；执行进程不复制业务状态机。媒体执行保留容器隔离；宿主不建立第二份任务状态。

## 2. FastAPI 工程结构

### 2.1 官方基线与项目边界

以 FastAPI 官方多文件应用和 Full Stack Template 的 APIRouter、Depends、应用入口为基线，并参考 fastapi-best-practices 的业务聚合原则。官方模板的单文件 `crud.py` 是小型示例，不是本项目所有持久化文件的统一容器，也不存在 FastAPI 强制要求的 Java 式分层。

本项目采用 api/core/models/schemas/services/repositories/integrations/workers 的职责边界，较大的业务在职责内部聚合；不创建无用途的空目录或统一基类。该目录是本项目的选择，不宣称是 FastAPI 唯一官方架构。

本项目保留 SQLAlchemy 和独立 Pydantic 契约，因此将 models 与 schemas 分开；媒体、AI 和异步任务分别使用 services、integrations、workers。以下是完整目录规范，所有后端源码必须能归入明确职责，禁止在 app 根目录继续堆积辅助文件。

### 2.2 完整目录规范

```text
backend/
├── Dockerfile / .dockerignore      后端独立构建边界
├── pyproject.toml / uv.lock
├── app/
│   ├── __init__.py
│   ├── main.py                     FastAPI 应用工厂、路由注册、启动入口
│   ├── api/
│   │   ├── deps.py                 共享 Depends、认证与请求依赖
│   │   ├── routes/                 按业务组织的 APIRouter
│   │   ├── errors.py               全局异常注册、安全错误映射
│   │   ├── responses.py            类型化成功响应 APIRoute
│   │   ├── middleware.py           请求限制和安全响应头
│   │   ├── openapi.py              OpenAPI 元信息与响应声明
│   │   ├── admission.py            HTTP 限流准入
│   │   └── upload_signing.py       浏览器上传与下载的 HTTP 地址适配
│   ├── core/
│   │   ├── config.py               Settings、限流与配额配置
│   │   ├── db.py                   Engine、Session、ORM Base
│   │   ├── errors.py               AppError 公共异常
│   │   ├── error_codes.py          公开结果码枚举
│   │   ├── security/               密文与密钥处理
│   │   ├── composition.py          具体运行资源与业务对象装配
│   │   ├── runtime.py              类型化运行资源集合、启动与关闭
│   │   └── lifespan.py             FastAPI lifespan 资源所有权
│   ├── models/                     SQLAlchemy 持久化实体
│   ├── schemas/                    Pydantic HTTP 输入与输出契约
│   ├── repositories/               数据访问和明确的事务所有权
│   │   ├── analysis/               分析任务、报告、执行租约
│   │   ├── auth/                   用户、会话与注册验证
│   │   ├── documents/              剧本导入和目录
│   │   ├── downloads/              下载任务、历史、进度和恢复
│   │   ├── imports/                媒体导入
│   │   ├── providers/              平台目录、探针与冷却状态
│   │   ├── source_discoveries/     来源发现
│   │   └── storage_files/          文件目录与清理
│   ├── services/                   按业务组织操作与业务类型
│   │   └── <业务>/
│   │       ├── rules/              该业务的纯规则，仅复杂业务需要
│   │       └── skills/             分析业务的技能定义与 Markdown 资源
│   ├── integrations/               存储、队列、邮件、AI 等外部系统适配
│   └── workers/
│       ├── analysis/               宿主分析 Worker 与 Agent 管理入口
│       ├── main.py                 worker 进程入口，监督以下组件
│       ├── download/               解析与下载组件
│       ├── imports/                导入组件
│       ├── outbox/                 Outbox 投递组件
│       ├── report/                 报告发布组件
│       ├── canary/                 平台探针组件
│       ├── dlq/                    死信管理
│       ├── session/                Chrome Native Messaging 来源、密封租约与无状态中继
│       └── runner/                 独立隔离的媒体执行进程与可信插件
├── sql/schema.sql                 当前态数据库结构
├── egress/                        Runner 出口代理配置
└── tests/                         单元、集成、契约与架构测试
```

`workers/runner/` 内部按实际边界就近组织，不保留空文件或兼容转发层：

- `provider_catalog_*.py` 声明各平台的 Profile（访问策略、URL、能力、账号要求、引擎参数）；`provider_registry.py` 统一识别与启动校验；`provider_factories.py` 仅复用确有重复的声明默认值。
- 平台差异采用函数策略与可信提取器适配，通用顺序复用现有 inspection/download Pipeline；不按每个平台复制 Workflow、HTTP 路由、Repository 或生成器框架。会话纯规则位于 `services/site_sessions.py`，Registry 查询与站点映射位于 `integrations/site_session_catalog.py`，不再维护第二份站点声明。
- `site_sessions.py` 负责向 broker 按需查询并解封单次租约；`provider_sessions.py` 管理操作期间的凭据使用与执行租约，不回写 Cookie 或发送失败上报。
- `provider_session_files.py` 与 `_secure_file.py` 管理私有临时文件，`provider_session_headers.py` 校验受控请求头；`netscape_cookie.py` 统一解析与序列化 Cookie。
- 宿主机来源和 RPC 契约位于 `workers/session/`；broker 不保存会话副本，不运行扫描或保活状态机。

所有 Python 包有 `__init__.py`；该文件默认不重导出业务符号。调用方直接从定义模块导入，避免用数百行导出清单再建一层公共接口。models 的导入注册用于建立完整 SQLAlchemy metadata，属于必要的初始化行为。

### 2.3 职责与依赖规则

| 目录 | 应当放入 | 不应放入 |
| --- | --- | --- |
| api | 路由、请求认证、HTTP 协议适配 | SQL、后台长任务实现 |
| core | 配置、运行资源装配与生命周期 | 单一业务的字段、展示转换和用例 |
| models | ORM 表、索引、约束 | 公开响应 DTO、业务流程 |
| schemas | 对外请求校验和响应字段 | 数据库访问、内部状态快照 |
| repositories | 数据操作、事务、原子状态变更 | HTTP 对象、平台下载和 AI 调用 |
| services | 业务操作、内部类型、纯规则 | FastAPI、数据库和外部 SDK 的具体实现 |
| integrations | 对外部系统的实际调用和结果适配 | 重复业务规则、通用转发接口 |
| workers | 消费、调度、进程入口、媒体执行 | Web 路由和重复的业务状态事实 |

- 根目录只保留 main.py 与包标记；新增顶级包必须先明确无法归入既有职责的原因，并同步本规范。
- 一个业务的规则与内部类型就近维护，不再设置平行 domain 目录；rules 和 skills 按实际需求创建，不为每个业务预建。
- 简单业务使用函数或内聚模块；复杂操作确需共享状态时使用类。禁止为每个接口固定创建 Service/Repository/DTO 全套文件，禁止只为改名创建包装或转发文件。
- 单一部署配置统一在 core/config.py，HTTP 异常统一在 api/errors.py；不得拆出只有一个配置类或一段相同响应包装的平行入口。
- 业务类型、HTTP schema、ORM 模型各自承担不同边界；只有字段形状和语义完全相同时才复用，不能为减少文件数暴露数据库内部字段。
- 事务须有明确所有者；文件归类不能改变事务提交、回滚、Outbox 原子性或权限校验。Runner 归入 workers 后仍是独立隔离进程。
- 路由不反向导入主应用；共享依赖通过 Depends 注入；运行资源通过 lifespan 创建和关闭。导入应用、生成 OpenAPI 不启动外部服务。
- Python 文件和函数采用 snake_case，类采用 PascalCase。异步路径不执行阻塞 IO 或 CPU 密集工作；使用线程边界或独立 Worker。
- 自有接口、类与模块按职责直接命名，不新增 `/vN`、`V2`、`_v2` 命名或平行实现；媒体内部路径为 `/internal/inspect`、`/internal/download` 等。迭代时直接修改唯一实现并同步所有调用方，依赖锁定与真实运行版本仍按发布要求维护。
- `__pycache__` 是 Python 运行缓存，不是源码目录；不得写入 Git。清理可移除缓存，不通过新增脚本控制缓存。

## 3. Swagger 与生成 API（必须遵守）

唯一维护链路：**路由装饰器 + Pydantic 模型 → FastAPI /openapi.json → @umijs/openapi → frontend/src/api/**。

- `/docs` 展示 Swagger UI；不手写 JSON/YAML 契约，不手动维护平行接口文档。
- 每个公开操作有稳定且唯一的 operation_id 和业务 tag。字段、错误、分页、可空与二进制响应均在后端注解中声明。
- 接口类型和请求函数全部自动生成；不得编辑 src/api，禁止复制 DTO 或创建别名聚合层。
- openapi2ts.config.ts 是唯一生成配置；执行 pnpm openapi，不另写生成包装脚本。
- 生成请求统一导入 src/lib/request.ts 的 Axios 封装；认证恢复、超时、取消和错误归一化由请求基础设施处理。
- CI 从后端源码自动导出临时 schema，重新生成并检查 Git 差异。禁止只用旧服务的 Swagger 验证新代码。
- 后端业务实现、外部对象存储传输和 WebSocket 协议不由 REST 客户端生成器代替。

### 3.1 全局响应与异常

- Web 业务 JSON 统一为 `{ code, message, data }`；成功 code 为 `ok`，data 保持业务模型、列表或 null；错误 data 为 null。保留真实 HTTP 状态码，不将失败转换为 200。
- `core/error_codes.py` 定义公开 ErrorCode 枚举；业务内部异常保持业务语义，由 `api/errors.py` 唯一映射为公开状态码和安全消息。路由不重复 try/except 转换业务异常。
- `register_exception_handlers` 在应用工厂一次注册，覆盖业务错误、配额、Starlette HTTPException（含 404/405）、请求校验、响应校验和未捕获异常。中间件的大小限制和超时复用同一响应函数。
- 保留 Retry-After、Allow、认证 Cookie 清理和安全响应头。未捕获错误仅输出安全消息，普通日志不记录输入、凭据或上游错误文本。
- Web 路由使用 `ApiResponseRoute`；`schemas/response.py` 的泛型模型参与 FastAPI 序列化和字段校验，Swagger 直接生成封装后的契约。不得仅通过中间件修改 JSON 而保留过时的 OpenAPI。
- Axios `request.ts` 统一解包业务 data，并把错误映射为 ApiError；页面继续使用业务返回类型，不自行拆包或定义平行响应类型。
- 204、文件流、Range、WebSocket、健康探针与指标遵循各自协议。独立 App 的 `/api/app/v1` 保持已发布契约；修改需连同 video-app 单独验收。

## 4. 前端目录与文件规则

依据 Next.js 官方文件约定组织路由，采用业务就近放置的源码组织方式。

```text
frontend/
├── package.json / pnpm-lock.yaml
├── components.json             shadcn CLI 配置
├── openapi2ts.config.ts         唯一接口生成配置
├── src/
│   ├── app/                    page、layout、loading、error、元数据等框架入口
│   ├── api/                    自动生成的请求函数与类型
│   ├── components/
│   │   ├── ui/                 官方 shadcn 基础组件
│   │   └── <业务>/             业务组件、专用 Hooks 和界面逻辑
│   ├── hooks/                  跨业务共享的 React Hooks
│   └── lib/                    Axios、浏览器能力及真正共享的非 React 代码
├── public/                     产品实际使用的静态资源
└── tests/                      测试、fixtures 和 helpers
```

- 单页面状态优先在组件内维护；需要独立职责或复用时再拆 Hook，业务专用 Hook 就近放置。
- 跨业务且使用 React 生命周期的能力进入 hooks；纯函数不能因名称含 use 就成为 Hook。
- lib 按职责组织，可为复杂共享能力建立子目录；不能把单业务文案、接口别名或 UI 塞入 lib。
- 不设置平行 services/utils/types 聚合层，不以改变目录名字代替删除无用途抽象。
- 普通文件 `kebab-case.ts/tsx`，Hook 文件 `use-*.ts`、函数 `useXxx`；Next.js 特殊文件和生成 API 保持工具约定。
- 接口直接使用 `API.*`；前端独有类型在所属业务附近定义。禁止为类型改名建立文件。
- UI 优先 Server Component，交互需要时再使用 Client Component；Server-only 能力不能经共享模块导入浏览器。
- 基础组件使用官方源码与 API；按需安装，不预存未使用组件，不维护假用户、模拟业务入口或演示资产。

### 4.1 页面状态展示

- 页面级或列表级的无数据状态统一使用 `frontend/src/components/layout/page-empty-notice.tsx`；该组件内部使用 Radix/shadcn `Empty`，禁止在业务页面重新实现一套左对齐的空提示结构。
- 标准结构为居中 `Empty`、`EmptyMedia variant="icon"`、语义化 `EmptyTitle`（页面已有 `h1` 时使用 `h2`）、`EmptyDescription`，以及可选的 `EmptyContent` 主操作。图标必须使用 Phosphor，并标记 `aria-hidden`。
- 首次为空、页面级无数据使用常规高度；筛选无匹配或局部面板无结果使用 `compact`。说明文案必须告诉用户下一步；存在明确恢复动作时在空状态中提供按钮，同时保留页面头部的稳定入口。
- 首次请求失败且没有可用数据使用 `PageErrorNotice` 居中展示并提供重试；已有数据刷新失败使用 `FeedbackNotice` 或 Sonner message，不得把请求错误降级成普通空状态。表单字段校验、删除确认和加载骨架属于各自语义，不套用页面空状态。
- 页面状态必须有稳定的可访问名称、可见焦点和键盘操作；异步反馈使用 `aria-live` 或组件自带的 alert/message 语义。特殊 404 可以保留专属排版，但仍须基于 `Empty` 的居中结构。

## 5. 清理与变更规则

- 创建文件前必须说明独立职责和实际调用方。禁止空目录、纯转发文件、重复类型、备用实现和无用途 barrel。
- 删除前核对源码、动态加载、框架入口、构建配置和测试；无普通 import 不等于无用，测试引用也不等于生产必需。
- 删除时同步清理 COPY、命令、依赖、测试夹具与当前文档入口；不通过删除业务回归测试掩盖功能损坏。
- 前后端分别管理依赖，禁止把独立 App 的规范写入本项目。Secret、本机配置、Cookie、制品、缓存和日志不进入 Git。
- 不因目录迁移改变公开 URL、权限、数据库语义和消息格式。一次迁移必须覆盖引用、导入入口、测试与部署入口，不保留旧路径兼容层。

## 6. 验收与迁移状态

新规范不能用文档提交代替代码验收：

- 后端：Ruff、mypy、pytest；覆盖路由注册、依赖注入、事务成功/回滚、响应字段过滤和 OpenAPI。
- 前端：format、lint、TypeScript、Vitest、production build；接口变化必须重生成。
- 镜像或运行入口变化必须验证构建；界面行为变化补浏览器验证；平台下载需真实任务验证。
- 推送 main 前核对暂存内容和远端状态；推送后检查同一提交的 CI，并报告失败或尚未完成的检查。

后端源码按第 2 节完整结构组织。目录调整必须同步所有导入、资源路径、测试、Compose 进程入口和文档；验收包括 OpenAPI 不变、配置定位、技能资源、HTTP/WebSocket、Worker 导入与镜像构建。

## 7. 官方依据

- [FastAPI 官方完整模板](https://github.com/fastapi/full-stack-fastapi-template/tree/master/backend/app)
- [FastAPI 多文件应用与 APIRouter](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [FastAPI 依赖注入](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [FastAPI 请求/响应模型](https://fastapi.tiangolo.com/tutorial/response-model/)
- [FastAPI 数据库会话示例](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [Next.js 工程结构](https://nextjs.org/docs/app/getting-started/project-structure)
- [shadcn Next.js 安装](https://ui.shadcn.com/docs/installation/next)

官方基线与项目扩展分别标明；目录规范不以现有实现为依据。

架构参考：[官方模板](https://github.com/fastapi/full-stack-fastapi-template/tree/master/backend/app)、[多业务组织参考](https://github.com/zhanymkanov/fastapi-best-practices)、[官方异常处理](https://github.com/fastapi/fastapi/blob/master/docs/en/docs/tutorial/handling-errors.md)。

容器构建：backend 与 frontend 各自维护 Dockerfile/.dockerignore，以各自目录为上下文；根 Compose 管理组合部署。后端镜像 video-server 用于 API/Worker/Runner，前端镜像 video-frontend 仅运行 Next.js；不再维护根 Dockerfile。
