# 046 容器自持平台会话 Plan

日期：2026-09-28。状态：待评审，全部任务未开始。需求见 [PRD](../prd/046-容器自持平台会话PRD.md)，技术方案见 [Design](../design/046-容器自持平台会话设计.md)。**任务状态、证据只在本文维护。**

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

- [ ] **S1**；状态：未开始；依赖：无。
  - 需求：FR-02、FR-04（非秘密读取）；NFR-03。
  - 步骤：
    1. 引入固定版本的 PSL 库（优先 `tldextract` 离线快照，或 `publicsuffix2`），实现 `SiteResolver`，拒绝 IP、私网、`localhost` 和公共后缀。
    2. 在 `app/workers/session/registry.py` 以数据声明首期 6 个平台条目（Design §3.2）和未知站点默认条目。
    3. `schema.sql` 新增 `site_sessions`，删除 `provider_session_sources`、`provider_authorizations`；新增 ORM 模型；仓储分为只读非秘密列的 `SiteSessionStates`（API 用）和读写密文的 `SiteSessionSecrets`（仅 broker、导入命令使用）。
    4. 在已有数据库和空数据库上幂等执行 `schema.sql`。
  - 验收：PRD AC-02；单元测试覆盖站点解析全部样例；仓储测试断言 `SiteSessionStates` 的 SQL 不含 `ciphertext`。

<a id="s2"></a>

### S2 一次性导入命令

- [ ] **S2**；状态：未开始；依赖：S1。
  - 需求：FR-01、FR-10；NFR-03、NFR-05。
  - 步骤：
    1. 把 `chrome_provider_cookies.py` 迁为 `app/workers/session/chrome_reader.py`，参数化为域集合；删除原文件。
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
    1. 按 Design §8 删除模块、类型、Compose 服务与卷、配置键、测试；开发与生产 Compose 同步。
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

暂无。
