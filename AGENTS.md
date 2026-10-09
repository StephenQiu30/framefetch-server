# framefetch-server 协作规范

本文件约束在本仓库工作的代码代理与贡献者：怎么读、怎么改、怎么验证、怎么交付。技术栈、目录与接口链路见 [PROJECT.md](PROJECT.md)，界面视觉见 [design.md](design.md)，安全边界见 [SECURITY.md](SECURITY.md)，提交格式见 [CONTRIBUTING.md](CONTRIBUTING.md)。规则冲突时以用户最新要求为准，其次是本文件。

## 产品定位

帧取（Framefetch）是单人自托管的视频解析、下载与分析工具。所有设计按个人工具取舍：不建设账号池、准入审批、运营金丝雀、多租户隔离或商业化能力。

## 不可违反的边界

- 公开线路（content_scope=public）只处理能够正向证明为公开、免费、非 DRM 的 HTTP(S) 内容；带着 Cookie 也不扩张到 private、follow-only、会员/购买或地域受限内容。
- personal_full 只适用于腾讯视频、优酷：处理账号可访问的完整非 DRM 单视频，必须保留原始完整时长，并通过最终文件校验。
- official_share 只适用于视频号：交付用户提交分享链接对应的微信官方非加密文件，候选时长只用于传输完整性校验，不宣称独立原长或原作品完整性已获证明。
- identity 与 content_scope 是两个独立维度，读取账号材料不等于放宽内容范围。
- 不解密媒体、不取得内容密钥、不转换保护流、不调用第三方公共解析站；无法证明为 clear 完整媒体时返回 `content_protected` 并引导文件导入。
- 平台身份只来自用户普通 Chrome 中的 `Framefetch` 扩展；不读取 Chrome Profile 文件、不访问钥匙串、不解密 Cookie。Cookie 不进入业务 JSON、日志、队列、Temporal History 或持久字段。
- 用户输入不得携带私网 URL、任意 yt-dlp 参数或 shell 片段。
- ExecutionContext 只保存解析引擎第 9 节的十二字段非敏感摘要；失败按第 8 节的十三类记录 layer、stage、gate、结构化 evidence 与摘要。
- 任何 Secret 不得进入前端、API 响应、异常、快照、测试夹具或普通日志；普通日志不记录完整 Prompt、抽帧或原始模型响应。

以上规则的完整定义与平台验收状态只在 [解析引擎](docs/design/14-解析引擎.md)与[平台身份](docs/design/15-平台身份.md)维护，本文不复述协议细节。

## 本机环境

- 基础服务（PostgreSQL、RabbitMQ、Redis、MinIO、Temporal）复用本机已运行的实例，不另起、不重建、不覆盖数据。
- `docker-compose.yml` 是唯一业务入口，本机与生产共用；通过 `*_HOST`/`*_PORT` 连接已有基础服务。`docker-compose-env.yml` 独立提供 PostgreSQL、RabbitMQ、Redis、MinIO，仅在没有现成服务的环境显式启动；Temporal 单独提供。
- 不覆盖已有 `.env`、`.env.prod`；只有配置文件不存在时才从 `.env.example` 创建。
- 宿主 AI Worker 由已登录 Codex 或 Claude CLI 的宿主用户运行，容器不得挂载或复制 CLI 认证目录。
- 数据库结构变化时，把 `backend/sql/schema.sql` 幂等执行到现有项目库；空库验证只用已有服务中的隔离测试库或 CI。

## 修改原则

- 动手前从[系统设计索引](docs/design/README.md)找到对应规范，并阅读相关 PRD 与执行计划，实现必须与文档设计一致；文档与代码冲突时先指出，由用户决定改文档还是改代码，不自行另立规则。
- 先读相邻代码、对应 README 和测试，优先复用已有模型、组件与函数。
- 只实现当前需求。不写兼容分支、别名路径、`V2`/`_v2`/`/vN` 命名、备用实现或“以后可能用”的空目录；迭代直接修改唯一实现并同步全部调用方。
- 删除时同步清理引用、依赖、Compose/Docker 入口、测试夹具与文档；不得用删除回归测试掩盖功能损坏。
- 生成的 API 客户端、扩展 manifest 与配对配置只通过生成命令更新；锁文件只由包管理器更新，上游 Skill 保持原样，适配写在目录之外。
- 文件按业务内聚与事务边界拆分，不按行数机械拆分，不为缩短文件引入转发层。
- 发现重复规则或过度设计时，记录证据、影响与最小修复；触及相关模块时处理，不以整理为由扩大授权范围。

## 验证

按改动范围执行最小充分验证，修复缺陷时补能稳定复现问题的测试。命令清单见 [CONTRIBUTING.md](CONTRIBUTING.md#本地检查)。文档变化时，在仓库根目录执行 `node backend/scripts/check_docs.mjs`。

- 接口变化：重新生成前端 API 并检查差异。
- 运行时、依赖或容器变化：验证业务与基础设施两份 Compose 可解析，并检查业务 Compose 的开发与生产配置，按需验证镜像构建与健康接口。
- 界面变化：真实浏览器检查桌面与 390px、明暗主题、键盘焦点。
- 平台下载：以正式 API 的真实完整文件为准；元数据成功、健康探针或 Registry 声明都不证明平台可用。
- 无法完成的验证写明原因、已执行范围和剩余风险，不得隐瞒失败。

## 文档

- 根 `README.md` 写运行方式；`backend/README.md`、`frontend/README.md` 写模块用法。
- 文档统一维护在 `docs/`（Obsidian 库，使用 Markdown 与 Git 管理），编写与沉淀规范见 [docs/AGENTS.md](docs/AGENTS.md)，目录与使用方式见 [PROJECT.md 第 3.1 节](PROJECT.md#31-文档工作区)。
- `docs/prd/` 定义产品范围与产品验收，`docs/design/` 定义技术架构与约束，`docs/plan/` 维护工作包与执行证据；各目录 README 是索引。同一规格只在一处维护，其他位置用链接引用。
- `BACKLOG.md` 只列未完成事项的链接。
- 文档只写当前有效规格，并区分“规格”与“已验证事实”。不写变更日期、“取代此前”、“迁移中”等过程叙述；历史通过 Git 追溯。

## Git 与交付

- 每次授权推送后，按提交 SHA 等待所有必跑 CI 检查的终态；全部成功才报告交付通过。失败时读取日志、修复并重新验证，不以旧提交、进行中、取消或跳过的结果代替通过。当前提交验证完成后再推进该仓库的下一次提交。

- 开始前和提交后都执行 `git status --short`，保留用户已有改动，不覆盖、不删除、不顺带提交无关文件。
- 一个提交对应一个可独立说明、验证和回滚的小任务，通过相关检查后再提交。
- 只暂存当前任务文件；不提交 Secret、`.env`、制品、缓存、日志、虚拟环境或 `node_modules/`。
- 只有用户明确要求时才推送、建分支或发起 PR；不改写已有提交，不强制推送。
- 交付说明用中文，包含修改摘要、验证结果、提交哈希、工作区状态，以及未完成项和已知风险。
