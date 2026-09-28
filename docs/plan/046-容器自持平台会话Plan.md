# 046 容器自持平台会话 Plan

日期：2026-09-28。状态：已评审（2026-09-28），S1–S5、S8 代码完成待验收；2026-09-28 修订：登录改为管理页面远程登录（L0–L4，S2 的导入子命令由 L2 删除）；S7 状态页并入 L3；S6、S9 未开始。需求见 [PRD](../prd/046-容器自持平台会话PRD.md)，技术方案见 [Design](../design/046-容器自持平台会话设计.md)。**任务状态、证据只在本文维护。**

工作方式沿用 [044 Plan §1](044-开源部署无感解析Plan.md#1-sdd-工作方式)：先写能判定的测试，再实现最小闭环；代码完成不等于平台实测完成；只有“已验收”才勾选。

## 1. 基线（2026-09-28 已核实）

- 容器匿名出口为 GCP 东京机房 IP，YouTube 间歇性要求 bot 验证；PO Token（bgutil 1.3.2）与 node JS 解密均正常。
- 宿主维护进程在 2026-09-25 后已退出；`youtube-operator-runner`、`douyin-operator-runner` 中不存在 `cookies.txt`。
- 非交互进程执行 `provider_startup start` 得到 `browser_permission_denied`。
- 本机 `.env` 当前含 `AUTO_BROWSER_SOURCE_PROVIDERS=youtube`（本次排查临时加入），S8 中随配置一并删除。
- 当前 API 的 `RUNNER_DEFAULT_ACCESS_POLICIES={"youtube":"operator_public"}`，但账号来源为空，YouTube 解析会报告配置缺失，直到 046 上线并完成导入。

## 2. 发布依赖

| 里程碑 | 任务 | 退出条件 |
| --- | --- | --- |
| M1 基础 | S1、S2 | 站点模型、表结构、导入命令可登记和撤销 |
| M2 容器会话 | S3、S4 | broker 与浏览器在受控上游上完成 bootstrap、保活、状态机 |
| M3 切换 | S5、S6、S7、S8 | 路由切到会话 Runner，旧链路全部删除，文档更新；**一次发布**，不存在新旧并行期 |
| M4 验收 | S9 | PRD §7 全部 AC 及真实平台矩阵 |

M3 是破坏性替换：S5–S8 同一发布，发布前部署者需按新手册重新导入会话（旧来源本已过期，无可迁移数据）。

## 3. 执行任务

<a id="s1"></a>

### S1 站点模型、注册表与数据表

- [ ] **S1**；状态：代码完成待验收；依赖：无。
  - 需求：FR-02、FR-04（非秘密读取）；NFR-03。
  - 步骤：
    1. 引入锁定版本的 `tldextract`（离线快照、含私有后缀、不写缓存），实现 `registrable_site`，拒绝 IP、单标签名、未收录后缀和公共后缀。
    2. 在 `app/services/site_sessions.py` 以数据声明现有全部 11 个账号会话平台条目和未知站点默认条目（Design §3.2）；`app/integrations/site_session_catalog.py` 组合 `ProviderProfile` 的主机与 Cookie 域。
    3. `schema.sql` 新增 `site_sessions` 与 ORM 模型；仓储分为只读非秘密列的 `SiteSessionStates`（API 用）和条件写入密文的 `SiteSessionSecrets`（仅 broker、导入命令使用）。旧表在 S8 删除。
    4. 在已有数据库和空数据库上幂等执行 `schema.sql`。
  - 验收：PRD AC-02；单元测试覆盖站点解析全部样例；仓储测试断言 `SiteSessionStates` 的 SQL 不含 `ciphertext`。

<a id="s2"></a>

### S2 一次性导入命令

- [ ] **S2**；状态：`status`／`revoke` 与写入逻辑保留；`import` 子命令与 Chrome 读取器被 macOS 隐私保护阻断，已由 L0–L4 取代，L2 删除；依赖：S1。
  - 需求：FR-01、FR-10；NFR-03、NFR-05。
  - 步骤：
    1. 把 `chrome_provider_cookies.py` 迁为 `app/workers/session/chrome_reader.py`（原位置删除，旧宿主链路改为从新位置导入，直到 S8 删除）；增加 Profile 列表与钥匙串拒绝识别。
    2. 实现 `python -m app.workers.session.seed`，子命令 `import`、`status`、`revoke`；Profile 自动选择规则见 Design §6.1。
    3. 条件写入、撤销墓碑、`revoked → seeded` 重新导入；输出只含计数和修订。
  - 验收：PRD AC-01、AC-07（导入与撤销部分）；用临时 Chrome 目录夹具覆盖单／多／无 Profile；日志扫描无 Cookie 值。

<a id="s3"></a>

### S3 session-broker

- [ ] **S3**；状态：代码完成待验收；依赖：S1。
  - 需求：FR-03、FR-05、FR-06；NFR-02、NFR-06。
  - 步骤：
    1. 新增 `app/workers/session/broker.py`（调度、每站点锁、并发 2、保活计划、条件写入）与纯函数状态机 `app/services/site_session_lifecycle.py`（Design §5）；`site_sessions` 增加 `consecutive_failures`，同状态刷新不改 `state_changed_at`。
    2. broker 作为唯一调度者经 `session_net` 调用浏览器 `identity`／`bootstrap`／`keepalive`／`headers`／`forget`（`browser_client.py`），jar 双向封装（`sealing.py`）。
    3. Runner RPC（HMAC，`rpc.py`）：`POST /internal/v1/site-sessions/lease`、`POST /internal/v1/site-sessions/failures`；`broker_app.py` 提供健康检查与扫描循环，端口 19200。
    4. 告警：进入 `reseed_required` 的唯一胜出写入输出一条 WARNING 日志；项目无独立通知通道（Design §5）。
    5. Compose 服务定义随 S4 与浏览器一起加入；`provider-sources` 的旧文件分发在 S8 删除。
  - 验收：PRD AC-05（broker 停止部分）、AC-06、AC-09；状态机和租约的单元测试；并发导入与迟到保活的竞争测试。

<a id="s4"></a>

### S4 session-browser 容器

- [ ] **S4**；状态：代码完成待验收；依赖：S3。
  - 需求：FR-03、FR-07、FR-08；NFR-02、NFR-04、NFR-06。
  - 步骤：
    1. 后端 Dockerfile 增加 `session-browser` 目标：依赖组 `browser`（`playwright==1.63.0`）安装固定版本 Chromium；非 root、只读根、`cap_drop: ALL`、tmpfs `/tmp`／`$HOME`、Profile 卷 `site_session_profiles`。开发与生产 Compose 增加 `session-broker`、`session-browser` 与内部网络 `session_net`；生产要求显式的 `SITE_SESSION_RPC_SECRET`、`SITE_SESSION_BROWSER_SECRET`。
    2. `app/workers/session/browser.py`：Playwright 持久化上下文（每站点 Profile、代理、Cookie 读写）、登录判定、主框架导航拦截、确定性 jar 导出；`browser_app.py`：身份密钥、五个签名接口、并发 2、单次 60 s。
    3. 视频号元宝脚本从宿主 `yuanbao_session.py` 迁入浏览器（宿主版本在 S8 删除）。
    4. 崩溃恢复：Profile 在卷上；卷丢失时由 broker 按 `profile_missing` 重建。
  - 验收：浏览器逻辑与 broker↔浏览器契约测试；真实镜像内对真实站点的冒烟（见执行记录）；PRD AC-10 的出口部分随 S6。

<a id="s5"></a>

### S5 会话路由与 session-runner

- [ ] **S5**；状态：代码完成待验收；依赖：S3。与 S6–S8 同一发布。
  - 需求：FR-04、FR-06；NFR-01、NFR-06。
  - 步骤：
    1. `SiteSessionRoutes` 接入 API inspect、下载意图与 Canary；会话记录强制 `OPERATOR_PUBLIC`／`PERSONAL_ENTITLED`（Design §3.4，未新增策略值）。
    2. 新增错误码 `provider_session_not_ready`，删除 Design §7 所列错误码；更新 `provider_errors.py` 规则与前端 `error-messages.ts`。
    3. Runner 新增 `session` 模式：按任务申请租约、tmpfs jar、结束删除、认证类失败上报；Redis 并发键改为站点。
    4. 访问上下文冻结 `site + seed_revision`；重新导入使旧 inspection 失效。
    5. 重新生成 OpenAPI 与前端 `src/api`。
  - 验收：PRD AC-05（全部）、AC-08、AC-09；以出口日志证明会话路线故障时匿名 Runner 零请求。

<a id="s6"></a>

### S6 出口一致

- [ ] **S6**；状态：未开始；依赖：S4、S5。
  - 需求：FR-07。
  - 步骤：`SITE_EGRESS_ROUTES` 替代 `RUNNER_PROVIDER_EGRESS_PROXIES`；导入时写入 `egress_route`；浏览器、Runner、bgutil 按记录选择；路由改变要求重新导入。
  - 验收：PRD AC-10，三方出口 IP 一致的日志证据。

<a id="s7"></a>

### S7 管理员状态页与删除授权事务

- [ ] **S7**；状态：删除授权事务已完成（随 S8），站点会话状态接口与页面并入 L3；依赖：S5。
  - 需求：FR-05、FR-09。
  - 步骤：删除 `/api/providers/{key}/authorization*`、`ProviderAuthorizationService`、前端授权对话框和 `lib/provider-authorization.ts`；状态接口与页面改为展示 Design §7 字段和导入命令；按 `design.md` 实现，桌面与 390px 真实浏览器验证。
  - 验收：PRD AC-06（展示部分）、AC-12（API／前端部分）；前端 `format:check`、`lint`、`test`、`build`。

<a id="s8"></a>

### S8 删除旧链路与文档

- [ ] **S8**；状态：代码完成待验收；依赖：S5、S6、S7（S6 与 S7 状态页之外的部分先行删除，见执行记录）。
  - 需求：FR-09。
  - 步骤：
    1. 按 Design §8 删除模块、类型、Compose 服务与卷、配置键、测试；`schema.sql` 删除 `provider_session_sources`、`provider_authorizations`（`DROP TABLE IF EXISTS`）及其 ORM；删除 `provider_session_policy.py` 中与站点会话注册表重复的 Cookie 校验；开发与生产 Compose 同步。
    2. 新增运行手册 `docs/operations/011-站点会话运行手册.md`（导入、状态、撤销、换机、告警处理）；删除 002、003、008 中宿主来源内容；043 标为已被 046 取代并删除正文；044 PRD 的 FR-17／AC-21 改为指向 046，044 Plan 同步追溯表。
    3. 改写 AGENTS.md“安全与运行约束”中的宿主元宝浏览器条款和“凭据 Runner 单 Provider 只读 Secret”条款；README 部署章节改为“一次导入 + compose up”。
    4. BACKLOG 增加 046 导航。
  - 验收：PRD AC-12；`rg` 检查 Design §8 列出的标识符在代码、Compose、文档中不再出现；后端全量检查；两份 Compose `config --quiet` 通过。

<a id="l0"></a>

### L0 远程登录可行性

- [x] **L0**；状态：已完成（2026-09-28）；依赖：S4。
  - 证据：在 `session-browser` 容器内经 egress-proxy 打开 `https://yuanbao.tencent.com/`，页面直接弹出微信扫码登录（二维码位于 `open.weixin.qq.com` 子框架）；打开 `https://www.douyin.com/` 先出现滑块验证。结论：提供可交互画面，验证码由管理员完成；不做只截取二维码的专用实现。

<a id="l1"></a>

### L1 会话浏览器登录接口

- [x] **L1**；状态：已完成（2026-09-28），见执行记录；依赖：L0。
  - 需求：FR-01；NFR-02、NFR-03。
  - 步骤：Design §6.1 会话浏览器五个接口；临时 Profile 与成功后原子替换；空闲 5 min 取消；每站点一个、全局两个登录；登录期间顶层导航只限 `https`。
  - 验收：用假浏览器与本地测试页覆盖开始、画面、输入、登录判定、保存、取消、超时、并发拒绝、失败时旧 Profile 不变。

<a id="l2"></a>

### L2 broker 转发与管理员接口

- [x] **L2**；状态：已完成（2026-09-28），见执行记录；依赖：L1。
  - 需求：FR-01、FR-10、FR-11。
  - 步骤：broker 签名通道 `SITE_SESSION_ADMIN_SECRET` 与登录转发、保存时过滤加密写入；API 管理员接口（Design §6.1 表）写入 OpenAPI，请求体不进入操作日志；撤销由 API 条件写入墓碑；两份 Compose 与 `.env.example` 同步；删除 `seed.py`（含 `status`／`revoke`，由管理页面取代）、`chrome_reader.py` 及测试；没有访客模式的平台在无会话时把 “Fresh cookies are needed” 归为 `provider_session_not_ready`；运行手册 011 改为管理页面登录。
  - 验收：PRD AC-01、AC-07；接口与 broker 单元、集成测试；`rg chrome_reader` 无结果；后端全量检查。

<a id="l3"></a>

### L3 平台状态页：站点会话与远程登录

- [ ] **L3**；状态：未开始；依赖：L2。取代 S7 的页面部分。
  - 需求：FR-01、FR-05、FR-11。
  - 步骤：重新生成 `src/api`；平台状态页“站点会话”区块与登录弹窗（画面、指针与键盘转发、保存、放弃）；按 `design.md` 实现。
  - 验收：前端 `format:check`、`lint`、`test`、`build`；桌面与 390px 真实浏览器验证。

<a id="l4"></a>

### L4 真实登录端到端

- [ ] **L4**；状态：未开始；依赖：L3。并入 S9。
  - 步骤：管理员在页面中扫码登录元宝 → 视频号样本解析与完整文件；`docker compose down && up` 后会话自动恢复；撤销与重新登录。
  - 验收：PRD AC-01、AC-03、AC-07、AC-11 的记录。

<a id="s9"></a>

### S9 真实平台验收

- [ ] **S9**；状态：未开始；依赖：S1–S8。
  - 需求：全部 FR／NFR。
  - 步骤：在本机完成 YouTube、抖音（账号）、Reddit、视频号、优酷、腾讯视频和一个未适配站点的导入；执行冷启动（`down && up`，宿主不运行本项目进程）、宿主重启和 7 天无人值守观察；每平台 3 个样本。
  - 验收：PRD AC-01～AC-12，逐条记录命令、版本、出口、预期／实测和脱敏结果。

## 4. 检查入口

- 后端（`backend/`）：`uv run ruff check app tests`、`uv run ruff format --check app tests`、`uv run mypy app`、`uv run pytest`。
- 前端（`frontend/`）：`pnpm format:check`、`pnpm lint`、`pnpm test`、`pnpm build`。
- Compose：`docker compose -f docker-compose.yml config --quiet`；生产 Compose 同上。

## 5. 追溯

| 需求 | 任务 |
| --- | --- |
| FR-01 | L1、L2、L3 |
| FR-02 | S1 |
| FR-03 | S3、S4 |
| FR-04 | S1、S5 |
| FR-05 | S3、S7 |
| FR-06 | S3、S5 |
| FR-07 | S4、S6 |
| FR-08 | S4 |
| FR-09 | S7、S8 |
| FR-10 | S2（`revoke`） |
| FR-11 | L2、L3 |
| NFR-01～NFR-06 | S3、S4、S5、S9 |

## 6. 执行记录

### S1（2026-09-28）

- 实现：`app/services/site_sessions.py`（状态、权益、登录校验、11 个平台条目、PSL 解析）；`app/integrations/site_session_catalog.py`（URL／主机 → 站点与 Cookie 域）；`app/models/site_session.py`；`app/repositories/providers/site_sessions.py`；`schema.sql` 新增 `site_sessions`；依赖 `tldextract 5.3.2`。
- 设计修正（已同步 Design §3）：视频号与腾讯视频同在 `qq.com` 下，已知平台的站点键允许比可注册域名更具体（`weixin.qq.com`、`v.qq.com`）；主机与 Cookie 域复用 `ProviderProfile`，不另建 `linked_sites`；注册表放在 services，组合放在 integrations，遵守架构测试；旧表推迟到 S8 删除。
- 测试：新增 `tests/unit/services/test_site_session_policy.py`、`tests/unit/integrations/test_site_session_catalog.py`、`tests/integration/test_site_session_repository.py`，覆盖 PRD AC-02 全部样例、拒绝项、20 并发首次导入单胜者、迟到保活不能覆盖新导入、条件状态转换、撤销墓碑与重新导入、状态读取的 SQL 不含 `ciphertext`、schema 幂等与墓碑约束。
- 门禁：`ruff check`、`ruff format --check`、`mypy app`（596 文件）通过；`pytest` 2184 passed、4 skipped（RabbitMQ、MinIO、下载角色 URL 未提供，Linux `O_PATH`），跳过项与本次改动无关。
- 数据库：`schema.sql` 在本机既有 `video` 库连续执行两次成功，`site_sessions` 为空；隔离 schema 空库测试通过。运行中的 API `/health/ready` 仍为 200。
- 未验收边界：S1 无真实平台行为；AC-02 的最终验收随 S2 导入命令一起做端到端确认。

### S2（2026-09-28）

- 实现：`app/workers/session/seed.py`（`import`／`status`／`revoke`，退出码 0／2／3／4）；`app/workers/session/chrome_reader.py`（由 runner 迁入，新增 `chrome_profiles` 读取 `Local State` 显示名、钥匙串拒绝识别为 `PermissionError`）；`app/core/security/site_session_cipher.py`（绑定 `site|seed_revision|jar_version`）；`Settings.site_session_encryption_key` 与既有 Fernet 校验共用；`.env.example` 增加 `SITE_SESSION_ENCRYPTION_KEY`；本机 `.env` 追加新生成的密钥（仅追加，未改动已有项）。
- 附带修正：读取器搬出 `workers/runner/` 后不再计入媒体 Runner 发布指纹（它只在宿主运行），`release_identity._OPERATOR_MODULES` 与对应测试已同步。
- 测试：新增导入选择（单／多 Profile、显式 Profile、未登录、仅会话 Cookie、权限拒绝优先于猜测、Chrome 缺失、跨域与过期过滤、未知站点）、配置加载、密文绑定、钥匙串拒绝、Profile 列表，以及导入→再导入→撤销→再导入的数据库集成测试。
- 门禁：`ruff check`、`ruff format --check`、`mypy app`（599 文件）通过；`pytest` 2205 passed、4 skipped（原因同 S1）。
- 本机实测：`status` 读取本机数据库，输出“尚未登记任何站点会话”；从非交互进程执行 `import --site youtu.be`，正确返回退出码 3 与钥匙串提示（读取器此前会把钥匙串拒绝静默处理成“没有 Cookie”，现已明确区分）；`revoke` 无会话返回 2；`co.uk` 被拒绝。
- 未验收边界：PRD AC-01 的“成功登记”分支需要部署者在自己的 Terminal 中执行一次 `import` 并允许钥匙串访问，尚未执行；该步骤完成后记录 Cookie 数量与修订（不记录值）即可关闭 AC-01 的实测部分。

### S3（2026-09-28）

- 实现：`broker.py`、`broker_app.py`、`browser_client.py`、`contracts.py`、`rpc.py`、`sealing.py`（`app/workers/session/`）；`app/services/site_session_lifecycle.py`；`Settings` 增加 `session-broker` 角色、两个 HMAC 密钥（≥32 字节校验）、浏览器地址、扫描／保活／租约时长；`site_sessions.consecutive_failures`。
- 设计修正（已同步 Design §5、§6.2–6.4）：broker 是唯一调度者、浏览器为被动 RPC（浏览器不需要访问 broker）；jar 双向封装、浏览器按进程生成身份密钥；项目不存在“管理员通知通道”，告警改为唯一胜出写入的 WARNING 日志加状态页；新导入遇到认证类挑战时停留在 `verifying` 计数，而不是立即要求重新导入；进入 `degraded` 后立即复验。
- 测试：状态机全部转换；封装（错误用途、错误密钥、篡改、畸形、大小）；签名 RPC（往返、错误密钥、重放、篡改、不可达）；broker 与真实 Postgres（导入→验证→轮换写入、浏览器不可达重试、登出只告警一次、保活到期与 Profile 重建、降级→复验→升级到重新导入、24 h 截止从进入状态算起、租约封装绑定任务与修订、视频号头转发、迟到轮换不覆盖新导入、撤销只清理一次、密文不可解密）；broker HTTP 应用（签名租约、409、422、失败上报、未签名 401、扫描循环与就绪、缺少密钥拒绝启动）。
- 门禁：`ruff check`、`ruff format --check`、`mypy app`（606 文件）通过；`pytest` 2238 passed、4 skipped（原因同 S1）。
- 本机实测：`schema.sql` 在既有 `video` 库重复执行成功并新增 `consecutive_failures`；以真实进程启动 `python -m app.workers.session.broker_app`：`/health/live` 200、扫描本机数据库后 `/health/ready` 200、未签名租约 401、签名租约 409 `provider_session_not_ready`（尚无会话）。
- 未验收边界：没有真实浏览器，AC-05／AC-06／AC-09 的端到端部分待 S4、S5。

### S4（2026-09-28）

- 实现：`app/workers/session/browser.py`（Playwright 持久化上下文、登录判定、主框架导航拦截、确定性导出、元宝脚本）与 `browser_app.py`；后端 Dockerfile `session-browser` 目标；`pyproject.toml` 依赖组 `browser`（dev 组包含它）；两份 Compose 增加 `session-broker`、`session-browser`、`session_net`、卷 `site_session_profiles`；`.env.example` 说明两个 HMAC 密钥。
- 契约测试同步：`test_compose_application_roles_share_the_selected_release_image` 允许唯一的 `session-browser` 目标使用独立镜像；`test_runtime_base_images_are_pinned_without_host_architecture_override` 允许阶段引用更早的构建阶段，外部基础镜像仍须 digest 固定。
- 测试：浏览器逻辑（Cookie 替换与字段映射、YouTube 探测、403／429、导航异常、Profile 缺失、其他站点按注册表判定、跨域 jar 拒绝、导航拦截四种情形、元宝头过滤、`forget`、导出过滤与排序）；broker 客户端 ↔ 浏览器服务契约（双向封装、头封装给 Runner、错误密钥、异常转 `unavailable`）。
- 门禁：`ruff check`、`ruff format --check`、`mypy app`（608 文件）通过；`pytest` 2249 passed、4 skipped（原因同 S1）；开发与生产 Compose `config --quiet` 通过。
- 本机实测：`docker build --target session-browser` 成功（2.77 GB）；`docker compose up -d --build --no-deps session-browser session-broker` 后两个容器 healthy；在 broker 容器内经签名 RPC 对真实 youtube.com 执行 `bootstrap`（无登录 Cookie）→ `logged_out`，4.0 s；`keepalive` → `logged_out`，4.2 s；未知 Profile → `profile_missing`；`forget` 后 → `profile_missing`。浏览器容器直连外网失败（`URLError`），经 egress-proxy 访问 YouTube 返回 200。
- 未验收边界：尚未用真实登录态导入（需部署者在本机 Terminal 执行一次 `seed import`）；AC-03 冷启动与 AC-11 视频号待 S5 路由接入后整体验收。

### S5＋S8（2026-09-28）

- 按用户要求（不做兼容、清理存在问题的代码）S5 与 S8 一次完成，S6、S7 状态页后续补齐；这段时间内会话路线使用默认出口。
- 删除：宿主来源链路（`provider_startup`、`provider_source_host`、`provider_cookie_*` 八个模块、`provider_authorization_queue`、`managed_chrome_cdp`、`yuanbao_session`、`provider_session_setup`／`source_replica`／`session_source`／`session_maintainer`／`session_bundle`／`session_policy`）；授权事务 API、服务、仓储、ORM、前端对话框与 `lib/provider-authorization.ts`；`provider-sources` 服务与全部单平台账号 Runner；`provider_session_sources`、`provider_authorizations` 两张表（`DROP TABLE IF EXISTS`，已应用到本机库）；`RUNNER_OPERATOR_BASE_URLS`、`RUNNER_DEFAULT_ACCESS_POLICIES`、`PROVIDER_AUTHORIZATION_QUEUE_ROOT`、`PROVIDER_SOURCE_ENCRYPTION_KEY`、`*_ATTESTED` 等配置；运行手册 002、003、008 与设计 043。
- 新增：`app/workers/runner/site_sessions.py`（broker 客户端：就绪修订、单任务封装租约、失败上报）；Runner `provider_sessions.py` 改为按站点冻结 `{site}:{seed_revision}`、每次操作领取租约写入 tmpfs；两份 Compose 中唯一的 `session-runner`；API `SESSION_RUNNER_BASE_URL`；错误码 `provider_session_not_ready`（503）贯通后端、OpenAPI 与前端文案；运行手册 `docs/operations/011-站点会话运行手册.md`。
- 端到端修正：①Runner 命令构建原先要求平台目录声明账号模式才允许携带 Cookie，会拒绝未适配站点（AC-08）；改为匿名 Runner 一律拒绝，会话与访客 Runner 由上下文准入。②`POST /internal/v1/context` 原先只带平台键，未适配站点统一为 `generic` 后无法得到站点；改为携带 URL，下载 Worker 复验上下文时同样传 URL。
- 门禁：后端 `ruff check`、`ruff format --check`、`mypy`（585 文件）通过，`pytest` 2054 passed、3 skipped；前端 `format:check`、`lint`、`test`（505）、`build` 通过；两份 Compose `config --quiet` 通过。
- 本机实测：`docker compose up -d --build --wait` 起全部服务，健康检查全部通过，旧容器已移除，只剩 `site_sessions` 一张会话表。用 `import_session` 为 `example.com` 写入测试会话，broker 与真实浏览器 15 s 内推进到 `ready`；在 `video-api` 容器内解析 `https://example.com/` 被强制路由为 `operator_public`，请求到达 `session-runner` 并以会话 Cookie 运行 yt-dlp（该页无视频，yt-dlp 返回不支持，属预期）；无会话的 YouTube 走匿名路线解析成功。测试会话已撤销。
- 未验收边界：真实登录态导入与冷启动（AC-01、AC-03、AC-11）待部署者在本机终端 App 执行 `seed import`（S9）；出口一致（AC-10）待 S6；状态页（AC-06 展示部分）待 S7。

### L1（2026-09-28）

- 实现：`app/workers/session/login.py`（`RemoteLogins`：临时 Profile、每站点一个与全局两个登录、空闲 5 min 取消、仅 `https` 顶层导航、登录判定后导出并原子替换站点 Profile、启动时清理遗留临时 Profile）；`browser.py` 公开 `launch_profile`、`logged_in`、`export_jar` 并新增 `adopt_profile`；`contracts.py` 登录契约（`LoginAction` 按种类严格校验字段与视口坐标）；`browser_app.py` 五个登录接口与定时清理；`browser_client.py` 登录方法与 `LoginRejected`。
- 测试：`tests/unit/workers/session/test_login.py`（临时 Profile 与替换、未登录不能保存且旧 Profile 不变、操作顺序、并发限制、起始链接校验、空闲取消、启动失败清理、导航拦截、遗留清理、动作字段校验）；`test_browser_app.py` 增加登录契约（jar 封装给 broker、409／404 映射）。
- 门禁：`ruff`、`mypy`（586 文件）通过；`pytest` 2064 passed、3 skipped。
- 本机实测：重建 `session-browser` 后在容器内启动元宝登录 0.9 s，画面为微信扫码登录弹窗（JPEG 30 KB），转发滚轮后取消，临时 Profile 已删除。

### L2（2026-09-28）

- broker：`save_login`（与浏览器共用 `app/workers/session/seeding.py` 的接受规则：站点 Cookie 域、未过期、至少一个持久 Cookie、满足注册表）与五个登录转发；管理员通道使用独立密钥 `SITE_SESSION_ADMIN_SECRET`，与 Runner 通道密钥相同时拒绝启动。浏览器在替换 Profile 前执行同一规则，页面看似已登录但没有持久登录 Cookie 时返回 `login_not_accepted`，旧 Profile 不变。
- API：`app/integrations/site_session_admin.py` 与 `app/api/routes/admin_site_sessions.py`（列表、开始、画面、输入、保存、放弃、撤销，全部仅管理员、`no-store`、不记录请求体）；新增 7 个 `site_session_*` 错误码；站点可为已知键、域名或任意 https 链接。
- 修正：注册表中抖音的 `ttwid` 与 Reddit 的 `loid` 是未登录访客也有的 Cookie，已从登录判定中移除；没有访客路线的平台遇到 “Fresh cookies are needed” 时返回 `provider_session_not_ready`，不再误报“访客环境准备中”（视频号截图问题）。
- 删除：`seed.py`、`chrome_reader.py` 及其测试；`provider-sources` 服务角色、`provider_source_encryption_key`、`provider_source_poll_seconds`／`lease_seconds`。
- 部署：两份 Compose 为 broker 与 API 注入 `SITE_SESSION_ADMIN_SECRET`（生产必填），API 增加 `SITE_SESSION_BROKER_URL`；契约测试断言只有 API 与 broker 持有该密钥。运行手册 011、README、AGENTS 与相关设计改为管理页面登录。
- 门禁：`ruff`、`mypy`（588 文件）通过；`pytest` 2041 passed、3 skipped（删除导入命令测试后数量下降）。
- 本机实测：重建全部服务后，在 `video-api` 容器内经真实 broker 与浏览器：列表返回全部已知平台；开始视频号登录 1.2 s；画面主机 `yuanbao.tencent.com`；未登录时保存返回 `site_session_login_incomplete`；`10.0.0.1` 返回 `site_session_invalid`。

