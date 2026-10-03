# Web 体验

- 根布局一次挂载身份投影与 TanStack Query 缓存；按 owner、资源、参数隔离查询键，事件驱动定向更新，WebSocket 重连后用 HTTP 快照收敛；后台刷新不清空已有数据，首次加载才用骨架。
- 草稿按 owner 保存在会话内存，不写入 URL、共享存储或遥测；换账号／确认失效时立即隐藏私有内容并清理缓存与在途请求；身份未知且网络异常时原地恢复，不伪造 anonymous。
- 页面状态统一：空状态 `PageEmptyNotice`（Radix/shadcn `Empty`）、首次请求失败 `PageErrorNotice`、已有数据刷新失败 `FeedbackNotice`／Sonner。图标统一 Phosphor。
- 公开页仅 `/` 匿名视图与 `/guide/`（`/self-hosting/`、`/about/` 等说明页随构建产出）；其余页面默认 `noindex`。SEO：`SITE_INDEXABLE` 默认 false，明确为 true 才允许首页与指南被索引；匿名首屏无需 JS 可读，`robots.txt` 屏蔽 `/api` 与 `/health`；结构化数据仅包含真实内容，不含虚构评分或价格；`SITE_URL` 必须为无凭据绝对地址；变更后需重建镜像。

## 内容创作

`/content` 是受保护的普通文字入口，支持 1–8 份事实材料／作者范文、写作目的和三种文体；材料草稿只在当前会话内存保存。历史仅请求 content_creation，数组查询使用重复参数格式。调整材料从账号拥有的固定来源读取，以新任务提交。详情复用既有分析路由，先显示正文，审校、引用、原材料和旧版本展开查看。

人工编辑以当前 report ID 保存新版本，保留未编辑块及旧文件，不调用模型；基准冲突与请求失败保留编辑稿。Markdown／DOCX／HTML 下载使用当前已完成发布版本，不将私有审校记录拼到文章。
