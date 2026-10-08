# 平台与 Provider

本文维护平台目录的职责划分与内容权益识别。各平台的阶梯、出口、身份与内容范围声明见[解析引擎](14-解析引擎.md#11-平台声明)。

## 职责

| 组件 | 职责 |
| --- | --- |
| Provider Registry | 代码中的平台声明：域名、媒体能力、阶梯、出口、identity 与 content_scope |
| Provider Catalog | `provider_catalog_entries`：管理员可见的名称、顺序、显示与启用状态；不控制 URL、提取器或身份 |
| Runner | 执行 yt-dlp 与可信插件，保留 HMAC、SSRF、出口代理、进程组取消与资源上限 |

- API 与 worker 不持有平台 Cookie。
- `GET /api/providers` 展示声明能力，不表示下载已验证。
- YouTube 的 EJS、JS 运行时与 bgutil 版本只用于诊断，版本差异不阻断任务。

## 内容权益识别

默认只处理公开、免费、非 DRM、用户有权保存的内容；身份材料不扩大内容授权。

付费与试看在归一化之前识别并阻断（`access_decision=blocked`、`formats=[]`）：

| 原因码 | 场景 |
| --- | --- |
| `content_supporter_only` | B 站充电专属 |
| `content_preview_only` | 试看片段 |
| `content_paid_only`、`content_export_required` | 抖音付费内容 |
| `content_access_metadata_invalid` | 权益元数据异常 |

- “已购买”标记不是文件导出授权；字段缺失不证明免费。
- 出现 `decodeKey`、DRM、加密或未知媒体域时立即拒绝；无法取得合法 clear 媒体时引导用户导入自有或已授权文件。
- carousel 与一帖多视频在多资产模型支持前 fail closed；PeerTube 只接受精确实例白名单。
- `personal_full` 的完整时长校验以 ffprobe 检查实际文件，容差为 `max(3 秒, 2%)`。
