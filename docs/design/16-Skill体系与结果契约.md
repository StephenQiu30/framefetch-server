# Skill 体系与结果契约

本页定义分析 Skill 的分层、结果契约注册表、通用结构化报告契约和第三方 Skill 引入流程。当前实现与目标分开标注；执行调度见[工作流与平台下载目标](15-工作流与平台下载目标.md)，任务模型与执行器见 [AI 分析](10-AI分析.md)。

## 分层

| 层 | 职责 | 形态 |
| --- | --- | --- |
| Skill（方法） | 怎么分析：领域方法、判断标准、参考材料 | `SKILL.md`（Agent Skills 规范）＋ `references/` ＋固定版本的上游模块，编译成每个任务不可变的指令快照 |
| 结果契约（形态） | 输出长什么样：模型 Schema、严格解析、持久化、报告渲染、API／前端视图 | 契约注册表中的一项；Skill 通过 `video-server-output-contract` 选择 |
| 引擎（调用） | 怎么调用模型：Codex App Server、Claude CLI、HTTP API | 通用适配器，按契约取 Schema 与契约提示，不感知具体 Skill |

同一契约可以被任意多个 Skill 复用；新增 Skill 只要沿用已有契约，就只需新增 Markdown 与测试样例。只有需要新的输出形态时才新增契约。

## 当前实现与问题

视频三种引擎已共用 `ai_cli/prompt.py` 与 `ai_cli/schema.py`，剧本也共用各自的提示模块，引擎层基本通用。问题在契约层：一种契约的类型判定、解析、序列化、报告渲染、API 联合类型与前端视图分散在约 8 处 `isinstance`／条件分支中（`result_types.py`、`result_parser.py`、`repository_serialization.py`、`report.py`、`schemas/analysis_results.py`、前端分析详情等），新增形态需要同步修改所有分支且容易遗漏。数据库对 `result_contract` 与 `result_json.kind` 还有 CHECK 约束。

## 契约注册表（目标）

`services/analysis/contracts/` 为每种契约声明一个规格对象，集中以下能力：

- 标识：契约值、结果 `kind`、允许的输入类型、结果类型。
- 解析：从模型输出严格构造结果，校验语言、时间轴或场景引用、长度与数量上限。
- 持久化：结果与 JSON 文档互转（沿用当前 `kind` 判别）。
- 报告：渲染 Markdown（DOCX 仍由报告 Worker 从 Markdown 渲染）。

模型侧的输出 Schema 与契约提示属于 `integrations/ai_cli`，以同一契约值为键登记，服务层不依赖集成层。现有 4 种契约迁入注册表时行为不变，持久化文档、API 与报告输出逐字节兼容。

## 通用结构化报告契约（目标，首期仅视频）

`structured-report` 让不需要专用结构的 Skill（短视频标题与包装、开头钩子方案、发布文案等）无需新增代码即可上线。结构复用视频文章的章节与证据校验：

- `title`、`summary`；`sections`：每节 `heading`、`body`（受限 Markdown：段落、列表、强调，无原始 HTML、链接与图片）与可选 `evidence`（`start_ms`／`end_ms`／`note`，必须落在视频权威时长内）。
- `limitations`：证据不足或需要人工核验的事项。
- 数量与长度上限固定在契约内；Skill 只能在正文中描述期望的章节，不能改变结构或放宽上限。
- 报告按通用章节渲染，前端提供一个通用视图；Skill 不需要前端分支。

剧本输入首期不开放：剧本分析依赖分块与汇总，通用契约的分块合并规则需另行设计。

## 第三方 Skill 引入

公开 Skill 数量庞大但质量与安全差异很大（公开审计中约三分之一存在提示注入，且常附带脚本），因此只做经审查的精选引入，不接入市场、不在运行时下载。

引入由 `python -m app.workers.skill_import`（在 `backend/` 执行，仅维护者机器联网）完成，规则固定：

1. 只从固定 commit 获取，记录仓库、commit、文件路径与 SHA-256。
2. 许可证白名单：MIT、Apache-2.0、BSD、CC-BY-4.0；无许可证或其他许可证拒绝引入。
3. 只保留 Markdown；脚本、可执行文件、MCP 配置、插件清单、安装脚本和二进制资源一律丢弃且不执行。
4. 静态提示注入扫描（忽略先前指令、调用工具或网络、读取文件或密钥、外发数据等模式）；命中需人工确认后才能写入。
5. 原文不修改地放入 `skills/modules/<来源>/`，附带原许可证；在 `modules/manifest.json` 固定哈希、许可证与选用章节（默认登记全部二级标题，维护者按需收窄），并追加 `NOTICE.md` 条目。已存在且内容不同的文件拒绝覆盖。
6. 由项目自己的产品 Skill 通过 `video-server-modules` 组合上游章节，产品 Skill 决定契约、边界与输出，上游文本只作为方法参考。

更新上游版本必须重新执行上述审查，并补静态样例与真实模型验收后才能发布。

## 首批引入范围

| 领域 | 目标 | 候选来源（待逐项审查） |
| --- | --- | --- |
| 导演／摄影／剪辑拉片 | 增强视觉分析契约下的拉片、节奏与连续性 Skill | DirectorSKILL（已审查过）、cinema-skills（尚不成熟，仅观察） |
| 剧本与故事结构 | 增强剧本分析契约下的审阅 Skill | jtydhr88/screenwriting-skills、zenstory-ai/drama-skills（均已引入部分章节）、zping0731-oss/screenwriting-skills |
| 短视频运营与包装 | 基于 `structured-report` 新增标题包装、开头钩子、发布文案 Skill | coreyhaines31/marketingskills（video）、samjia12/skill-video-script、CiCi2026-7/VideoCraft-Skill |

## 实施阶段

| 阶段 | 交付 | 验收 |
| --- | --- | --- |
| 1 | 契约注册表，现有 4 种契约迁入 | 全量测试通过；历史报告读取、渲染与 API 输出不变 |
| 2 | `structured-report` 契约（视频）与通用前端视图 | 解析与校验单元测试、报告渲染快照、OpenAPI 与前端测试 |
| 3 | 引入工具 | 许可证、脚本丢弃、注入扫描、哈希固定的单元测试 |
| 4 | 首批 Skill 引入与产品 Skill | 每个 Skill 静态样例；每个契约至少一次真实模型验收 |

执行边界保持不变：不执行第三方脚本，运行时不联网获取 Skill，每个任务固定不可变指令快照（SkillWorkflow 步骤日志依赖这一点复用结果）。
