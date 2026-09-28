# 媒体解析策略责任链与 Provider Session 生命周期

- 状态：当前设计事实；外部 Provider 真实可用性由 canary 持续判定
- 关联设计：`005-多平台Provider策略设计.md`

## 1. 问题与目标

解析入口原先在 `MediaRunnerRouter.inspect` 中直接嵌套匿名与 Operator
异常处理。它能够工作，但路由顺序、允许降级的错误和最终错误优先级耦合在
同一个方法中；YouTube 登录 Cookie 被浏览器轮换后，Runner 又会把带 Cookie
的 bot challenge 误报为出口验证失败，导致用户只能看到“稍后重试”。

本设计完成六个目标：

1. 用可测试的策略责任链统一匿名与 Provider Operator 解析路径。
2. 以错误策略对象约束降级范围，并优先暴露已配置会话过期。
3. Operator 会话从已授权 Chrome 的操作级租约或部署方单平台只读文件取得；
   可写副本只在 tmpfs，不依赖 AI Worker，也不提供普通用户 Cookie 上传入口。
4. 私有封面通过认证 HTTP client 获取并在内存中显示，不让原生图片请求绕过
   Access/Refresh Cookie 恢复。
5. 下载任务由 Worker 在执行前重新解析并校验规格；终态重试只负责入队，避免
   Provider 的短时不稳定直接阻断 HTTP 操作。
6. 为 Registry 中每个平台维护固定 metadata/media 诊断样本，并把真实结果写入
   canary 表；没有当前证据时不再显示静态“已验证”日期。

## 2. 解析管线模式

```mermaid
flowchart LR
    API["MediaRunnerRouter facade"] --> P["MediaInspectionPipeline"]
    P --> A["Anonymous runner strategy"]
    A --> F{"Failure policy permits fallback?"}
    F -->|No| E["Stable public-path error"]
    F -->|Yes| O["Provider operator strategy"]
    O --> S{"Operator result"}
    S -->|Success| R["Frozen access context"]
    S -->|Session expired| X["Session-expired diagnosis"]
    S -->|Other failure| E
```

采用的模式和边界如下：

- **Strategy**：每个隔离 Runner client 是一个可替换的解析策略。
- **Deterministic routing**：`MediaInspectionPipeline` 每次只选择一个 Runner。已配置受控会话的
  Provider 直接进入对应的独立 Operator，其余 Provider 直接进入匿名 Runner。
- **Frozen access context**：解析成功后固化 Provider、Profile、会话来源和 Runner，下载不得
  切换匿名、账号或其他端点。
- **Facade**：`MediaRunnerRouter` 只协调单一解析、下载上下文和活跃任务，不再内嵌
  Provider 字符串分支或失败回退。

受控会话缺失、过期、验证失败或被限流时直接返回对应稳定错误，不转移到匿名
路径掩盖根因。DRM、付费、私密、地域或其他权益限制直接拒绝，不切换账号或客户端。

## 3. Provider Session 生命周期

需要登录态的平台统一使用站点会话，设计见 [046](046-容器自持平台会话设计.md)，运维见 [011 手册](../operations/011-站点会话运行手册.md)：

1. 部署者一次性从本机 Chrome 导入站点 Cookie，加密保存在 PostgreSQL；业务进程不读取 Chrome Profile 或 Keychain。
2. 容器内会话浏览器保持登录并采集轮换后的 Cookie；只有 `session-broker` 持有解密密钥。
3. Runner 每次操作领取绑定任务与站点的一次性封装租约，只在独占 tmpfs 中创建 `0600` jar；Cookie 原文不进入 API、RabbitMQ、日志、业务响应或 AI Worker。
4. 撤销时站点回到公开路线，浏览器 Profile 被删除；平台侧会话由部署者在第一方撤销。

视频号的会话来自腾讯元宝（`yuanbao.tencent.com`），动态请求头由会话浏览器按任务生成并直接封装给 Runner。

## 4. 环境策略

| 环境 | 会话来源 | 生命周期 | 用途 |
| --- | --- | --- | --- |
| 本地开发 | 伪造的一次性租约 | 单次操作 | 单元测试和隔离 Runner 契约 |
| CI | 伪造的一次性租约 | 单次操作 | 单元测试和授权 canary |
| 个人生产 | 管理页面远程登录的站点会话，容器内保活 | 会话持久；可写 jar 单次操作 | 单一 `session-runner` |

若未来平台提供官方 OAuth 或资产导出 API，应新增官方 Connector，以用户授权范围和
资产级导出权替代 Cookie。不得把本地授权工具、消费端私有接口或浏览器自动化扩展为
服务器登录方案。

## 5. 验收条件

- 已导入会话的 YouTube 链接在 inspect 开始时直接选择站点会话路线。
- 带 Cookie 的 bot challenge 分类为 `credential_expired`，页面给出可操作错误。
- 站点会话通过一次性加密租约交给 `session-runner`，业务容器不读宿主浏览器。
- 视频号只使用导入的元宝会话解析官方返回，不进入匿名或第三方回退。
- 解析成功后下载仍使用 inspection 冻结的 Operator access context。
- 限流等稳定错误在当前 Runner 内终止，不触发跨路由重试。
- 目标链接完成解析、选格式、下载、制品校验和 AI 分析入口验证。

## 6. 私有封面交付

封面对象继续存储在私有 MinIO，并由受保护的 inspection 路由返回。前端不能把
受保护 API URL 直接交给图片标签，因为图片导航不会经过共享 HTTP client 的
401 刷新拦截器。`media-assets` 服务先用认证 client 读取 Blob，校验 MIME 与
非空内容，再创建短生命周 object URL；`MediaCover` 最终仍用官方 Next.js
`Image` 组件解码和渲染，并用 shadcn `AspectRatio` 维持布局。组件卸载或来源
改变时立即 revoke object URL。

站点 CSP 只为 `img-src` 增加 `blob:`，不扩大 script、connect 或 frame 来源。
加载中与真正失败是两个不同状态，只有认证读取或浏览器解码失败才显示“封面不可用”。

### 6.1 前端组件边界

- 业务组件只组合 `components/ui` 中的 shadcn/ui 组件；原生表单控件和
  Radix primitive 只能出现在该目录内。
- 图片使用官方 Next.js `Image`；受保护资源适配是数据层责任，不重新实现
  图片组件。
- Dialog、Sheet、Popover、Select、RadioGroup、Progress、Alert 与 Input
  优先使用已安装的 shadcn 实现，由 Radix 提供焦点、键盘和无障碍语义。
- 业务组件继续只组合 `components/ui` 中的控件；原生交互控件和 Radix
  primitive 的边界由组件代码审查维护。

## 7. 下载规格与重试边界

平台可能在两次请求间轮换 CDN rendition。创建任务时只校验用户刚刚选择的
inspection/format 仍属于当前账户；终态重试不会在 HTTP 请求中再次调用 Provider，
而是复用已保存的来源引用和语义计划创建新的持久化队列任务。解析记录过期不影响
这个入队动作。

Download Worker 在真正下载前必须使用原访问上下文重新 inspect，检查来源身份、权益
和当前可用流，再由 Runner 依据语义计划选择流。Provider format id 只是短期 hint，
不能作为恢复依据；若当前规格不可用，任务返回 `format_unavailable`，用户重新解析
链接后选择新的真实规格。重新 inspect 成功后，Runner 把本次解析结果以 `0600`
临时 JSON 保存在当前任务工作区，并用 `--load-info-json` 下载刚刚选中的流；任务结束
后随工作区清理。这样既不把会过期的 CDN URL 持久化到 PostgreSQL，也不会为了下载
再次触发平台网页挑战。媒体字节、封装和最终制品完整性校验仍不能绕过，也不改写
原任务历史。

## 8. 固定诊断矩阵与状态真实性

`fixed_public_cases.json` 为 22 个注册 Provider 各保存一条 versioned metadata 和
media 诊断样本；单元测试要求它和 Registry 精确双向覆盖。诊断命令只输出
Provider、Profile、阶段、结果、稳定错误码和耗时，不输出 URL 或 Cookie。

固定公开矩阵用于定位上游回归，不替代生产环境 Secret 配置的项目自有/授权
canary。Registry 的基线表示当前版本已经完成的发布验收，不会因为长期无人下载或
没有配置固定探针而退回 unknown；只有近期重复失败、平台限流、认证失败或出口受限
才临时覆盖该基线。尚未发布验收的 unknown Profile 仍必须同时具备 metadata、media、
完整视频 Analysis 证据和显式批准，才能提升为 verified。

所有成功并保留完整制品的真实远程下载都会自动投影为非敏感 media 运行证据；投影
只读取 Provider/Profile/访问模式和完成时间，不解密、不返回来源 URL，也不记录用户
身份。状态 API 因而能立即反映真实用户链路的最近下载时间，26 小时后仅把“当前可用”
标记转为历史时间，不撤销已经发布的支持能力。完整 Analysis 仍使用严格 attestation，
不能由普通下载推导。证据读取按 Provider/Profile/访问模式和 stage 分别保留窗口，media
流量不能挤掉 metadata 或 analysis；探针调度也把当前 Profile 版本纳入 due identity，版本
升级后立即生成新证据，不依赖 target id 的命名约定。API readiness 只检查业务核心依赖，媒体 Runner 使用独立健康检查；
可选 Operator Runner 与平台 canary 的故障只降级对应平台，不让整个 API、上传、
匿名下载或 AI 配置不可用。

2026-08-29 的真实浏览器回归覆盖 22 个可启用 Provider：除小红书外均完成真实媒体
下载和制品校验；QQ 视频保持明确禁用。小红书当前公开入口由平台返回 `300012`
IP 风险限制，两个旧测试笔记由第一方页面返回 `300031` 已失效；系统分别保留平台
验证边界，并把确定失效的笔记归类为 `provider_link_unavailable`，不再伪报服务故障。
TikTok 解析只使用其嵌入播放器实际调用的第一方 `player/api/v1/items` 和 yt-dlp 默认
客户端；明确无 item/HTTPS 格式、API 临时故障与响应结构漂移分别归类为链接不可用、
临时不可用和提取器回归，不回退上游网页挑战。短链重定向也必须重新校验为 canonical
video/embed 后才能进入 Player extractor。Tumblr 公开页由项目插件直接读取
当前 `www` 页的 OG 视频与封面，避免上游旧 blog 子域改写触发 429。


## 媒体形态归一化

Runner 在视频时长探测和语义规格选择之前识别媒体形态。单视频保留真实视频规格；
单张图片和纯图集统一使用 `image_gallery`（`asset_count` 可以为 1），视频合集使用
`video_collection`。图片和合集沿用 API 返回的 ZIP 下载规格，前端不按平台名或 URL
虚构画质选项。图片来源必须是提取器给出的实际图片地址、图片格式，或明确声明
为图片的资源元数据；普通视频封面不能替代原媒体。

Instagram 适配器在提取边界保留上游图片/视频类型，通用 Runner 消费统一的类型字段，
不依赖帖子 ID、CDN 查询参数或特定截图中的链接。上游未返回可验证的媒体信息时仍然
明确失败，不承诺所有外部平台始终可用。

解析命令最多枚举配置上限加 1 项，额外一项用于检测溢出，超限时不静默截断。
缺失成员、嵌套合集会明确拒绝；图文混合集尚无统一成员下载计划，不能宣称完整支持。
每个合集成员均执行权益校验，下载阶段重新解析并检查媒体身份和数量，失败时不生成
部分成功的 ZIP。图集和合集打包后再次检查工作区容量，异常时清除部分文件与制品。

验证使用合成媒体元数据与下载替身，覆盖图片类型保留、单张图片、图集格式、视频封面
隔离、成员缺失、解析数量边界、权益校验和失败清理；外部站点实时可用性仍需 canary。
