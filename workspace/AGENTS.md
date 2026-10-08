# workspace 文档规范

本文件约束 `workspace/` 中的文档编写与维护。仓库协作规则见 [AGENTS.md](../AGENTS.md)，站点结构与运行方式见 [PROJECT.md](../PROJECT.md#31-文档工作区)。

## 沉淀内容与归档

将后续工作需要复用的产品决策、能力边界、技术约束、执行方案与验证证据写入 `content/`。先阅读相关文档，优先更新已有主题；聊天记录、临时草稿、工具输出与重复总结不单独归档。

| 位置 | 内容 | 命名 |
| --- | --- | --- |
| `content/prd/` | 用户问题、目标、范围、需求与产品验收条件 | `PRD-主题.md` |
| `content/design/` | 架构、接口、状态、约束、失败处理与技术验证条件 | `NN-主题.md`；沿用已有编号，新增主题使用未占用编号 |
| `content/plan/` | 对应需求的工作包、依赖、执行状态、checklist 与验收证据 | `PLAN-主题.md` |

同一规格只维护一处，其他文档通过链接引用。产品范围归 PRD，技术规则归 Design，实施状态与证据归 Plan。根目录及模块 README 保留运行与使用说明。

## 内容要求

- 文档会在网页中用 Editor.js 编辑保存：只使用标题、段落、列表、表格、引用、代码块与分隔线；不在列表项内嵌表格或代码块，不写原始 HTML，否则保存往返会丢失结构（`pnpm test` 会拦截）。
- 使用中文、一个一级标题与连续的标题层级。标题和文件名准确表达主题，沿用项目术语，不使用版本后缀或日期区分同一主题的规格。
- PRD 写清用户任务、目标、范围、功能与非功能需求、可观察的验收条件；范围外事项只记录与当前决策直接相关的边界。
- Design 链接对应产品需求，写清职责、数据与接口、业务规则、异常及恢复、安全与资源约束；只维护本主题的技术规格。
- Plan 链接对应 PRD 与 Design，按需求拆分工作包，写清依赖、交付物、完成条件、当前状态与未完成项。
- 规格写当前有效约定；历史通过 Git 追溯，不加入变更日志或重复叙述历次方案。待实施能力与当前已实现能力必须区分。
- 验证记录写明实际动作、环境或样本、结果、证据位置与覆盖限制。未验证标为未验证，不用计划、静态检查、模拟测试或截图推断真实平台与产品验收完成。
- 不编造数据、进度、性能提升或通过结果；不记录 Secret、Cookie、认证文件、用户私有材料或完整模型输入输出。
- 引用外部方法或结论时附来源，固定依赖标明版本或提交；无法确认的推断与事实分开说明。

## 链接与索引

- 使用标准 Markdown 相对链接，写明 `.md`／`.mdx` 扩展名；跨文档引用优先链接具体章节，标题变化时同步更新锚点引用。
- 新增、删除或重命名文档时，同步更新所属目录的 `README.md` 索引与所有引用。需要指定导航顺序或标题时更新该目录 `_meta.js`。
- `content/` 同时供 Obsidian、GitHub 与 Nextra 使用，不复制为第二份内容，不使用只能在单一工具中解析的双链或绝对本机路径。
- 未完成事项在对应 Plan 中维护，仓库 [BACKLOG.md](../BACKLOG.md) 只链接当前待办，不复制规格或执行证据。

## 提交前检查

确认文档位置、内容职责、关联需求、索引与验证表述符合以上规则，然后在 `workspace/` 执行：

```bash
pnpm check
pnpm build
```

`pnpm check` 校验文档相对链接与章节锚点，`pnpm build` 验证站点可以构建。检查通过只说明文档结构与构建有效；内容准确性与业务验收需要各自证据。

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
