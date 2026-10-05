# 安全策略

## 产品边界

帧取是单人自托管工具，只处理部署者有权获取的非 DRM HTTP(S) 内容，不用于规避访问控制、版权保护或平台授权。内容范围（`public`、`personal_full`、`official_share`）与身份策略是两个独立维度，定义与平台适用范围见[解析引擎](workspace/content/design/14-解析引擎.md#1-目标与边界)。

## 强制控制

**输入**

- 普通业务接口不接受原始 Cookie、账号凭据、私网 URL、任意 yt-dlp 参数、shell 命令、输出路径或文件名模板。
- 用户 URL 只加密持久化；日志、消息与 API 错误中不出现完整 URL query。

**身份材料**

- 平台身份只来自用户普通 Chrome Profile 中的 `FrameFetch` 扩展。宿主 cookie-source 只监听 `127.0.0.1`，与扩展之间使用独立配对密钥双向 HMAC 认证并校验固定扩展 Origin；Runner 以独占 Bearer 按次请求材料。
- 不读取 Chrome Profile 文件、不访问钥匙串、不解密 Cookie、不需要完全磁盘访问。材料只存在于 Runner 内存与操作私有 tmpfs，操作结束即清理。
- 配对配置为当前用户 `0600`、目录 `0700`。该机制不能防御同一用户下的恶意进程。

**执行隔离**

- 媒体工具只在 `session-runner` 中执行。Runner 不持有 PostgreSQL、RabbitMQ、MinIO、Redis 或 AI 凭据，不挂载 Docker socket、宿主 Chrome Profile、钥匙串或 CLI 认证目录。
- 外部媒体流量只经过 `egress-proxy`；入口 URL 校验不替代出口层的 SSRF 防线。
- 外部操作设置大小、时长、并发与超时上限，取消时终止整个进程组。

**Secret**

- 基础设施 Secret 只来自类型化配置与环境变量；生产必须替换 `.env.prod` 中的全部占位值，配置校验会拒绝开发密钥。
- 管理员在 Web 中维护的 AI Provider Key 只存入加密数据库字段，仅在 AI Worker 内存中解密。
- 任何 Secret 不进入前端、API 响应、异常、快照、测试夹具、普通日志或 Git。

## 报告漏洞

请勿在公开 Issue 中披露可利用细节、密钥或用户内容。通过 GitHub 私有安全报告提交复现条件、影响范围与最小 PoC；维护者完成分级与修复后再协调披露。

## 发布门禁

涉及 URL、Runner、子进程、对象存储、身份材料、队列或模型输入的变更，必须包含对应的滥用与失败测试，并通过 [CONTRIBUTING.md](CONTRIBUTING.md#本地检查) 列出的全部检查。
