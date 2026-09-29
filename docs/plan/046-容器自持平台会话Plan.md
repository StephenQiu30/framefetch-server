# 046 容器自持平台会话 Plan

日期：2026-09-29。状态：固定公开接口／站点会话路线及自动接入已实现；当前 18/23 平台取得完整下载证据，全平台无感冷启动未验收；7 天观察未完成。需求见 [PRD](../prd/046-容器自持平台会话PRD.md)，技术方案见 [Design](../design/046-容器自持平台会话设计.md)。**任务状态、证据只在本文维护。**

工作方式沿用 [044 Plan §1](044-开源部署无感解析Plan.md#1-sdd-工作方式)：先写能判定的测试，再实现最小闭环；代码完成不等于平台实测完成；只有“已验收”才勾选。

## 1. 原始审查基线（历史，非当前运行状态）

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

- [ ] **S2**；状态：代码完成待验收；依赖：S1。
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

- [ ] **S6**；状态：配置实现完成，三方实际出口待验收；依赖：S4、S5。
  - 需求：FR-07。
  - 步骤：复用唯一 `RUNNER_PROVIDER_EGRESS_PROXIES` 映射；浏览器、Runner、bgutil 使用相同平台代理，路由改变时配套重建。
  - 验收：PRD AC-10，三方出口 IP 一致的日志证据。

<a id="s7"></a>

### S7 管理员状态页与删除授权事务

- [ ] **S7**；状态：删除授权事务已完成（随 S8），站点会话状态接口与页面已实现，真实浏览器验收见下方；依赖：S5。
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
| FR-01 | S2 |
| FR-02 | S1 |
| FR-03 | S3、S4 |
| FR-04 | S1、S5 |
| FR-05 | S3、S7 |
| FR-06 | S3、S5 |
| FR-07 | S4、S6 |
| FR-08 | S4 |
| FR-09 | S7、S8 |
| FR-10 | S2 |
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

### 登录态来源决策（2026-09-28）

- 先后评估 Chrome 扩展同步与管理页面远程登录（提交 `fdfcbbc9`、`d57bf68d`、`73543525`、`c779d0a0`），用户决定不采用，并已为本机授予完全磁盘访问权限；上述提交整体回退，保留宿主 Chrome 一次性导入（S2）。
- 回退时保留与方案无关的修正：抖音 `ttwid`、Reddit `loid` 为访客 Cookie，已从登录判定移除；没有访客路线的平台遇到 “Fresh cookies are needed” 返回 `provider_session_not_ready`（视频号不再误报“访客环境准备中”）；删除未使用的 `PROVIDER_SOURCE_*` 配置。
- 门禁：`ruff`、`mypy`（585 文件）通过；`pytest` 2055 passed、3 skipped。

### 强制会话与冷启动修复（2026-09-28～29，本机验收）

本节是当前执行状态；前述 S1–S9 记录保留原执行时间与证据，不代表当前拓扑。

- S5／S8：在线匿名／访客路线及对应 Compose 服务已移除；路由、Canary 与可用性展示只使用会话，旧策略值不作为执行兼容入口。
- S3／S4：新增持久 `next_check_at`；broker／browser 重启后复验；正常维护 30～35 分钟，临时故障持久退避；403／429 不增加认证失败次数。维护与媒体共用站点锁；新导入清除旧 Profile 身份；Runner 轮换 Cookie 经封装回传、登录探针与修订条件写入后发布。
- S6：复用 `RUNNER_PROVIDER_EGRESS_PROXIES` 统一三方映射，变更时配套重建。三方实际出口 IP 证据仍需独立验收，不另建 SITE_EGRESS_ROUTES。
- S7：后台平台目录展示会话状态、最近验证、下次检查和恢复动作；OpenAPI 自动生成客户端已更新。
- S9：YouTube 21 个 Cookie、抖音 94 个 Cookie 成功导入，均修订 1；只记录计数，不记录秘密。真实媒体验收与 7 天观察分开。
- 当前 schema.sql 在既有数据库连续执行两次成功。生产拓扑以明确的测试占位密钥通过静态解析；本机 `.env.prod` 缺少两个会话 RPC Secret，未修改该文件，不能宣布生产已可部署。
- 同期媒体结果双栏布局改动由其他任务独立提交（`0ed9eba6`、`08b4c9be`）；本次不覆盖或重复纳入。
- 本次静态、单元／集成与真实浏览器验收结果如下；不将短时测试视为 7 天稳定性验收。


#### 本轮最终门禁与真实证据

- 后端：`ruff check app tests`、`ruff format --check app tests`、`mypy app`（585 文件）通过；最终 `pytest` **2056 passed，3 skipped**。跳过项分别缺少 download-role URL、TEST_RABBITMQ_URL、隔离 MinIO endpoint，不把业务任务成功等同于这些测试已运行。
- 前端：`pnpm format:check`、`pnpm lint`（含 typecheck）、`pnpm test` **507 passed**、`pnpm build` 通过。测试日志有一次未导致失败的 `ECONNRESET`，不描述成零告警。OpenAPI 客户端从 schema 生成。
- 部署：新后端、浏览器镜像构建成功；已有库幂等 SQL 连续两次成功；现有基础设施未重建，环境文件未修改。统一重建 API、下载 Worker、Canary、session-runner、broker、browser；在线匿名／guest 容器已停用并删除。
- 使用 `agent-browser` 通过真实 Web 登录、粘贴地址、选择格式、创建下载、保存文件和播放。前三个样本保存文件的 SHA-256／大小与 PostgreSQL artifact 一致，ffprobe 检出 H.264＋AAC。实际使用已有 RabbitMQ／Worker／MinIO 链路。

| 样本 | 下载任务 | 文件字节 | 时长 | SHA-256 |
| --- | --- | ---: | ---: | --- |
| YouTube `jNQXAC9IVRw` | `6c22ab78-8b50-4578-9435-2236620b6e52` | 632006 | 18.948 s | `1c335af874a305f810d2b0d6634c8e36a0b538578010bc5b49e50fc91d95ab2a` |
| 抖音 `7674644830270473609` | `e704c43f-3967-4f10-8a2f-417b41cdca1a` | 2991195 | 14.070 s | `b495811a95bddf1332cf3327198016f6f485b691539819c7fb7256870a1d00fc` |
| 用户原 YouTube `BWst4tIkNdc`（720P） | `b560bb83-790b-4962-a8ce-a648b3b07b18` | 39859405 | 169.437 s | `2f3c0ae0ed9fc53a1396e746681d396c2911521acd954a7d235ed594b9fdf641` |

- 真实测试修复了两处遗漏：①抖音提取成功后会新增 `aweme.snssdk.com` 的响应 Cookie，轮换回写现在丢弃域外项，严格拒绝损坏、空或非白名单输入；不再把合法提取结果误判成登录失效。②context RPC 尚未接单时的会话未就绪异常现在保留 `before_media_io`，准备等待不会消耗媒体尝试次数。两项均有回归测试。
- 冷启动：整组服务重建后，持久登录态恢复，无需再导入。另停止 session-browser 约 40 秒后重启，原解析意图 `351490d6-ea72-4bc8-840d-0bd29ffee75d` 在等待阶段 `attempt=0`，恢复到 `ready` 后 `attempt=1`；`fence=5` 表明经历多轮领取。仍为同一意图，111.38 秒内交接到任务 `7d40cc9f-ba5f-4ed7-95f2-19fa6ef82693`，包含人工点击耗时，不能当成纯启动耗时。
- 冷启动后文件验证：任务 `7d40cc9f-ba5f-4ed7-95f2-19fa6ef82693` 成功，632006 字节、18.948 秒，SHA-256 与首次 YouTube 样本一致；浏览器播放成功。共 4 次真实下载、3 个不同视频。隔离 QA 账号已停用、认证会话已撤销、临时密码文件已删除。
- 缺失会话：Instagram `DbKfjdhTMAY` 返回 `provider_configuration_missing`，页面明确要求管理员导入；无匿名请求回退。
- 状态页：1440px 与 390px、浅／深色真实浏览器检查通过；390px 页面 `scrollWidth=innerWidth=390`，宽表在容器内滚动。浏览器未记录未捕获脚本异常。
- 本机证据目录 `/tmp/framefetch-session-qa/`：媒体哈希清单、冷启动前后状态、页面截图。首次文件下载被测试浏览器取消，配置 `--download-path` 后同一业务按钮保存成功，未修改文件交付业务代码。录制缩放时测试浏览器出现截图异常，重启隔离测试浏览器后重拍；不将损坏录像用作验收依据。

#### 仍未关闭的验收

1. 真实覆盖为 YouTube 两个不同视频、抖音一个视频及重复冷启动样本；尚不满足两平台各三个不同样本的完整矩阵。
2. 未完成 7 天无人值守观察、三方实际出口 IP 的独立比对、视频号与其他平台真实登录／媒体矩阵。只有 Cookie 保留而没有真实登录探针的平台不会标为 ready；需要逐平台补充探针与样本。
3. 本机生产环境文件缺少会话 RPC Secret，生产发布未执行。静态占位密钥校验不等同于生产配置完成。
4. 平台强制退出、验证码或账号验证仍需部署者处理；自动保活与轮换不能保证账号永久有效。

### 启动自动接入与后台重新获取（2026-09-29）

按用户最新要求，宿主从手工 seed import 改为项目启动自动获取；正常维护仍由容器持有，不恢复旧宿主来源 TTL 或匿名回退。实现已完成，本机后台获取的真实验收仍有系统授权前提，不能宣称全自动闭环已验收。

- 根 `./start` 是 macOS 统一入口：加载现有配置、幂等应用当前 SQL、自动接入、安装当前用户 LaunchAgent、构建并启动 Compose、通过 broker 签名 RPC 确认平台准入。
- 默认自动接入 YouTube、抖音。缺失或 reseed_required 才读取 Chrome，正常状态不覆盖；来源 Profile 与认证材料 HMAC 指纹随种子原子持久化。相同失效材料不循环重导，已撤销会话不自动复活；并发撤销、健康恢复与新修订均阻止迟到写入。
- 后台每 60 秒执行一轮；每站点独立子进程最多 60 秒，超时终止进程组。每次项目启动额外发起带请求号的真实后台权限检查，旧报告不能替代本次检查。后台不可读时启动返回 2，保留已启动且可用的服务。
- 自动获取首期仅支持 macOS 已登录的 Chrome；多 Profile 歧义需一次指定。平台扫码／验证码和系统授权仍需人完成。Linux 纯容器启动只能恢复已有部署会话。

#### 本轮验证

- 后端 Ruff、格式检查、mypy（587 文件）通过；完整 pytest **2067 passed，3 skipped**。跳过项仍是独立 download-role URL、RabbitMQ 测试地址与隔离 MinIO endpoint。旧的启动文档契约曾因入口改变失败，已改为验证 `./start` 并通过完整重跑。
- 前端格式、lint／typecheck、**507 项测试**和构建通过；最新文案通过容器镜像构建并部署。两份 Compose 静态解析通过，生产仍使用检查专用占位 RPC Secret，未修改实际 `.env.prod`。
- 唯一当前态 SQL 在已有项目库连续执行两次；隔离 schema 的完整 SQL 重复执行测试通过。未创建新的基础设施服务，未覆盖环境文件。
- 真实 Chrome＋现有 PostgreSQL 的隔离 schema：YouTube、抖音从无会话自动得到 `imported_pending_verification`；再次扫描保持 seeded；将该隔离记录设为失效后返回 `awaiting_new_login`，修订保持 1。隔离 schema 已清理，未覆盖业务账号会话。
- LaunchAgent 已安装并实际运行多轮，退出码 0；部署会话修订未被后台覆盖。真实后台读取 Chrome 返回 `chrome_permission_required`，而交互环境能够读取，证明两者权限不同。已向用户说明后台解释器的完全磁盘访问授权；授权完成前，失效后的自动重新获取不算通过。启动入口如实返回 2，不能用当前 ready 掩盖这个缺口。
- 通过 `./start` 实际重建服务后，broker 的当前运行期 RPC 返回 YouTube、抖音 ready；没有手工重新导入。后台权限不影响容器对已有会话的恢复与维护。
- 使用 agent-browser 真实登录、解析、创建任务、保存和播放：YouTube 任务 `282fb5e5-5e04-47fc-ad61-5bbdcf967977`（632006 字节，18.948 秒）及抖音任务 `df0e20c9-a77e-4a1a-bcc1-bd5e71215ccb`（2991195 字节，14.070 秒）成功。浏览器保存文件的 SHA-256、大小均匹配当前数据库 artifact，ffprobe 确认 H.264＋AAC，复用真实队列／Worker／MinIO 链路。
- 管理页更新自动同步与主动撤销提示；1440px／390px 浏览器检查通过，390px 页面宽度与视口均为 390，宽表在容器中滚动；检查未记录未捕获脚本异常。临时 QA 管理员停用，Web／认证会话与临时密码文件已删除，测试浏览器已关闭。
- 本机证据：`/tmp/framefetch-auto-source-qa/` 的真实来源、媒体与 artifact 清单和截图；`/tmp/framefetch-auto-source-tests-final.log`；`/tmp/framefetch-auto-start-final.log`；`/tmp/framefetch-auto-source-access-final.log`。临时权限探针 LaunchAgent 已卸载，产品自动接入服务保留。

待完成：后台解释器授权后的真实重新获取复验；真实宿主重启与七天无人值守观察；其余平台登录探针／媒体矩阵。前一轮列出的生产配置与三方实际出口验收缺口仍未关闭。

### 全平台注册范围与无感冷启动验收（2026-09-29）

**结论：未通过。** 本轮基线 `feadd5a7`，只进行真实浏览器验收及证据／运行手册更新，没有修改产品代码，没有增加兼容或匿名路线。使用 agent-browser 从 Web 登录、单次提交链接、选择默认格式、创建下载到保存与播放；没有用 API 调用替代产品操作。

平台状态页共 24 项，其中 23 项显示“下载解析器已部署”，微信公众号文章显示“已登记，暂无解析器”。23 项分别执行暖启动和业务容器全部停止后的首轮请求，共 **46 次矩阵用例**；另执行 1 次会话服务停机期间提交后自动恢复用例。当前固定 Canary 只覆盖 9 项，其余 14 项使用 `04ddbb5f` 之前的样本进行入口准入诊断：这些失败发生在会话准入阶段，不能推断其当前上游内容有效性、提取器质量或完整媒体可用性。固定矩阵缺失本身仍是验收缺口。

| 平台 | 样本来源 | 暖启动 | 容器冷启动后 | 当前阻断／结果 |
| --- | --- | --- | --- | --- |
| YouTube | 当前固定 | 解析通过，下载失败 | 解析／文件／播放通过 | 暖启动下载进入终态，未自动恢复 |
| 哔哩哔哩 | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| 抖音 | 当前固定 | 解析／文件／播放通过 | 解析／文件／播放通过 | 两个阶段均取得真实文件 |
| TikTok | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| 小红书 | 当前固定 | 准入失败 | 准入失败 | 无可用部署会话 |
| 快手 | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| Vimeo | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| X / Twitter | 当前固定 | 准入失败 | 准入失败 | 无可用部署会话 |
| Instagram | 当前固定 | 准入失败 | 准入失败 | 无可用部署会话 |
| Facebook | 当前固定 | 准入失败 | 准入失败 | 无可用部署会话 |
| Twitch | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| Reddit | 当前固定 | 准入失败 | 准入失败 | 无可用部署会话 |
| Pinterest | 当前固定 | 准入失败 | 准入失败 | 无可用部署会话 |
| 微博 | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| 优酷 | 历史入口诊断 | 准入失败 | 准入失败 | 无可用部署会话 |
| 腾讯视频 | 历史入口诊断 | 准入失败 | 准入失败 | 无可用部署会话 |
| 微信公众号文章 | — | 暂无解析器 | 暂无解析器 | 仅登记，不计入 23 项媒体矩阵 |
| 微信视频号 | 当前固定 | 准入失败 | 准入失败 | 无可用部署会话 |
| Snapchat Spotlight | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| LinkedIn | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| Telegram | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| Kick | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| Tumblr | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |
| 红果短剧官方分享 | 历史入口诊断 | 准入失败 | 准入失败 | 尚未接入可验证会话 |

#### 冷启动与无感恢复证据

- 完整停机前确认没有执行中的下载／解析意图／导入任务；执行业务 Compose `stop` 后通过 `./start --no-build` 恢复。复用原有 PostgreSQL、RabbitMQ、Redis、MinIO 和持久卷，不清除会话、不手工导入。停机开始至启动校验结束约 **60.57 s**（包含停机、启动与检查，不是纯服务启动耗时）。YouTube、抖音当前运行期 broker RPC 均返回 ready，seed_revision 均保持 1。
- 启动最终返回 **2**：后台真实 Chrome 获取仍报告 `chrome_permission_required`。现有部署会话恢复成功不等于空会话首次接入或失效重新获取成功；这个缺口未关闭。
- 冷启动后首轮 YouTube 完整流程 **30.49 s**，抖音 **13.68 s**；其余 21 项仍准入失败，重启没有解决其接入缺失。
- 额外停止 session-broker 与 session-browser，API 保持运行；只提交一次 YouTube 请求。意图 `3e2360a6-06d2-4b49-a51e-b4834e6411cf` 在服务停止时为 `retry_wait`、`attempt=0`、`fence=2`。恢复服务后同一意图自动变为 `handed_off`、`attempt=1`、`fence=4`，交接任务 `64aaaa08-53ee-4828-85ca-5c3bf9e4336d`；浏览器正常选择格式、创建下载并保存播放，全程 **98.66 s**，没有重新提交解析。这证明已有会话下等待中的解析可以自动继续；不代表已失败的下载也会恢复。
- 暖启动 YouTube 元数据 13.07 s 成功，下载任务 `86cdf49c-ea75-4f8e-b483-4b73835efa2f` 在整个流程 110.83 s 时确认为 `failed`、attempt=2、`provider_session_not_ready`。当时会话为 degraded，最近原因 `browser_unavailable`；浏览器不可用的深层原因尚未定位。全部容器冷启动后该原任务仍是 failed，没有自动恢复。页面却同时显示“下载失败／重新下载”与“本次任务会在等待期限内自动继续”，构成明确的状态文案与实际行为冲突。

#### 真实文件与测试收尾

四次成功交付均由浏览器保存文件，SHA-256 与文件大小匹配 PostgreSQL Artifact，ffprobe 确认 H.264＋AAC，播放器 currentTime 前进且非 paused。没有把元数据解析或 HTTP 200 计为下载成功。

| 阶段／平台 | 下载任务 | 字节 | 时长 | SHA-256 |
| --- | --- | ---: | ---: | --- |
| warm／douyin | `c389514c-d922-41b4-b1bb-6630fbd59f9a` | 2991195 | 14.070 s | `b495811a95bddf1332cf3327198016f6f485b691539819c7fb7256870a1d00fc` |
| cold／youtube | `5e10cf2e-4f3e-4921-a800-4c6897d5959b` | 632006 | 18.948 s | `1c335af874a305f810d2b0d6634c8e36a0b538578010bc5b49e50fc91d95ab2a` |
| cold／douyin | `5af59aba-0b35-4b8c-92dc-0a076f54fdcb` | 2991195 | 14.070 s | `b495811a95bddf1332cf3327198016f6f485b691539819c7fb7256870a1d00fc` |
| recovery／youtube | `64aaaa08-53ee-4828-85ca-5c3bf9e4336d` | 632006 | 18.948 s | `1c335af874a305f810d2b0d6634c8e36a0b538578010bc5b49e50fc91d95ab2a` |

- 测试结束时业务服务均 running，有健康检查的服务均 healthy；浏览器未记录未捕获脚本异常。QA 账号停用、认证及 Web 会话撤销、临时密码文件删除，隔离浏览器关闭。保留测试任务和媒体证据，不删除业务数据。
- 原始证据保存在本机 `/tmp/framefetch-all-platform-qa/`：`warm-results.json`、`cold-results.json`、`recovery-results.json`、`artifact-evidence.json`、`cold-start-evidence.json`、`recovery-before.json`、`recovery-after.json`、`session-final.json`、`screenshots/` 与两份可解码 WebM 录像。该目录是临时本机证据，不承诺跨机器或清理后保留；本节是入库的脱敏验收结论。
- 本轮仅文档修改，执行文档差异和证据计数检查；没有重新运行前述完整单元测试，不能将历史绿灯计作本轮结果。

#### 未关闭问题与后续验收门禁

| 优先级 | 问题与影响 | 最小处理方向 | 必须补充的回归证据 |
| --- | --- | --- | --- |
| P0 | 21 个声明已部署的解析器无法通过会话准入 | 逐平台补齐会话获取、真实身份探针与 Runner 准入；平台状态页分别显示解析器安装状态和部署实际可用状态 | 每个平台有效固定样本、完整文件保存播放、冷启动首次请求；缺少任一项保持未验收 |
| P0 | 后台 Chrome 读取权限未满足，缺失或过期后无法完成自动重新获取 | 完成实际后台解释器系统授权并复验；持续如实暴露来源故障，避免只看容器 ready | 无会话首次自动获取、旧登录失效后新材料自动导入、无人手工执行 seed import |
| P1 | YouTube 下载因会话暂不可用进入终态，页面仍承诺自动继续 | 定位 browser_unavailable；统一解析与下载的有限等待及终态语义，终态不显示自动恢复承诺 | 下载进行中中断会话服务，同一任务自动恢复或在截止后准确终止；不能以新建任务成功代替 |
| P1 | 固定 Canary 仅 9 项，14 项没有现行样本覆盖 | 为实际承诺的平台补齐可维护的固定矩阵 | 平台目录与矩阵集合一致，并逐项保存真实结果 |

未执行真实宿主重启、空部署全平台接入、全部平台各三个不同视频或 7 天无人值守观察；本轮不能证明长期稳定，也不能宣称全平台无感冷启动已完成。前文生产配置与出口独立验收缺口继续保留。

### 其余平台下载接入与固定公开路线（2026-09-29）

**验收结论：部分通过，全平台无感冷启动仍未通过。** 用户批准“允许平台原生公开接口，禁止失败后匿名降级”，并再次确认“严格报告未就绪，核心服务继续运行”。本轮从 `6b0a1a10` 开始，期间保留其他任务的前端提交与租约／broker 并行修改；后者不属于本轮路由修改的独立完成证明。

#### 实现与合同

- FR-04／AC-05：12 个平台在任何请求前固定选择原生公开路线，其他 11 个平台使用真实身份验证后的站点会话；共用 session-runner，不新增服务、兼容分支或失败后匿名兜底。API、Runner、Canary、状态页使用同一固定策略；公开操作不领取账号租约。
- FR-01／FR-03：默认自动接入扩展为全部 11 个会话站点；新增第一方身份断言，Cookie 存在不是 ready。小红书只将 web_session 作为候选认证材料；腾讯视频来源及下载器统一读取当前 v_vuserid／v_vusession 等字段，缺失时不发送匿名请求。
- X 实测返回的视频／音频格式缺少 codec 信息，认证线路此前跳过了媒体探测，导致 format_unavailable；现在允许有界探测对应媒体，不把 Cookie 传给 CDN。回归测试和真实文件均通过。
- 固定矩阵扩展为 23 平台、46 个 metadata／media 目标；启动公开探测最多 3 路并发。红果原短分享页返回空 pageData，保留失败证据，固定样本更新为同一集的官方播放器；这不是解析失败后的自动回退，原短链仍未验收。
- 启动先提供核心业务服务，再自动获取／验证平台。来源最多 3 个子进程并发，单进程最多 60 秒，整轮共享 90 秒截止时间；前台启动不消费后台权限请求，只有 LaunchAgent supervise 写后台检查结果。任一启用站点、公开探测或后台权限未就绪均返回非零，核心容器保留运行。

#### 真实浏览器矩阵

通过 agent-browser 执行 Web 登录、单次粘贴、解析、选择格式、创建下载、保存文件、ffprobe 和播放；没有通过直接业务 API 创建下载替代浏览器操作。首轮 21 项中 **12 项完整文件／播放通过，2 项已有文件但点击播放被遮挡，7 项解析失败**。随后完整业务容器停止并重启，23 项首轮业务请求中 **17 项文件／播放通过、6 项解析失败**；红果同集官方播放器单独补测通过。因此取得完整下载证据的平台为 **18/23**，其中相对 YouTube／抖音增加 **16/21**；不能宣称余下全部已完成。

| 平台 | 首轮 | 首次业务容器冷启动后 | 限定结论 |
| --- | --- | --- | --- |
| YouTube | 本轮未执行 | 文件／播放通过 | 当前固定单视频通过 |
| 抖音 | 本轮未执行 | 文件／播放通过 | 当前固定单视频通过 |
| 小红书 | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| 微信视频号 | 解析失败 | 解析失败 | 未取得元宝有效登录材料 |
| X / Twitter | 解析失败 | 文件／播放通过 | 补齐缺失音轨信息后通过 |
| Instagram | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| Facebook | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| Reddit | 解析失败 | 解析失败 | 第一方访问 HTTP 403，身份验证未通过 |
| Pinterest | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| 哔哩哔哩 | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| TikTok | 解析失败 | 解析失败 | 原生播放器接口 HTTP 403 |
| 快手 | 制品成功，浏览器播放点击被遮挡 | 文件／播放通过 | 滚动至播放器后补测通过 |
| Vimeo | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| Twitch | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| 微博 | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| 优酷 | 解析失败 | 解析失败 | 未取得有效登录材料 |
| 腾讯视频 | 解析失败 | 解析失败 | 第一方 SDK 身份未知，不能凭 Cookie 放行 |
| Snapchat | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| LinkedIn | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| Telegram | 制品成功，浏览器播放点击被遮挡 | 文件／播放通过 | 滚动至播放器后补测通过 |
| Kick | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| Tumblr | 文件／播放通过 | 文件／播放通过 | 当前固定单视频通过 |
| 红果官方入口 | 解析失败 | 解析失败 | 原短链数据为空；同集官方播放器补测文件／播放通过 |

#### 冷启动与证据边界

- 首次完整停止／启动在扩展后的串行来源检查实现上耗时 871.21 s（包含 stop、up、来源、会话及公开探测），最终返回 2。公开平台第一轮 12 项探测失败，稍后同路线复测 10 项成功，TikTok 与旧红果短链失败；首次集中失败原因尚不能确定，不以复测覆盖失败。随后修复来源串行等待和前台消费后台权限请求的问题，再次完整停止／启动验证。
- 全量浏览器流程前曾遇到 FrameFetch 需要重新登录，先记录 cold-before-signin 的测试中止，再通过正常登录继续；这 23 次没有提交平台请求的中止不计作平台解析失败。
- 冷启动保留既有数据库和会话卷，没有手工 seed import、删除会话或清空业务数据。无会话首次接入、真实登出后重新获取、真实宿主重启与 7 天无人值守没有全部通过。
- 当前外部阻断：后台 Python 的 Chrome 读取权限仍未满足；优酷／元宝缺少有效登录材料；腾讯视频第一方页面身份保持未知；Reddit、TikTok 当前出口被拒绝。没有绕过验证码、权限或将未知身份标记为成功。
- 技术检查：完整后端 2130 passed、3 skipped；跳过项分别为独立 download-role URL、TEST_RABBITMQ_URL 和隔离 MinIO endpoint 未提供。Ruff、格式、mypy（588 个源文件）通过。业务 Compose 解析、镜像构建通过；以本机 .env 验证生产 Compose 时缺少 SITE_URL／站点内部 RPC 必填密钥，生产部署不计通过。本轮没有修改前端 API 契约或重跑前端套件，也没有远端 CI 证明。
- 原始脱敏测试清单、截图与下载证据位于本机 `/tmp/framefetch-platform-support-qa/`；文件大小／SHA-256 与数据库 Artifact 逐项核对。该目录为临时本机证据，不承诺跨机器保留。

#### 最新重启补测与清理

- 来源检查改为有界并发、启动顺序调整后，再次完整 stop／start：从开始停止到核心 API ready 为 **43.96 s**（其中 stop 36.61 s）。启动后最早的哔哩哔哩、Vimeo、微博原生媒体探测均返回成功。
- 该次完整启动验收被共享部署的另一轮服务重建中断：broker 验证子进程退出 137，随后 Compose 报 provider-canary 未运行，命令最终返回 137、共 208.97 s。服务的 StartedAt 在验收期间再次改变；该次不能计为完整冷启动通过，也不能把中断归因于上游平台。原始记录为 cold2-evidence.json／cold2-start.log／cold2-first-egress.json。
- 服务恢复后，同路线公开 metadata 最终 **11/12** 成功，只有 TikTok 未通过；YouTube、X、哔哩哔哩、红果官方播放器再次通过完整浏览器下载和播放，耗时分别为 **26.42／35.74／18.26／17.45 s**。这 4 项为重建后的定向回归，不替代完整 23 项的第二轮冷启动验收。
- 最终 **36 份浏览器保存文件**（包含重复回归）均与数据库 Artifact 的大小和 SHA-256 一致。各任务 UUID、哈希与时长保存在 artifact-evidence.json；两次首轮播放点击遮挡不计入完整通过数。
- 最终已验证会话为 YouTube、抖音、小红书、X、Instagram、Facebook、Pinterest；腾讯视频进入 reseed_required，Reddit degraded，优酷／视频号没有可用会话。后台权限检查仍为 chrome_permission_required。
- QA 账号已停用，认证及 Web 会话已撤销，临时密码文件已删除，两个隔离 agent-browser 会话已关闭；测试任务与媒体证据保留，没有删除其他业务数据。完整无并行重建干扰的最终冷启动、缺失／失效会话的后台重新获取仍是未关闭门禁。
