# 平台与 Provider 体系

解析引擎的阶梯、出口与身份声明统一以[设计 17](17-解析引擎重建.md)为准。本页只维护目录职责和既有内容校验边界，平台登记、提取器存在与真实文件验收分别记录。

- **Provider Registry**：声明平台、域名、媒体能力、阶梯、出口、identity 与 content_scope，语义见设计 17。
- **Provider Catalog**：`provider_catalog_entries` 保存管理员可见名称、顺序、显示与启用状态，不控制 URL、提取器或身份。
- **Runner**：独立执行 yt-dlp 与可信插件，保留 HMAC、SSRF、出口代理、进程组取消和资源上限。API 与 Worker 不持有平台 Cookie。
- **ExecutionContext**：十二字段摘要贯穿意图、检查、下载 Job 与制品元数据。下载在同一成功层与出口重新解析并核对媒体身份、完整时长及语义规格。
- **YouTube**：保留现有 EJS、JS 运行时与 bgutil 配置，安装版本仅用于诊断；发行身份或版本差异不阻断任务。
- **失败**：统一使用设计 17 第 3.6 节的十三类失败，并携带 layer、stage、gate、结构化 evidence 和摘要。`GET /api/providers` 展示声明能力，不声称已验证下载。

## 内容权益

默认仅公开、免费、非 DRM、用户有权保存的内容；会话机制不扩大内容授权。

- **付费与试看识别**：B 站充电（`content_supporter_only`）、试看（`content_preview_only`）、抖音付费（`content_paid_only`／`content_export_required`）、权益元数据异常（`content_access_metadata_invalid`）在归一化之前识别并阻断：`access_decision=blocked`、`formats=[]`。“已购买”标记不是文件导出授权。字段缺失不证明免费。
- **腾讯视频与优酷**：个人单视频、非 DRM 路径，复用固定 yt-dlp 提取器加仓库插件；在原始响应归一化前校验完整时长与分段，缺失 `cdn_url` 或试看返回受限原因；DRM 清单排除；最终以 ffprobe 校验实际文件（时长容差 `max(3 秒, 2%)`）。完整 VIP 下载待真实样本验证，不承诺全部会员画质。
- **微信**：公众号文章作为多资产发现容器，只有无登录、身份映射唯一、公开 clear 的原生视频可下载；视频号登录与页面执行目标统一见[设计 17](17-解析引擎重建.md)，所需页面入口与身份材料仍按设计 17 第 4 节记为能力阻塞。接入代码不等于已验证稳定下载，出现 `decodeKey`、DRM、加密或未知媒体域立即拒绝；无法取得合法 clear 媒体时引导上传自有／已授权文件。
- **其他短视频平台**：按设计 17 的冷启动矩阵验证完整文件；carousel／一帖多视频在多资产模型支持前 fail closed；PeerTube 仅精确实例白名单。
- **Edge Agent（未实施）**：用户设备配对与签名上传只传输用户已合法取得的明文文件，不做采集、解密或代理；复用本地上传的 quarantine、验证与晋升能力。
