# 046 容器自持平台会话 Plan

日期：2026-09-28。状态：已评审（2026-09-28），S1、S2 代码完成待验收，其余未开始。需求见 [PRD](../prd/046-容器自持平台会话PRD.md)，技术方案见 [Design](../design/046-容器自持平台会话设计.md)。**任务状态、证据只在本文维护。**

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

- [ ] **S2**；状态：代码完成待验收；依赖：S1。
  - 需求：FR-01、FR-10；NFR-03、NFR-05。
  - 步骤：
    1. 把 `chrome_provider_cookies.py` 迁为 `app/workers/session/chrome_reader.py`（原位置删除，旧宿主链路改为从新位置导入，直到 S8 删除）；增加 Profile 列表与钥匙串拒绝识别。
    2. 实现 `python -m app.workers.session.seed`，子命令 `import`、`status`、`revoke`；Profile 自动选择规则见 Design §6.1。
    3. 条件写入、撤销墓碑、`revoked → seeded` 重新导入；输出只含计数和修订。
  - 验收：PRD AC-01、AC-07（导入与撤销部分）；用临时 Chrome 目录夹具覆盖单／多／无 Profile；日志扫描无 Cookie 值。

<a id="s3"></a>

### S3 session-broker

- [ ] **S3**；状态：未开始；依赖：S1。
  - 需求：FR-03、FR-05、FR-06；NFR-02、NFR-06。
  - 步骤：
    1. 把 `provider-sources` 服务改造为 `app/workers/session/broker.py`：15 s 扫描、状态机（Design §5）、条件写入。
    2. 浏览器 RPC（`session_net`）：`bootstrap`、`report`、`publish_jar`，jar 用 X25519 临时密钥封装。
    3. Runner RPC（`runner_rpc_net`，HMAC）：`lease`、`report_failure`；租约算法从 `provider_cookie_lease.py` 迁入 `lease.py`，AAD 绑定任务与站点。
    4. `reseed_required` 转换时经管理员通知通道发出一次告警。
  - 验收：PRD AC-05（broker 停止部分）、AC-06、AC-09；状态机和租约的单元测试；并发导入与迟到保活的竞争测试。

<a id="s4"></a>

### S4 session-browser 容器

- [ ] **S4**；状态：未开始；依赖：S3。
  - 需求：FR-03、FR-07、FR-08；NFR-02、NFR-04、NFR-06。
  - 步骤：
    1. 新增镜像：固定 digest 的 Chromium，非 root、只读根、`cap_drop: ALL`、Profile 卷 `site_session_profiles`。
    2. `app/workers/session/browser.py`：每站点 Profile、按站点代理、`Network.setCookies`／`getCookies`、`login_probe`、`Fetch` 顶层导航拦截、30 min ± 5 min 保活、2 个并发站点任务、60 s 超时。
    3. 注册表中各平台的 `login_probe`（YouTube `ytcfg.LOGGED_IN`，其他平台以真实页面确定后写入注册表）。
    4. 视频号 `yuanbao` 头插件：把 `yuanbao_session.py` 的读取逻辑迁入浏览器，删除宿主版本。
    5. 浏览器崩溃恢复：从磁盘 Profile 重启；Profile 缺失时由 broker 重新 bootstrap。
  - 验收：受控测试站点上的 bootstrap、轮换回写、导航拦截、崩溃恢复集成测试；PRD AC-10 的浏览器出口部分。

<a id="s5"></a>

### S5 会话路由与 session-runner

- [ ] **S5**；状态：未开始；依赖：S3。与 S6–S8 同一发布。
  - 需求：FR-04、FR-06；NFR-01、NFR-06。
  - 步骤：
    1. `SiteRouteResolver` 接入 API inspect 与下载 Worker；新增 `ProviderAccessPolicy.SITE_SESSION`，删除 `OPERATOR_PUBLIC`；`PERSONAL_ENTITLED` 改由注册表 `entitlement` 表达。
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

- [ ] **S7**；状态：未开始；依赖：S5。
  - 需求：FR-05、FR-09。
  - 步骤：删除 `/api/providers/{key}/authorization*`、`ProviderAuthorizationService`、前端授权对话框和 `lib/provider-authorization.ts`；状态接口与页面改为展示 Design §7 字段和导入命令；按 `design.md` 实现，桌面与 390px 真实浏览器验证。
  - 验收：PRD AC-06（展示部分）、AC-12（API／前端部分）；前端 `format:check`、`lint`、`test`、`build`。

<a id="s8"></a>

### S8 删除旧链路与文档

- [ ] **S8**；状态：未开始；依赖：S5、S6、S7。
  - 需求：FR-09。
  - 步骤：
    1. 按 Design §8 删除模块、类型、Compose 服务与卷、配置键、测试；`schema.sql` 删除 `provider_session_sources`、`provider_authorizations`（`DROP TABLE IF EXISTS`）及其 ORM；删除 `provider_session_policy.py` 中与站点会话注册表重复的 Cookie 校验；开发与生产 Compose 同步。
    2. 新增运行手册 `docs/operations/009-站点会话运行手册.md`（导入、状态、撤销、换机、告警处理）；删除 002、003、008 中宿主来源内容；043 标为已被 046 取代并删除正文；044 PRD 的 FR-17／AC-21 改为指向 046，044 Plan 同步追溯表。
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

