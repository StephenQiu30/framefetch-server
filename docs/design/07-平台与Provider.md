# 平台与 Provider 体系

当前登记的 23 个 Profile 均有固定 metadata／media 样本，是否能在目标机器下载须用真实文件验证。后续按平台适配器契约收敛识别、凭据、解析、下载和完整性验证；Temporal 只编排这些操作。逐平台覆盖与待实施方案见[工作流与平台下载目标](15-工作流与平台下载目标.md)。

## 分层模型

- **Provider Catalog**：声明式、版本化 Profile（平台、host 白名单、能力、访问模式、Cookie allowlist、状态）；`provider_catalog_entries` 承载管理员可见目录。当前默认 23 个解析 Profile，另有 Generic 与硬阻断域；已退出范围的平台域名明确拒绝，不落入 Generic。
- **Runner 执行面**：媒体解析与下载在独立隔离的 `workers/runner/` 进程完成（固定版本 yt-dlp、可信仓库插件、进程组隔离、HMAC 认证、纵深 URL 准入、tmpfs 工作区）。API 与 Worker 不持有 Provider Secret。
- **访问上下文**：inspect、下载前重解析、视频流、音频流与 probe 使用同一冻结的 `ProviderAccessContext`（Provider、Profile、来源修订、客户端、出口、引擎身份）。下载不得切换匿名／账号／端点；重解析必须核对内容标识。
- **能力证据**：Registry 中每个平台有固定 metadata／media 诊断样本，`provider_canary_results` 记录真实结果，`GET /api/providers` 聚合动态状态；无当前证据不显示“已验证”。`PROVIDER_VERIFIED_KEYS` 显式批准后，且 metadata、完整媒体、完整视频 Agent／报告证明均新鲜，才可提升为 `verified`。`route_cooldowns` 控制冷却，遵守 `Retry-After`，平台整体 429／挑战时停止重试放大，不靠轮换身份或出口规避。
- **YouTube**：固定 mweb + EJS + bgutil PO Token sidecar；POT 不能修复登录过期或出口挑战；侧车与脚本不一致时暂停 YouTube 接单。
- **错误优先级**：受控会话缺失／过期／验证失败直接返回稳定错误，不降级匿名掩盖根因；DRM、付费、私密、地域限制直接拒绝。错误按阶段与明确证据归类，模糊错误不直接要求账号。

## 路线选择（当前）

`ProviderProfile.access_policy` 是当前批准路线的唯一声明，`execution_access_mode` 从它派生；`access_modes` 只表示引擎具备的技术能力，不自动授权执行。API、Runner、状态目录与探针读取同一 Registry，意图在联网前持久化，匿名阶段仅在明确认证失败时选择已批准的公开账号能力；不因限流、网络或私有内容失败扩张范围。默认 23 平台的访问范围保持不变；显式配置的 PeerTube 精确实例读取自身公开声明，未知实例仍不可进入公开入口。

账号站点的 Cookie 条件、页面头插件与权益范围通过 `session_policy` 组合进同一 Profile，删除独立的站点声明表。Registry 在启动时拒绝不受支持的执行模式、访客策略、缺失账号策略、账号归属／权益冲突及重复站点。状态目录不再包含已退休访客路线的分支。

新增平台通常只需一份 Profile、实际需要的 URL／提取器策略和真实样本；使用 Registry、Strategy 与公共 Pipeline 组合，避免每个平台增加一套调度和业务层。匿名优先与 Chrome 会话来源已实施，产物沿用既有共享卷；真实能力验收，见[工作流与平台下载目标](15-工作流与平台下载目标.md)。

## 内容权益

默认仅公开、免费、非 DRM、用户有权保存的内容；会话机制不扩大内容授权。

- **付费与试看识别**：B 站充电（`content_supporter_only`）、试看（`content_preview_only`）、抖音付费（`content_paid_only`／`content_export_required`）、权益元数据异常（`content_access_metadata_invalid`）在归一化之前识别并阻断：`access_decision=blocked`、`formats=[]`。“已购买”标记不是文件导出授权。字段缺失不证明免费。
- **腾讯视频与优酷**：个人单视频、非 DRM 路径，复用固定 yt-dlp 提取器加仓库插件；在原始响应归一化前校验完整时长与分段，缺失 `cdn_url` 或试看返回受限原因；DRM 清单排除；最终以 ffprobe 校验实际文件（时长容差 `max(3 秒, 2%)`）。完整 VIP 下载待真实样本验证，不承诺全部会员画质。
- **微信**：公众号文章作为多资产发现容器，只有无登录、身份映射唯一、公开 clear 的原生视频可下载；视频号公开 `/sph/` 链接当前走元宝会话接入，登录态与页面请求头通过宿主机来源按需取得，细节见[平台会话](08-平台会话.md)。接入代码不等于已验证稳定下载，出现 `decodeKey`、DRM、加密或未知媒体域立即拒绝；无法取得合法 clear 媒体时引导上传自有／已授权文件。
- **授权导出（预留）**：只有拿到正式逐资产导出渠道后，才单独实现 OfficialConnector（验证资产、主体、用途、有效期、非 DRM、完整时长与可解码性）；公共解析插件不得自行升级为授权下载。
- **其他短视频平台**：分阶段补 canary 与完整 E2E 证据后才升级状态；carousel／一帖多视频在多资产模型支持前 fail closed；PeerTube 仅精确实例白名单。
- **Edge Agent（未实施）**：用户设备配对与签名上传只传输用户已合法取得的明文文件，不做采集、解密或代理；复用本地上传的 quarantine、验证与晋升能力。
