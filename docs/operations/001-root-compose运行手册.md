# 根目录 Compose 运行手册

## 运行模型

业务拓扑只有一个运行入口：根目录 `docker-compose.yml`。本机直接复用已经运行的
PostgreSQL、RabbitMQ、Redis 和 MinIO，但前端、API、Worker、Runner 与
Operator 必须处于同一 Compose 网络；不提供宿主机业务进程与容器 Operator 混合运行入口：

| 文件 | 用途 | 是否启动 PostgreSQL、RabbitMQ、Redis、MinIO |
| --- | --- | --- |
| docker-compose.yml | 本机/共享环境运行，只启动业务容器 | 否，复用宿主机已有服务 |
| docker-compose-prod.yml | 独立的生产业务容器运行配置，与默认拓扑保持一致 | 否，复用生产宿主机服务 |

默认业务拓扑包含独立 Next.js 前端、API、Outbox、下载 Worker、导入 Worker、报告 Worker、Provider Canary、Media Runner 和受控出口代理。前端监听 8101，API 监听 8111。YouTube Operator 与其他 Provider Operator 只通过对应 profile 显式启用。

构建参数和受控 Runner 可共用 YAML Anchor；业务进程分别声明自己的角色、连接地址、密钥、挂载、网络和启动命令。`.env` / `.env.prod` 仅供 Compose 插值，业务服务不再使用整份 `env_file` 注入。

## 配额与代理配置

`QUOTA_LIMITS` 和 `RATE_LIMIT_POLICIES` 接受局部 JSON 覆盖；默认值、滚动 24 小时口径、存储预留和恢复方式见 [准入设计](../design/006-上线产品能力补全设计.md)。调整文件、规范化文本或报告上限时，应同步重建 API 与对应 Worker，使准入预留与执行上限一致。分片 URL 绑定精确 `Content-Length`；代理必须保留此头，不能改为未确定长度的上传。Next.js `/storage-upload` 已转发该头。

部署者通过 `TRUSTED_PROXY_CIDRS` 声明外部入口代理，使用 `FRONTEND_IPV4_ADDRESS` 同时配置前端容器地址及 API 对该主机的信任；`APP_NETWORK_SUBNET`、`APP_NETWORK_IP_RANGE` 应与它相容。API 自行解析可信转发链，入口关闭 Uvicorn 自动代理头改写。公网入口需要将真实客户端地址追加到转发链，并直接转发 WebSocket Upgrade；不要信任任意客户端传入的地址。

生产密钥检查只要求当前角色使用的密钥。Import、Report、Outbox 不接收 URL 解密密钥，Worker 不接收 JWT、管理员初始化及指标访问密钥；MinIO 消费者继续共用仓库规定的一组业务凭据。更改配置后使用对应 Compose `up -d --build` 应用，不用 `restart` 代替配置更新。

## Docker 文件使用规范

下载角色需要声明与消费两条有界队列：`video.download` 和 `video.download-intent`，各自有 `.dead` 队列。升级持久解析入口前，在现有 RabbitMQ 的项目 vhost 中，为实际 `RABBITMQ_DOWNLOAD_USER` 配置这四条队列以及 `video.events`／`video.events.dead` 的 configure、write、read 权限；标准名称的匹配式为 `^video\.(events|events\.dead|download|download\.dead|download-intent|download-intent\.dead)$`。使用自定义队列／交换机名时对应精确调整，不给 Worker 管理员权限。Outbox 仍只需写 `video.events`，无需管理权限；运维 DLQ 角色如要处理新死信队列，再增加该队列的 read 权限。不要覆盖其他业务 vhost 或删除已有队列。

如果 Worker 报 `ACCESS_REFUSED` 且指向 `video.download-intent`，先修复该角色权限，再重启 Worker 重新声明绑定；仅看到 API 健康不代表接单能够执行。部署验收必须使用 Compose 中真实受限角色，确认新意图实际离开 queued。CI 基础设施夹具也声明解析队列及 DLQ，但它的宽权限测试账号不能代替受限账号验收。

若 RabbitMQ 同时启用了 topic permissions，还须在 Outbox 角色的 `video.events` write routing-key 列表中加入 `^download\.intent\.requested$`；资源级 exchange write 权限不能替代该项。下载角色如有 topic read 限制，也须加入对应解析与死信 routing key。新队列已声明但 outbox 持续 `ChannelAccessRefused` 时检查这一层，不能通过给业务进程管理员权限解决。

- `docker-compose.yml` 和 `docker-compose-prod.yml` 只管理业务容器，不启动基础设施或初始化容器。
- 直接沿用当前 `.env` / `.env.prod`。容器通过 `POSTGRES_HOST/PORT`、`RABBITMQ_HOST/PORT`、`REDIS_HOST/PORT` 和 `MINIO_HOST/PORT` 访问已有服务；默认主机为 `host.docker.internal`，端口以本机实际配置为准。宿主机运行的命令使用相应回环地址。
- MinIO 只配置一组 `MINIO_ACCESS_KEY` 与 `MINIO_SECRET_KEY`，所有业务进程共用。
- `docker-compose-env.yml` 仅保留为 GitHub CI 的隔离夹具，本机启动和验证不使用它。CI 的临时服务端口不应复制到本机业务配置中。

## 宿主机基础设施

使用业务 Compose 前，确认本机以下服务已经运行：

- PostgreSQL
- RabbitMQ
- Redis
- MinIO

容器通过现有环境文件中的连接地址访问这些服务。连接地址和凭据不能提交到 Git。数据库结构变更时按需执行 `backend/sql/schema.sql`；已有 RabbitMQ 拓扑、MinIO bucket 和身份继续复用，启动项目不执行整套初始化。

复用外部 MinIO 时，部署者必须在该实例的启动环境中设置与 `.env` 相同的 `MINIO_API_CORS_ALLOW_ORIGIN` exact-origin 列表并重建实例；不能依赖手工 bucket CORS、`*` 或遗留实例状态。社区版 MinIO 的浏览器上传策略是实例级 API 配置，仓库不会尝试调用不受支持的 bucket CORS API。无法控制外部实例启动配置时，应关闭 `MEDIA_IMPORT_ENABLED` 与 `DOCUMENT_IMPORT_ENABLED`，而不是放宽 CORS。

本机开发同时需要从浏览器和真机 App 上传时，`MINIO_PUBLIC_ENDPOINT` 应配置为真机可访问的 HTTPS 地址，`MINIO_LOCAL_BROWSER_ENDPOINT` 配置为 `127.0.0.1:<port>`。只有来自回环页面、显式标记为本地 Web 的开发请求会使用回环签名地址；Flutter 和远程 Web 始终使用公共地址。该分流由项目配置完成，不依赖或修改操作系统代理规则。生产环境应省略 `MINIO_LOCAL_BROWSER_ENDPOINT`。

私有 Tailnet 生产部署应使用节点的 Tailscale HTTPS 名称作为 `SITE_URL`，不能使用 `http://100.x.y.z`。`SITE_URL` 只生成公开元数据与绝对链接，不会把直接访问的 `8101` 请求重定向到 Tailscale；HTTPS 和规范域名跳转如有需要，应由部署入口配置。手机和 Mac 通过 Tailnet HTTPS 使用 `Secure` 会话 Cookie，远程 Web 与移动端继续使用 `MINIO_PUBLIC_ENDPOINT` 的 HTTPS 地址；本机开发可直接使用 `http://127.0.0.1:8101`。

macOS 若启用了系统 HTTP/HTTPS/SOCKS 代理，活动网络服务的代理绕过列表必须包含 `100.64.0.0/10` 与 `*.ts.net`。否则 Safari/WebKit 会把 Tailnet TLS 请求交给公网代理，而不是经 Tailscale `utun` 接口直连，表现为证书正常但页面无法建立安全连接。该规则属于 Tailnet 路由边界，不是浏览器兼容分支；修改后应在 WebKit 网络日志中确认目标 `100.x` 地址通过 `utun` 连接。

## 新机器部署边界

新机器须先提供项目专用的 PostgreSQL、RabbitMQ、Redis、MinIO 及稳定密钥，再按下文的业务拓扑启动；将实际连接信息写入不入库的 `.env`。当前仓库尚未通过全新宿主机的空状态、备份恢复与容量验收，不能把 CI 的 `docker-compose-env.yml` 当作生产基础设施安装入口，也不能沿用 `.env.example` 的开发凭据宣称一条命令完成部署。P9.09 在这些验收完成前保持开放；平台访客自动准备只在核心依赖已可用后运行。

## 本机业务拓扑

~~~bash
# 已有 .env 直接复用；仅首次缺少文件时创建并填写已有服务的连接信息
test -f .env || cp .env.example .env
docker compose --env-file .env -f docker-compose.yml config --quiet
docker compose --env-file .env -f docker-compose.yml up -d --build --wait
~~~

最后一条命令是本机完整项目的启动与重建入口，不需要任何宿主进程。需要登录态的站点由
部署者一次性导入站点会话，之后由 `session-broker`、`session-browser`、`session-runner`
在容器内维护；步骤见 [011 站点会话运行手册](011-站点会话运行手册.md)。服务健康与平台
接受会话分别检查，不把核心健康冒充为平台可下载。
不要使用不会应用代码、镜像或配置变化的
`docker compose restart`。

出口目的地址策略由固定版本 Squid 与只读 ACL 文件实现。所有环境统一使用
`backend/egress/blocked-destinations.conf`：放行透明代理与 Docker Desktop 用于公网
DNS 的合成段 `198.18.0.0/15`，其余私网段、字面量 IP 与非 Web 端口一律拒绝。Bilibili
媒体 CDN 的 4483/8082 与抖音冷媒体 CDN `*.wmzfylgdsz.com` 的 TLS 8889 例外仅对指定域名开放。
`docker compose up` 不会因为只读挂载的 `squid.conf` 或 `blocked-destinations.conf` 内容变化而重建
`egress-proxy`，Squid 也不会自行重读配置；旧策略会在新代码需要的目的地上直接拒绝，表现为重启后首次解析或下载失败。
因此健康检查每 10 秒比较两个策略文件的修改时间：有变化时先 `squid -k parse` 校验，通过后执行
`squid -k reconfigure` 热加载；校验失败时继续使用正在运行的旧策略并把容器标为 unhealthy，修正文件后自动恢复。
`backend/egress/` 以目录只读挂载到 `/etc/squid/policy`，`git pull`、`git checkout` 或编辑器以替换文件方式保存后，
容器内都能读到新内容；不要改回单文件挂载，否则 Linux 上容器会继续读取被替换前的旧文件。镜像、挂载或网络配置变化仍需重建
`egress-proxy`。

访问地址：

- Web：http://localhost:8101
- API/Swagger UI：http://localhost:8111/docs
- OpenAPI：http://localhost:8111/openapi.json

如果只需要容器内的受控出口代理：

~~~bash
docker compose --env-file .env -f docker-compose.yml up -d egress-proxy
~~~

## 更新项目

代码同步与服务启动保持解耦；需要更新时先执行：

~~~bash
git pull --ff-only
~~~

随后执行上面的唯一业务 Compose 命令。YouTube、TikTok、X 完整媒体 Canary 属于
启动后的验收步骤，不与项目生命周期耦合；命令见
`docs/operations/007-固定Provider探针运行手册.md`。

业务 Compose 的更新和停止只作用于项目业务容器，已有基础服务继续运行。

## 生产环境

.env.prod 由部署者在本机或 Secret 管理系统维护；以 .env.example 为配置字段参考，保留已有环境文件。生产需设置 APP_ENV=production，按部署实际填写公开地址与凭据；显式设置 ANALYSIS_ENABLED=false、SCREENPLAY_ANALYSIS_ENABLED=false，直到宿主分析 Worker 已完成配置。生产出口策略使用 `./backend/egress/blocked-destinations.conf`。

~~~bash
# 准备好 .env.prod 并替换全部 replace-with-* 占位值后执行
docker compose --env-file .env.prod -f docker-compose-prod.yml config --quiet
docker compose --env-file .env.prod -f docker-compose-prod.yml up -d --no-build
~~~

生产镜像分别使用 video-server:prod（后端）与 video-frontend:prod（前端），由各自目录的 Dockerfile 构建。生产 Compose 不启动基础设施初始化服务，也不包含 environment profile。

后端所有进程（包括来源同步与初始化）必须使用同一份 `video-server:prod` 发布镜像。Python／Node 基础镜像在两个 Dockerfile 中固定多架构索引摘要；Python 依赖来自 `uv.lock`，Web 来自 `pnpm-lock.yaml`，yt-dlp 固定源码 commit。基础镜像摘要不等于最终镜像摘要：系统 apt 包仍在构建时解析，因此部署和回滚保留最终构建产物，不在不同机器重新构建后假定二进制相同。更新基础摘要须重新执行确定性检查、双架构运行检查和相关平台验收；启动阶段不得临时安装最新版依赖。

在支持 containerd image store 的 Docker Desktop／Engine 上，标准镜像的双架构本地构建入口为：

~~~bash
docker buildx build --platform linux/amd64,linux/arm64 --load \
  --metadata-file /tmp/framefetch-backend-build.json \
  -t video-server:prod ./backend
docker buildx build --platform linux/amd64,linux/arm64 --load \
  --build-arg SITE_URL=https://你的实际域名 \
  --build-arg SITE_INDEXABLE=false \
  --metadata-file /tmp/framefetch-frontend-build.json \
  -t video-frontend:prod ./frontend
~~~

两份 metadata 中的 `containerimage.digest` 是本次多架构产物身份。经典 Docker image store 不支持同时加载两架构时，分别指定单一 `--platform` 构建并记录产物；需要发布仓库时由部署者指定可信仓库，用 `--push` 保留索引与构建证明。不要把 amd64 模拟执行的耗时用于原生容量承诺。此入口覆盖标准镜像；精简模式和自动升级／回滚尚待 Plan P9.09／P9.13 验收，不能通过自行删除 guest 服务声称同等平台能力。

依据：[Docker 固定基础镜像](https://docs.docker.com/build/building/best-practices/#pin-base-image-versions)、[多架构构建](https://docs.docker.com/build/building/multi-platform/)。

生产健康检查：

~~~bash
curl --fail http://127.0.0.1:8111/health/live
curl --fail http://127.0.0.1:8111/health/ready
~~~

## AI Worker

AI Worker 继续运行在宿主机，不由 Compose 启动。Agent 必须读取与业务 Compose 相同的环境文件；本地组合使用默认 `.env`，生产组合显式传入 `.env.prod`：

~~~bash
cd backend
uv run python -m app.workers.analysis.agent_cli doctor
uv run python -m app.workers.analysis.agent_cli install
uv run python -m app.workers.analysis.agent_cli status
~~~

~~~bash
uv run python -m app.workers.analysis.agent_cli doctor --env-file ../.env.prod
uv run python -m app.workers.analysis.agent_cli install --env-file ../.env.prod
uv run python -m app.workers.analysis.agent_cli status
~~~

AI Worker 心跳是功能级状态，不是 API 全局 readiness。Worker 短暂重启时分析任务
保持 `queued`，下载、上传和历史查询继续可用；不提供分析能力的部署仍应显式设置
`ANALYSIS_ENABLED=false` 后重建 API。

## 站点会话

所有站点会话服务随默认拓扑启动，没有 Compose profile。生产部署须显式设置
`SITE_SESSION_ENCRYPTION_KEY`、`SITE_SESSION_RPC_SECRET`、`SITE_SESSION_BROWSER_SECRET`：

~~~bash
docker compose --env-file .env.prod -f docker-compose-prod.yml config --quiet
docker compose --env-file .env.prod -f docker-compose-prod.yml \
  up -d --build --force-recreate --remove-orphans --wait --wait-timeout 300
~~~

导入、撤销与换机见 [011 站点会话运行手册](011-站点会话运行手册.md)。

### Runner 代际协议升级顺序

代际功能必须先把兼容基线 `a84fc3da`（包含 `0e438344` 的协议准备与冷却探测回滚修复）部署到所有 API、Runner、下载 Worker 和 Canary；基线沿用内部 v1 协议，旧数据输出仍为旧形状，但能读取将来带代际字段的记录和响应。在启用行为版任一容器之前，部署者必须用有 DDL 权限的现有 PostgreSQL 连接执行新版 `backend/sql/schema.sql`，并验证 `download_jobs` 上的 `execution_access_context`（JSONB）和 `execution_context_attempt`（INTEGER）两列均存在；Compose 不会自动迁移，任一列缺失就停止发布。之后才能构建行为启用版本的同一后端镜像，先重建 YouTube POT 侧车以及当前 Compose profile 启用的匿名、guest、operator Runner，确认侧车 `healthy`、Runner `/health/runtime` 与签名 v1 上下文返回代际；再重建 API、下载 Worker 和 Canary。侧车脚本来自仓库只读挂载，宿主文件更新不会使旧 Node 进程自动加载新代码；健康检查会比较进程启动时的脚本摘要与当前挂载文件，不一致时先重建侧车再开放 YouTube 路线。过渡中的兼容基线调用方会读取新字段，并按新 `generation_id` 屏蔽旧 MEDIA 证据。行为启用版本的调用方若连到旧 Runner 会拒绝新工作。回滚只能先退回兼容基线调用方，再退回兼容基线 Runner；不能回到 `a84fc3da` 之前的版本。旧 inspection 不删除；Worker 只在账号、出口、引擎、策略等引用不变时刷新代码代际，Runner 仍复核媒体身份与格式。实际执行上下文与 attempt 编号在当前租约下先写入 job；仅编号仍等于最终尝试时，成功和终态失败才按它筛选媒体证据；成功 artifact 另存同一 attempt 的兼容副本；旧版无执行上下文的任务在新版 MEDIA 状态中不计证据。YouTube 接单还需从侧车身份端点核对运行脚本 SHA-256，脚本与 Runner 镜像不一致时暂停该平台新工作。

迁移门禁查询应在业务 schema 中返回两行，类型分别为 `jsonb` 和 `integer`。行为版 API 在启动后台服务前、下载 Worker 在消费队列前均执行相同的结构检查；缺失或类型不符时新进程启动失败。API `/health/ready` 也持续检查这两列，返回 503。部署时仍须先迁移再重建，进程门禁不能替代发布前检查：

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND table_name = 'download_jobs'
  AND column_name IN ('execution_access_context', 'execution_context_attempt')
ORDER BY column_name;
```

当前 Compose 对每个 Runner 是单实例，重建时该路线会短暂不可用；持久意图在已有预算内等待恢复。必须记录该窗口的排队时间和失败率，并实际演练新旧接口、在途任务与反向回滚。不能把分阶段兼容自动解释成零中断或已完成高可用验收。

## 停止和数据安全

~~~bash
docker compose --env-file .env.prod -f docker-compose-prod.yml down
~~~

不要在未确认备份的情况下使用 --volumes。 .env、.env.prod、Cookie、Authorization、Provider key 和完整模型输出不得进入日志或 Git。
