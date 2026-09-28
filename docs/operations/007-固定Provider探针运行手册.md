# 固定 Provider 探针运行手册

> 当前固定矩阵仅使用会话路线；匿名和访客路线已移除。登录探针或会话未就绪的站点不可执行，真实文件通过才算媒体证据。访问规则以 [046](../design/046-容器自持平台会话设计.md) 为准。


本手册用于当前固定引擎、Runner 拓扑和网络出口的回归诊断。公开诊断样本只定位
Extractor、访问和下载链路问题；生产发布仍必须使用项目自有或明确授权、由 Secret
配置的 canary，并完成完整视频分析证据。

## 1. 前置检查

当 `.env` 配置 Provider Operator 时，先确认一次性登记的 Secret，再启动 Compose
Profile。项目不启动 Session Broker：

```bash
docker compose --env-file .env -f docker-compose.yml \
  --profile youtube-operator --profile douyin-operator \
  --profile reddit-operator --profile wechat-channels-operator \
  up -d --build --wait

curl --fail http://127.0.0.1:8111/health/ready
```

全局就绪检查只证明核心 API 依赖可用，媒体 Runner 和受控会话使用各自探针。
API 就绪不能替代固定 Provider metadata/media 验收。`provider-canary` 必须显示 `runner_work:/work` 挂载，且容器内
`RUNNER_WORKSPACE_ROOT=/work`。

`PROVIDER_CANARY_TARGETS` 的每条目标必须显式声明 `access_mode`。公开路由写
`anonymous`，会话路由写 `operator_managed`；同一样本的两种路由必须使用
不同 `target_id` 分别配置 metadata/media 目标。Canary 只执行声明的单一
Runner，不存在 anonymous→operator 回退。未配置对应 Operator Runner 的
`operator_managed` 目标会如实记录为访问失败。

## 2. 固定矩阵

样本位于 `backend/app/workers/canary/fixed_public_cases.json`。矩阵覆盖已登记会话机制的平台，每个 target 包含 metadata 与 media 两条记录；URL 不会出现在命令输出或数据库 canary 行中。所有探针固定使用 `operator_managed`，会话缺失或登录探针未验证时明确失败，不自动准备访客或回退匿名。矩阵登记仅代表测试目标，不等于该站点已经通过真实文件验收。

media 阶段必须下载解析结果中的第一项格式，与 Web 界面默认选项保持一致；不得改成
最低清晰度来缩短探针时间，否则会漏掉真实用户默认格式的签名或客户端兼容问题。

浏览器、API 和重启验收必须从该固定矩阵取样，不得使用 yt-dlp README、
extractor 单元测试或其他项目的历史链接代替服务验收样本。上游历史样本下架、
转私密或对当前出口限制时，只能作为内容级负例，不能用于判定 Provider
整体不可用。

```bash
docker exec video-provider-canary \
  python -m app.workers.canary.fixed_matrix --stage metadata

docker exec video-provider-canary \
  python -m app.workers.canary.fixed_matrix --stage media
```

只复测单个平台：

```bash
docker exec video-provider-canary \
  python -m app.workers.canary.fixed_matrix --provider youtube --stage media
```

只有本次选择的所有目标都成功时命令返回 0；任何失败返回 1，并写入正常
`provider_canary_results`。不要用 `|| true` 掩盖发布门禁。

未知 `--provider` 返回 2，且不创建 runtime、不执行部分已知平台；避免拼写错误造成漏测而误报通过。先对齐整组镜像和 schema，需要登录态的平台先按[站点会话手册](011-站点会话运行手册.md)导入会话。诊断保持串行，时长/大小采用预先声明的 Runner 预算；超时或超限记为未在预算内完成，不能临时降低清晰度或换样本。固定样本不是所有内容或所有能力的发布保证。

## 3. 结果判读

| 稳定错误 | 判定 |
| --- | --- |
| `provider_auth_required` / `provider_session_expired` | 会话缺失或失效；重新执行一次对应 Provider 授权并重建 Operator，不轮换账号放大请求 |
| `provider_verification_failed` | 平台人机验证/挑战未通过；保留最后有效登录态并降级平台，不自动规避 CAPTCHA |
| `format_unavailable` | 相邻 rendition 漂移或原规格消失；探针有界重检三次，用户重试自动选择当前兼容规格 |
| `provider_drm_protected` / `provider_content_restricted` | 内容能力边界，不重试、不绕过 |
| `extractor_regression` / `provider_temporarily_unavailable` | 上游页面或固定 extractor 回归，降级对应平台 |
| `provider_rate_limited` | 当前会话/出口限流，停止高频复测并等待 |
| `media_validation_failed` | 下载文件、共享路径或 ffprobe 契约异常，属于本项目公共链路故障 |

metadata 成功不等于可下载；media 成功也不等于 AI 分析完整。Registry 中已经完成
发布验收的基线长期保留，近期重复失败才临时降级；尚未验收的 Profile 仍需要近期
metadata、media、完整视频 Analysis attestation 和显式批准才能提升。

平台状态同时合并固定探针与真实业务下载。只有状态为 succeeded、制品仍保留且含有
有效 Provider 访问上下文的远程任务才会成为 media 证据；不会解密来源 URL，也不会
公开任务、用户、账号、Cookie 或出口标识。固定探针用于无人使用时的主动监测，真实
任务用于及时反映用户实际链路，两者不需要维护平行的手工状态。

2026-08-29 当前版本对 22 个已启用 Provider 执行了 44 个固定探针（metadata/media
各 22 个）。其中 16 个 Provider 在全矩阵中两阶段均成功，哔哩哔哩的 media
阶段成功；TikTok 已以 `tiktok-public-player` Profile 单独复测，anonymous
metadata 与完整媒体探针分别在 2678ms、4771ms 成功。该版本删除了遗留的浏览器、会话与
device-id 参数，只使用第一方公开播放器 API，不依赖 Cookie、本地浏览器或 Operator
会话。YouTube、抖音、Reddit 和微信视频号的
固定公开样本仍被平台授权、验证或公开媒体边界拒绝；这些结果必须如实投影为
`access_required` 或 `degraded`，不得通过为绕过失败而更换样本、手工改数据库或恢复个人
浏览器会话伪造可用。对应的 C 端降级入口是上传用户拥有或已获授权的文件。
所有成功任务由状态服务自动显示为最近真实下载，无需手工更新页面状态。

## 4. 更新固定样本

只在原内容删除、链接写错或不再属于预期能力边界时升级 target 版本。更新前先用
当前 Runner 验证 Provider identity、单视频边界、最低规格完整下载、SHA-256 和
ffprobe；同一版本不得静默换 URL。测试要求矩阵和 Registry 双向一致，新增/删除
Provider 时必须同步更新。
