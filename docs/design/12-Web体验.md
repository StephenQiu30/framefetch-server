# Web 体验

- 根布局一次挂载身份投影与 TanStack Query 缓存；按 owner、资源、参数隔离查询键，事件驱动定向更新，WebSocket 重连后用 HTTP 快照收敛；后台刷新不清空已有数据，首次加载才用骨架。
- 草稿按 owner 保存在会话内存，不写入 URL、共享存储或遥测；换账号／确认失效时立即隐藏私有内容并清理缓存与在途请求；身份未知且网络异常时原地恢复，不伪造 anonymous。
- 页面状态统一：空状态 `PageEmptyNotice`（Radix/shadcn `Empty`）、首次请求失败 `PageErrorNotice`、已有数据刷新失败 `FeedbackNotice`／Sonner。图标统一 Phosphor。
- 公开页仅 `/` 匿名视图与 `/guide/`（`/self-hosting/`、`/about/` 等说明页随构建产出）；其余页面默认 `noindex`。SEO：`SITE_INDEXABLE` 默认 false，明确为 true 才允许首页与指南被索引；匿名首屏无需 JS 可读，`robots.txt` 屏蔽 `/api` 与 `/health`；结构化数据仅包含真实内容，不含虚构评分或价格；`SITE_URL` 必须为无凭据绝对地址；变更后需重建镜像。

## 内置 Skill

本轮保留任务开始前页面、导航、视频／剧本详情、原Skill选择器、语言、可编辑默认提示词、恢复默认、执行提示、状态／历史和报告布局。原页面基线及既有客户端修改保护见[执行计划](../plan/PLAN-内置Skill能力整合.md)。

Skill名称、描述、默认提示词与产出内容可优化；不引入新工作台、双源表单、文本处理弹窗或报告工作流。文章整理通过适合的原文档表单与正式结果契约接入，不要求伪造剧本场景。

MD／DOCX使用保存结果，失败不再次推理。原Markdown reader的代码、换行、表格与长SHA显示缺陷可以最小修复，保持原布局。三端使用正式生成契约，恢复及真实桌面／窄屏验收未完成前不宣称交付通过。
