# 帧取文档

帧取服务端的产品需求、系统设计与执行计划。文档统一保存在仓库 `docs/` 下，使用 Markdown 与 Git 管理。将本目录作为已有文件夹打开为 Obsidian 库，或用任意编辑器修改后提交即可。

| 目录 | 内容 |
| --- | --- |
| [产品需求](prd/README.md) | 产品范围、用户任务、目标与产品验收 |
| [系统设计](design/README.md) | 技术架构、业务规则与验证条件 |
| [执行计划](plan/README.md) | 工作包、依赖、checklist 与执行证据 |

编写或更新文档时，遵循 [文档规范](AGENTS.md)，按主题归档并同步索引与验证证据。

协作与工程规范保留在仓库根目录：

- [AGENTS.md](../AGENTS.md)：协作、修改原则与交付
- [PROJECT.md](../PROJECT.md)：技术栈、目录、接口链路与命名
- [design.md](../design.md)：界面视觉标准
- [SECURITY.md](../SECURITY.md)：安全边界
- [CONTRIBUTING.md](../CONTRIBUTING.md)：本地检查与提交规范

Obsidian 配置保留在 `.obsidian/app.json`：使用标准 Markdown 相对链接，并在文件重命名时更新链接。个人界面状态与插件配置不入库。

文档检查：在仓库根目录执行 `node backend/scripts/check_docs.mjs`。
