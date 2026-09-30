# BACKLOG — 当前任务导航与历史记录

## 当前任务：全平台通用解析（2026-09-30）

目标架构、实施依赖、P01–P09 checklist、当前状态与跨平台验收统一维护在 [docs/design/17-通用解析架构与实施计划.md](docs/design/17-通用解析架构与实施计划.md)。本文件不维护第二份执行状态；领域状态入口见 [设计 14](docs/design/14-状态与待办.md)。

以下保留旧任务历史，不作为当前架构或排期依据。旧 PRD/Plan 编号、ToC 目标与 24 平台记录均按其历史日期理解；当前规范以 PROJECT、AGENTS 与 docs/design 为准。

## 历史：容器自持平台会话（046）

PRD · Design · Plan · 运行手册。取代 044 FR-17／AC-21 与 043；任务状态只在 046 Plan 维护。

## 历史：统一解析中心（045）

PRD · Design · Plan。任务执行顺序与验收状态只在 045 Plan 维护；当前为方案设计，未实现。

## 历史执行基线（2026-09-22）

- 044 已拆分为 PRD、Design 和 Plan。PRD 唯一维护 FR／NFR／AC；Plan 唯一维护 P9 的步骤、依赖、状态与证据；本台账保留导航与历史记录。
- 核心目标是全新开源部署后的公开解析自动准备，不以已有 Cookie、宿主桌面授权或跨机器复制为前提。043 的来源持久分发仅为已有来源的辅助能力。
- P1–P7 保留原有工作记录，本轮不重新认证其全部完成证据；P6／P8 未完成项统一映射到 P9，不再并行实施另一套意图、授权或重试流程。文中旧排期及“24 平台”是原台账范围，当前覆盖以 PRD、执行顺序以 Plan 为准。
- 基线纠正：043 已将启动配置意图与来源瞬时健康分开，不能继续按旧 P8.2a.1 的“来源暂不可用就删除路由”实施；分布式租约只解决执行互斥，不等于消除宿主或状态存储单点。
- 本轮交付是需求／设计／执行台账。Plan 中 P9 全部保持未勾选；验收数值是目标，不是已证明容量。依赖满足后按任务推进，未经关联 FR、NFR、AC 验收不得关闭。

- 来源评审：`docs/design/README.md`；新增 040 ToC 无感下载与授权续接设计。
- 状态：P1–P5 保留原有完成记录；P6 尚未端到端验收；P7 为 2026-09-21 工作区审查发现的新增回归，P8 为待实现的产品能力。实施前复核代码行号。
- 维护约定：需求（PRD）与执行计划（Plan）逐项追溯到对应设计和证据。代码原型、单测通过、平台授权、真实文件交付分别验收，不以文档或 Cookie 可读标记下载完成。合并完成后按 AGENTS.md 清理纯过程内容。

---

## 一、PRD（需求）

> 每条需求：背景指向来源设计，验收标准为可判定条件。P7 的缺陷优先级按 review-agent：P1=需优先修复，P2=一般缺陷；不把环境相关问题无条件标为 P0。

### 可维护性（先做，投入最小）

- **R1 共享安全文件模块**

  - 背景：`_no_follow` 3 份、原子写 3 份、私有目录 fstat 校验多处重复（038 §3）。
  - 需求：新增 `_secure_file` 模块，收敛 `O_NOFOLLOW` 打开、`os.replace`+fsync 原子写、私有目录 fstat（uid/nlink/mode）校验；删除重复实现。
  - 验收：`grep` 确认 `def _no_follow`、`def _atomic_write_*` 各只剩一处定义；runner 既有测试全绿。
  - 优先级：P1

- **R2 Netscape Cookie 唯一实现**

  - 背景：解析/序列化/校验拆分在 3 个文件且规则漂移（038 §3）。
  - 需求：新增 `netscape_cookie` 模块，唯一实现解析、序列化、校验、过期过滤、`\x00` 检查、域名 allowlist 匹配。
  - 验收：cookie 读写校验只经该模块；allowlist 匹配逻辑一处；相关单测通过。
  - 优先级：P1

- **R3 凭证哈希一致性**
  - 背景：`provider_session_maintainer.py:89,273` 写未加盐 sha256，与 `provider_sessions.py:158` 的 HMAC 不一致（038 §3）。
  - 需求：统一为 HMAC（带密钥）派生凭证标识，消除未加盐哈希。
  - 验收：`state.json` 不再含未加盐 sha256；跨进程标识仍稳定可对账。
  - 优先级：P1

### 错误语义与重试/冷却（正确性）

- **R4 错误状态码分层**

  - 背景：`verification.py` 全部 502 与 `gallery.py:86` 422 冲突（038 §2-4）。
  - 需求：「产物非法/内容拒绝」统一 4xx，「基础设施/上游临时故障」保留 5xx；时长超限归为内容拒绝。
  - 验收：同一错误码不再同时承载 4xx/5xx 语义；前端错误提示可区分「链接不可用」与「服务繁忙」。
  - 优先级：P1

- **R5 失败分类全阶段覆盖**

  - 背景：`classify_provider_failure` 仅 `failure_context is not None` 时生效（038 §4）。
  - 需求：probe/remux/public_asset 阶段也携带 `failure_context`，使 provider 限流/封禁在全部子进程调用中被正确分类。
  - 验收：构造任一 probe 失败，产物落库稳定错误码而非通用 502。
  - 优先级：P1

- **R6 跨层冷却预算 + 退避/滞回 + 原因落库**

  - 背景：冷却固定 `DEFAULT_COOLDOWN`、`reason_code` 硬编码、`finish()` 不写 reason（038 §2-6）。
  - 需求：以 `(provider, egress_affinity, error_class)` 为 key 的单一冷却状态；遵守 `Retry-After`；指数退避 + jitter + 连续 N 次成功才清零的滞回；`block()/finish()` 落库 `reason_code` 与稳定错误码。
  - 验收：冷却可追溯原因；恢复需连续成功；不再「冷却 → 探测 → 解禁 → 再失败」抖动。
  - 优先级：P1

- **R7 删除 canary 错误码有损折叠**

  - 背景：`_RUNNER_ERROR_ALIASES` + `.get(code, "runner_failed")` 压平根因（038 §2-5）。
  - 需求：保留 `provider_errors.py` 细粒度稳定错误码；`canary_internal_error` 仅表示探测代码自身 bug，不落为平台失败证据。
  - 验收：canary 证据可区分验证码/POT 挂/凭证过期三类根因。
  - 优先级：P2

- **R8 下载队列重试可观测 + DLX 确认**
  - 背景：消费者恰好重试一次、`declare_queue(passive=True)`，DLX 绑定在外部拓扑（038 §2-1）。
  - 需求：确认 `download` 队列绑定 DLX 且 `dlq` 重放与 sweeper 三层恢复不重复计数；重试预算集中为可观测状态。
  - 验收：二次失败消息进入 DLQ 而非静默丢失；重放不重复执行幂等任务。
  - 优先级：P1

### 高可用（HA 提升）

- **R9 分布式凭证租约协调器**

  - 背景：operator 会话当前单副本 + 并发 1，是 SPOF（038 §5-1）。
  - 需求：Redis `SET NX + TTL + 心跳续租` 实现跨副本凭证租约；同一 `{provider}:{credential_version}` 同一时刻仅一个持有者；到期自动释放。
  - 验收：两副本并发请求同一凭证仅一个获租约；持有者崩溃后租约到期被接管。
  - 优先级：P0（消除 SPOF）/ P2（若短期接受单点则先文档化 + 告警）

- **R10 孤儿 workspace 文件系统 GC**

  - 背景：sweeper 只做 DB 三层恢复，无文件系统扫描（038 §2-2）。
  - 需求：年龄基回收 `{task_id}-*` 目录（超阈值且无活跃任务），info_json 复用有明确生命周期。
  - 验收：硬崩溃遗留目录在阈值后被回收；活跃任务目录不被误删。
  - 优先级：P2

- **R11 会话就绪与失效检测补全**

  - 背景：`is_ready()` 只查第一个 provider、`assert` 抛 500（038 §2-3）。
  - 需求：按 provider 校验；operator 未配 cookie 源返回受控 4xx；区分 `credential_expired` 与 `provider_link_unavailable`。
  - 验收：多 provider 场景会话失效可被 ready 感知；异常路径不再 500。
  - 优先级：P2

- **R12 状态证据对称（负向信号）**

  - 背景：证据只投影 `succeeded`，平台回归不立即可见（038 §2-7）。
  - 需求：纳入近期失败证据（带稳定错误码 + `context_generation_id` 过滤），不让个别链接失效误判为平台故障。
  - 验收：平台回归秒级反映到状态；单链接失效不污染平台状态。
  - 优先级：P2

- **R13 权益漂移自动停用**
  - 背景：缺「漂移即停用 credential version」安全网（038 §5-3）。
  - 需求：inspect attestation 检测账号权益与基线不一致即 disable 对应 `credential_version`。
  - 验收：账号意外获得会员/权限后，对应版本被停用而非 fail-open。
  - 优先级：P1

### 无额外机器的可移植部署

- **R14 clean-room 无会话启动与能力发现**

  - 背景：031 已明确 Cookie 文件和 operator profile 不能作为全新隔离部署的启动前置条件，全部验收在当前宿主的 clean-room 环境完成。
  - 需求：标准 Compose 在无 `.provider-sessions` 时启动核心服务；Canary 异步执行静态、metadata、media 分层探针，并投影 `public_probe`、`public_ready`、`authorization_required`、`degraded`、`blocked`、`unsupported` 等可行动状态。
  - 验收：全新工作目录无需创建空 Cookie 文件即可进入首页；平台状态不以容器健康冒充真实可用。
  - 优先级：P0

- **R15 本机 Provider Access Agent**

  - 背景：手工导出、复制 Netscape Cookie 不能满足可移植个人部署；又不采用常驻远端节点。
  - 需求：实现 loopback/Unix Socket 限定的宿主 Agent、一次性授权事务和 Provider 专用持久浏览器目录；平台要求验证时由 UI 发起可见授权，成功后自动发布受限会话并复用。
  - 验收：用户不执行 Cookie 导出/导入 CLI；授权后无需重建容器即可重试；不同 Provider 的状态、目录和会话不可互读。
  - 优先级：P0

- **R16 自适应访问状态机**

  - 背景：匿名失败不都代表需要登录，链接失效、解析器错误、DRM、地区限制和出口挑战必须分开。
  - 需求：实现 `public_probe → public_ready | authorization_required | degraded`，授权成功后进入 `operator_ready`；inspection 冻结上下文，download 不静默换身份。
  - 验收：每个稳定错误只有一个状态迁移；失败不会触发循环登录、无限重试或未知代理回退。
  - 优先级：P0

- **R17 产品内授权与恢复体验**
  - 背景：平台验证是第三方边界，但不应转化为运维人员反复手工取文件。
  - 需求：平台状态页和解析错误提供统一“完成平台验证”“重新探测”“查看限制”动作；Sonner 只用于短时结果，持续状态由页面组件承载。
  - 验收：桌面和 390px 页面可完成授权、取消、超时与重试；刷新页面和重启服务后状态一致。
  - 优先级：P1

### ToC 无感下载与授权续接（040，待实施）

- **R18 可靠且隔离的授权控制通道**
  - 背景：040 §1 F01–F10、F15–F18；当前控制通道、终态、结果确认、活性和权限存在独立缺陷。
  - 需求：Dev/Prod 接线一致；跨 UID 最小权限、原子发布、CAS 终态、可靠 ACK、有限并发和明确 owner；本地材料可读不冒充平台授权。
  - 验收：部署集成和故障注入覆盖取消/完成乱序、Redis 写失败、API 重启、跨 UID、并发用户和其他平台不受授权等待影响。
  - 优先级：P1。
- **R19 受限来源同步与有效访问证明**
  - 背景：040 §1 F08、F11–F12、F17–F18，§6–§7。
  - 需求：按批准 Provider/主体同步；ACK、revision、来源时效、撤销及同主体校验完整；新机不要求手工复制 Cookie，但也不假设第三方授权随代码存在。
  - 验收：登录态域/path 不丢失；空值不清空有效来源；乱序不复活已撤销材料；过期、本机来源故障、平台挑战可区分。
  - 优先级：P1。
- **R20 一次提交的持久下载意图**
  - 背景：040 §3、§5；现有页面内存和回调不能跨关闭/刷新续接。
  - 需求：解析前保存轻量意图；使用既有 PG/outbox/Worker 幂等交接现有下载 job，不创建另一套执行引擎。
  - 验收：双击、重发、重复回调只创建一个 job；授权完成自动续接原意图；页面关闭及服务重启可恢复；取消不可复活。
  - 优先级：P1。
- **R21 统一动作、错误与等待体验**
  - 背景：040 §1 F06、F13–F14、F17，§8。
  - 需求：服务端输出真实可执行动作，前端不从 hostname/字符串猜测权限；恢复中不先报失败，首次同意/强制验证才请求必要操作。接口仍由 FastAPI/Pydantic → OpenAPI → @umijs/openapi 生成。
  - 验收：三个问题平台及状态页无空按钮/必失败按钮；统一 Sonner 瞬时反馈和持久任务状态；桌面、390px、明暗主题和页面重入可用。
  - 优先级：P1。
- **R22 真实交付和观察预算分离**
  - 背景：040 §9–§11。
  - 需求：自动恢复预算集中；Canary 观察超时不冒充业务失败；平台能力以当前 metadata/media 分层证据为准。
  - 验收：先完成 YouTube/抖音/Reddit 真实文件，再运行现有 24 平台矩阵；大文件仍查询原任务；所有结果按公开成功/需动作/部署不可用/不支持如实记录。
  - 优先级：P1。

---

## 二、Plan（执行计划）

> 按 038 §6 五阶段；任务间 `→` 表依赖；每项验证对应 AGENTS.md §实现与验证 的最小充分检查。提交 scope 用后端稳定模块名（`runner` / `worker` / `canary` / `docs`）。

### P1 共享安全模块 + 凭证哈希一致性（对应 R1–R3）

- [x] P1.1 新建 `app/workers/runner/_secure_file.py`：`_no_follow`、原子写、私有目录校验；替换 `provider_cookie_sync.py:275`、`provider_session_files.py:116`、`provider_cookie_queue.py:237` 的 `_no_follow` 与 `_atomic_write_*` 三处。
  - 依赖：无。验证：`ruff`/`mypy`/`pytest` + `grep` 确认单一定义。
- [x] P1.2 新建 `app/workers/runner/netscape_cookie.py`：统一解析/序列化/校验/过期/`\x00`/allowlist；替换 `provider_cookie_export`、`provider_cookie_file`、`provider_session_files._validate_netscape_cookie`。
  - 依赖：P1.1。验证：cookie 相关单测全绿；allowlist 匹配收敛一处。
- [x] P1.3 `provider_session_maintainer.py:89,273` 改 HMAC 派生，复用 `provider_sessions.py:158` 的密钥来源。
  - 依赖：P1.1。验证：状态文件哈希可跨进程稳定对账；无未加盐哈希残留。
- [x] P1.4 收敛 `provider_cookie_*` / `provider_session_*` 职责后删除空文件与转发层，同步 PROJECT.md 目录归属（如新增模块位置）。已核对 runner 目录无空文件或纯转发层，并补充 `_secure_file.py` 与 `netscape_cookie.py` 的职责归属。
  - 依赖：P1.1–P1.3。验证：runner 目录无空文件或纯转发层，通用文件与 Cookie 原语各保持单一定义；Ruff、mypy、pytest 全绿。

### P2 错误语义 + 冷却预算（对应 R4–R8）

- [x] P2.1 `verification.py`/`gallery.py`/`collection.py` 产物非法统一 4xx，基础设施失败保留 5xx。
  - 依赖：无。验证：新增「时长超限 →4xx」「无流 →4xx」「上游 5xx 透传」回归测试。
- [x] P2.2 `commands.py` probe/remux/public_asset 构造命令时补传 `failure_context`，使 `classify_provider_failure` 全阶段生效。
  - 依赖：无。验证：probe 失败落库稳定错误码。
- [x] P2.3 冷却：`route_cooldowns.py` 增加指数退避 + jitter + 滞回；`block()/finish()` 落库 `reason_code` + 稳定错误码。
  - 依赖：无。验证：冷却可追溯；恢复需连续成功。
- [x] P2.4 删除 `canary/service.py` `_RUNNER_ERROR_ALIASES` 折叠，`canary_internal_error` 仅限探测自身 bug。
  - 依赖：P2.2。验证：canary 证据区分验证码/POT/凭证三类。
- [x] P2.5 确认 `download` 队列 DLX 绑定；`dlq` 重放与 `sweeper` 三层恢复去重计数；重试预算可观测。
  - 依赖：无。验证：消息二次失败进入 DLQ；幂等重放不重复执行。

### P3 分布式凭证租约（对应 R9）

- [x] P3.1 设计租约数据模型与 Redis key 规范（`{provider}:{credential_version}` + TTL + 心跳）。
  - 依赖：无。验证：方案评审通过（可选）。
- [x] P3.2 实现租约协调器 `app/workers/runner/`（或 `integrations/`），接入 operator runner 下载前 acquire / 完成 release / 心跳续租。
  - 依赖：P3.1。验证：两副本并发仅一个获租约；崩溃后到期接管（集成测试）。
- [x] P3.3 不适用：P3.2 已落地 Redis 跨副本租约；operator runner 的生产 Compose 已配置共享 Redis，未采用单副本 SPOF 作为长期方案。
  - 依赖：P3.1。验证：已由 P3.2 的 Redis 互斥、TTL 接管、心跳续租测试和 Compose 配置覆盖；不采用单点告警替代租约。

### P4 孤儿 GC + 会话检测（对应 R10–R11）

- [x] P4.1 `download/sweeper.py` 增加 `runner_workspace_root` 年龄基 GC，回收无活跃任务的 `{task_id}-*`。
  - 依赖：无。验证：阈值后回收；活跃任务目录保留。
- [x] P4.2 `provider_sessions.py is_ready()` 改按 provider 校验；`assert` 改受控 4xx。
  - 依赖：无。验证：多 provider 失效可感知；异常不再 500。
- [x] P4.3 确认浏览器会话「Cookie 轮换失败」归 `credential_expired` 而非 `provider_link_unavailable`。
  - 依赖：P2.2。验证：构造轮换失败落库正确错误码。

### P5 状态证据对称 + 权益漂移（对应 R12–R13）

- [x] P5.1 `status_evidence.py` 纳入失败证据（稳定错误码 + `context_generation_id` 过滤）。
  - 依赖：P2.4。验证：平台回归秒级可见；单链接失效不污染状态。
- [x] P5.2 落实 inspect attestation 权益漂移 → disable `credential_version`。
  - 依赖：无。验证：漂移后对应版本停用，不 fail-open。

### P6 无额外机器的可移植部署（对应 R14–R17）

- [x] P6.1 将核心 readiness 与可选 Provider 授权解耦，补充全新工作目录 Compose 契约测试。
  - 依赖：无。验证：`.env.example` 默认不启用 profile、operator endpoint 或 operator policy；两套 Compose 的核心服务均无 profile，operator 服务保持显式 opt-in；`docker compose --env-file .env.example -f docker-compose.yml config --quiet` 通过。
- [x] P6.2 实现 Provider 能力状态机和按当前宿主/出口生成的探针 generation。
  - 依赖：P6.1。已交付：访问状态投影、当前 generation 过滤，以及匿名降级与受控线路缺少上下文的区分。验证：匿名成功、需授权、平台挑战、临时故障、永久不支持路径测试。
- [ ] P6.3 完成本机 Access Agent 与一次性授权事务的端到端验收，先覆盖 YouTube，再复用 Provider policy 扩展。已有代码原型不等于真实下载闭环；040 F01–F18 对应缺陷先按 P7 修复。
  - [x] P6.3a macOS v1：按 Provider 隔离的专用 Chrome 目录、授权等待、内存租约和按需 LaunchAgent；覆盖 Chrome-backed Provider，并有取消/超时/隔离测试。
  - [x] P6.3a.1 历史 Compose 接线：曾让 YouTube、抖音、Reddit Operator Runner 使用对应 Agent 队列；2026-09-22 经竞品复核确认不适合作为 ToC 默认链路，已由 P8.2a 的部署级来源替代。优酷/腾讯视频和视频号继续保持各自受控来源边界。
  - [x] P6.3b 产品内一次性事务验收：API 创建 nonce，前端调用并轮询，宿主消费 control 请求；生产 control 挂载、跨 UID、原子发布、取消竞态、结果确认和超时语义已按 P7 验收。无需 Cookie CLI 的真实 Redis + Agent 控制全环测试通过；真实平台媒体下载仍由 P8.7 单独验收。
  - [x] P6.3c 历史原型（2026-09-23 已移除）：当前 Chrome 扩展与 Native Messaging 曾用于本机同步，但不满足开源部署无感解析的目标，也未完成真实平台媒体闭环。现仅保留部署级来源与个人部署的隔离 Chrome 授权。
  - 依赖：P6.2。验证：最终交付需覆盖无 Cookie CLI 的可见授权、会话发布、取消/超时、Provider 隔离测试。
- [ ] P6.4 接入 Web 平台状态与解析恢复动作，完成明暗主题、桌面和 390px 浏览器验收。
  - [x] P6.4a 平台状态页已接入访问状态和产品内本机授权事务，并由生成 OpenAPI 类型驱动。
  - [ ] P6.4b 产品内授权完成后自动重试原链接、明暗主题和 390px 真实浏览器验收。
  - 2026-09-21 进展：普通用户不再看到仅管理员可执行的共享宿主授权入口；390px 明暗主题下的真实已完成任务页已验证。按需 Agent 探测预算覆盖实测约 1.8 秒的 launchd 冷启动，不再把短暂未响应误报为未安装。产品内授权完成后的同意图自动续接仍依赖 P8.1–P8.3，未据此勾选 P6.4b。
  - 依赖：P6.2–P6.3。验证：真实浏览器授权后重试原链接；重启后无需再次手工获取。
- [ ] P6.5 在当前宿主的独立 clean-room Compose project 中运行固定 metadata/media 矩阵，分别记录匿名成功、需平台验证和不可支持项。
  - 依赖：P6.4。验证：使用独立临时卷、浏览器目录和项目名且不挂载业务私有状态；产出真实制品与失败证据。共享公网出口的限制单独记录，不要求额外机器。

### P7 修复新增授权链路回归（对应 R18–R19、R21）

> 完整触发条件和代码位置见 040 §1 同号 F。2026-09-21 已完成 P7.01–P7.18 的代码修复与自动化回归；生产配置契约、真实 Redis + Agent 控制全环，以及宿主/API 不同 UID 的隔离挂载验证通过。上述结果不代表真实平台媒体下载已经通过，平台闭环仍按 P8.7 验收。

- [x] P7.01 / F01 **[P1] 生产控制通道**：补生产 API 受限 control 挂载/配置；不得暴露快照与密钥。验收：开发和生产配置契约 + 实际 begin→Agent→ 结果全环。依赖：与 P7.02 一起交付。
- [x] P7.02 / F02 **[P1] 跨 UID 权限**：初始化与 API 读写分离，明确生产者/消费者权限。验收：API UID 与宿主 UID 不同仍可请求/应答/取消，API 不可改 sources 或读秘密；不能仅跑同 UID 单测。
- [x] P7.03 / F03 **[P1] 原子入队**：完整写入后原子发布；忽略临时文件。验收：在创建/写入/fsync 各点插入消费者，不丢失请求、不消费半包；崩溃残留可清理。依赖：P7.02。
- [x] P7.04 / F04 **[P1] 终态 CAS**：完成/取消/过期以版本条件迁移，禁止迟到结果复活事务。验收：并发 GET/cancel、重复结果、截止边界都只有一个终态；覆盖本轮复现。
- [x] P7.05 / F05 **[P1] 可靠结果 ACK**：持久化结果成功后确认消费，失败可重放。验收：删除前后/状态写失败/进程退出均不丢结果、不重复恢复。依赖：P7.04。
- [x] P7.06 / F06 **[P1] 前端在途取消**：generation 失效、迟到 POST 补偿取消、迟到 GET 不回调。验收：POST 未返回就关闭、GET 未返回就取消、换 Provider 后旧请求完成；不重新解析/下载。依赖：P7.04。
- [x] P7.07 / F07 **[P1] 授权等待不阻塞刷新**：同一个 Agent 在等待用户时继续有界处理新 probe/refresh。验收：一平台等待验证，另平台新下载可正常获得租约；无十分钟队头阻塞。
- [x] P7.08 / F08 **[P1] 真实授权判定**：source_available 与上游 verified 分开，绑定主体和执行上下文；失败保持准确原因。验收：格式合法但已撤销材料不能返回 authorized；验证成功也不能直接标记媒体完成。依赖：P7.04、P7.05。
- [x] P7.09 / F09 **[P1] 宿主来源权限**：个人隔离尚未实现前，仅明确批准的部署管理员可修改共享来源；其他用户得到受控拒绝。验收：用户 A 无法切换 B/宿主来源，非本机部署不能误操作用户浏览器；明确记录后续个人 grant 的迁移策略。
- [x] P7.10 / F10 **[P1] 准入与背压**：活跃授权按 owner/provider/source 去重，限制线程、浏览器、队列总量；同来源发布串行。验收：并发请求下资源有界，返回可解释的排队/限流，不启动无限 Chrome。依赖：P7.09。
- [x] P7.11 / F11 **[P2] Cookie 查询作用域**：批准域内覆盖子域和 path，保留必要 store/hostOnly 语义，不扩大权限。验收：根域、www host-only、非根 path、多 store 的合成及扩展集成用例。
- [x] P7.12 / F12 **[P2] 空值与失效区分**：按 Cookie 语义处理合法空值；坏批次不等同退出登录。验收：有效 SID + 空值字段不删除有效来源；明确撤销仍及时失效。依赖：P7.11。
- [x] P7.13 / F13 **[P2] 平台动作能力**：腾讯视频/优酷等文件来源不展示必失败的 Chrome 授权，按实际部署能力给动作。验收：所有状态页 Provider 的按钮与后端支持能力一致。
- [x] P7.14 / F14 **[P2] 视频号空操作**：状态页提供真实刷新/维护说明，解析页保留明确批准的元宝重试；不能用空回调冒充动作。验收：两个入口点击均有可验证行为，且不走通用 Cookie 路线。
- [x] P7.15 / F15 **[P2] CLI 来源一致性**：dedicated_chrome 成功同样发布来源选择。验收：两种来源分别 authorize→install/drain→refresh，不错误回落另一来源。
- [x] P7.16 / F16 **[P2] deadline 与保留期分离**：真实到期收敛为 expired，保留有限结果查询窗口，清理无引用残留。验收：真实 Redis TTL + 虚拟时钟 + Agent 迟到结果；不得只用 expire 空实现。
- [x] P7.17 / F17 **[P2] 同步握手**：request_id/provider/revision ACK、有限等待、明确失败；syncAll 不伪报全成功。验收：未安装、宿主失败、延迟同步及旧 ACK；解析不能把“已发消息”当“来源已更新”。
- [x] P7.18 / F18 **[P2] 活性探针**：区分安装 marker 与实际控制通道可达。验收：marker 存在但 Agent 停止、wrapper 失效时快速受控失败，不创建无限等待事务。

### P8 完成无感下载产品闭环（对应 R19–R22）

> 以下是已有能力缺口/目标能力，不作为新引入代码缺陷；详细设计与验收见 040 §3–§11。不新增额外机器或另一套任务基础设施。

- [ ] P8.1 **[P1] 持久意图与幂等交接**：在 downloads 域保存解析前意图，PG/outbox 驱动准备步骤，原子或等价幂等地交接现有 job；handed_off 后只投影 job。验收：双击/重放/重启只有一个 job，输入指纹冲突明确报错。依赖：P7.04–P7.05。
- [ ] P8.2 **[P1] 已批准能力自动复用**：绑定 owner/provider/主体/用途/版本/时效，启用平台需明确同意；同步单飞、撤销版本防乱序覆盖，正常轮换无弹窗。验收：账号切换、退出登录、过期 session Cookie、桥失联和未启用平台均有正确边界。依赖：P7.08–P7.12、P7.17–P7.18。
  - [x] P8.2a **ToC 默认来源去客户端化**：YouTube、抖音、Reddit Operator Runner 统一读取部署方单平台只读来源；普通解析不唤醒扩展，服务端托管重试不创建本机授权事务。`PROVIDER_SESSION_DIR` 可由 Secret volume/controller 投影并在每次操作热读取；浏览器桥只保留为个人部署可选导入器。
  - [x] P8.2a.1 **启动来源准入与有效拓扑**：统一启动入口在 Compose 前验证本地文件/受控动态来源，只启用可用 Operator；缺少来源时删除遗留空容器、移除 endpoint/default policy，并将已有 Canary operator 目标按 Provider 能力降为匿名。运行计划使用被忽略的 `0600` 文件且不写入 Cookie。2026-09-22 实测 YouTube/视频号 Operator ready，抖音/Reddit 空 Operator 被移除；两者公开样本仍返回 `authorization_required`，因此不作为 P8.7 真实下载通过证据。
  - [ ] P8.2b **托管来源生命周期**：补管理员可观察的来源 revision/到期/撤销状态和原子轮换操作；需要多主机时在现有 `ProviderCookieSync` 后增加认证 Broker/secret-manager adapter，禁止 API、前端和业务数据库暴露明文。验收：两台 Runner 只获得单次租约，轮换无需重启，旧 inspection 因 generation 变化拒绝执行。单机 Compose 不提前引入 Broker。
- [ ] P8.3 **[P1] 服务端授权后续接**：授权关联 intent，状态提交可靠地产生恢复事件；有限重试集中预算，保持冻结上下文。验收：关闭页面后完成授权仍可续接，取消不可复活，不隐式升级 public→operator、不切账号。依赖：P8.1–P8.2、P7.06–P7.07。
- [ ] P8.4 **[P1] 动作/错误与生成契约**：FastAPI/Pydantic 定义受约束 next_action 和状态，生成 OpenAPI 与 @umijs/openapi 客户端；删除散落的 hostname/错误字符串恢复决策。验收：schema/客户端一致，配置故障不提示重登，metadata 成功不冒充媒体完成。依赖：P7.13–P7.14、P8.3。
- [ ] P8.5 **[P1] 一次提交交互**：默认下载选项明确展示，一次确认推进；持久状态与 Sonner 分工，必要动作才弹框，刷新/重入恢复同一意图。验收：Radix/shadcn、design.md、明暗主题/桌面/390px/键盘；合集和敏感选项不隐式批量下载；制品就绪与浏览器保存分开。依赖：P8.4。
- [ ] P8.6 **[P1] 大文件与故障恢复**：分开 HTTP、观察、无进度及业务总期限，统一重试预算与 Retry-After；长任务继续查询同一 job。验收：超过 Canary 300 秒仍执行的任务不被记为 provider 失败；断网/429/签名过期在同一授权下有界恢复。依赖：P8.1、P8.3。
- [ ] P8.7 **[P1] 真实平台闭环与清理**：先验证 YouTube/抖音/Reddit，再从现有 registry/固定矩阵枚举全部 24 平台；同宿主隔离 clean-room 与重启验证。验收：保存 metadata、media、实际文件和校验、权限策略、稳定失败原因；统计无动作完成/必要动作后续接；不支持项如实记录，不保证绕过平台验证。只清理本次隔离测试资源，不删除用户会话或业务数据。依赖：P8.5–P8.6，同时收口 P6.4b/P6.5。
  - 2026-09-21 进展：真实浏览器完成 BiliBili 公开样本的解析、360P 任务和制品读取；文件 38,026,077 字节，SHA-256 `bc06dd4f4f8ff5ca2b86a1de3763a44ca33d8726e4a18923c99b9e22c2d20977`，ffprobe 为 H.264 640×360 + AAC、554.117619 秒。Vimeo 1080P 真实任务完成，预览媒体请求返回 206；固定 metadata 矩阵 23 项中 19 项成功，media 首轮 17 项成功，Vimeo、Kick 定向复测分别在 340,961 ms、787,888 ms 成功，确认超过 300 秒的持续任务不会被观察窗口误判为平台失败。YouTube、抖音、Reddit 当时缺少有效服务端来源，视频号受控 Runner 暂不可用；第 24 个注册平台 PeerTube 需要部署方先配置可信实例白名单，不以任意公共实例冒充已验收。2026-09-22 已移除三平台普通请求对浏览器扩展/本机 Agent 的依赖并改为部署级来源，但尚未用新来源完成真实三平台媒体闭环，因此 P8.7 保持未勾选。

---

## 三、可追溯性

| 需求  | 来源结论              | Plan 任务                             |
| ----- | --------------------- | ------------------------------------- |
| R1–R3 | §3、§6.1              | P1.1–P1.4                             |
| R4    | §2-4                  | P2.1                                  |
| R5    | §4                    | P2.2                                  |
| R6    | §2-6                  | P2.3                                  |
| R7    | §2-5                  | P2.4                                  |
| R8    | §2-1                  | P2.5                                  |
| R9    | §5-1、§6.3            | P3.1–P3.3                             |
| R10   | §2-2                  | P4.1                                  |
| R11   | §2-3                  | P4.2–P4.3                             |
| R12   | §2-7                  | P5.1                                  |
| R13   | §5-3                  | P5.2                                  |
| R14   | 031 启动与能力发现    | P6.1–P6.2                             |
| R15   | 031 本机 Access Agent | P6.3                                  |
| R16   | 031 便携访问阶梯      | P6.2–P6.3                             |
| R17   | 031 验收标准          | P6.4–P6.5                             |
| R18   | 040 §1、§7            | P7.01–P7.10、P7.15–P7.18              |
| R19   | 040 §6–§7             | P7.08、P7.11–P7.12、P7.17–P7.18、P8.2 |
| R20   | 040 §3–§5             | P8.1、P8.3                            |
| R21   | 040 §8                | P7.06、P7.13–P7.14、P7.17、P8.4–P8.5  |
| R22   | 040 §9–§11            | P8.6–P8.7                             |

- 建议排期：保留既有 P1–P5 记录；先完成 P7 的 P1 正确性缺陷和相关 P2 回归，再推进 P8 单次提交纵向闭环，最后以真实文件、浏览器和 clean-room 证据收口 P6。不得用新增“已授权”按钮替代下载成功验收。
- 每项完成后按 AGENTS.md §Git 与任务交付 提交：`refactor(runner): <中文描述>` / `fix(worker): ...` / `feat(runner): ...`，附回归证据，未验收不勾选。

## P9 开源部署无感解析执行计划（044）

执行细节已迁移到 044 Plan，需求和验收见 044 PRD，技术方案见 044 Design。以下只作任务导航，不复制状态；旧台账归并关系见 Plan §7。

| 执行任务 | 入口 |
| --- | --- |
| P9.01 统一身份、错误和契约语义 | 步骤、依赖与验收 |
| P9.02 持久解析意图与后台执行 | 步骤、依赖与验收 |
| P9.03 公开访客上下文生命周期 | 步骤、依赖与验收 |
| P9.04 首个公开平台纵向闭环 | 步骤、依赖与验收 |
| P9.05 跨机制验证与重点平台扩展 | 步骤、依赖与验收 |
| P9.06 必要授权与原意图续接 | 步骤、依赖与验收 |
| P9.07 结果、下载交接与存量业务 | 步骤、依赖与验收 |
| P9.08 能力目录与管理员诊断 | 步骤、依赖与验收 |
| P9.09 标准空部署与自动准备 | 步骤、依赖与验收 |
| P9.10 Web 单次提交与页面连续性 | 步骤、依赖与验收 |
| P9.11 Web 持久会话协议收敛 | 步骤、依赖与验收 |
| P9.12 Flutter 契约同步与恢复 | 步骤、依赖与验收 |
| P9.13 引擎维护、更新和回滚 | 步骤、依赖与验收 |
| P9.14 全链路、容量与恢复验收 | 步骤、依赖与验收 |
