# Skill 体系与结果契约

本页定义分析 Skill 的分层、结果契约注册表、通用结构化报告契约和第三方 Skill 引入流程。当前实现与目标分开标注；执行调度见[工作流与平台下载目标](15-工作流与平台下载目标.md)，任务模型与执行器见 [AI 分析](10-AI分析.md)。

## 分层

| 层 | 职责 | 形态 |
| --- | --- | --- |
| Skill（方法） | 怎么分析：领域方法、判断标准、参考材料 | `SKILL.md`（Agent Skills 规范）＋ `references/` ＋固定版本的上游模块，编译成每个任务不可变的指令快照 |
| 结果契约（形态） | 输出长什么样：模型 Schema、严格解析、持久化、报告渲染、API／前端视图 | 契约注册表中的一项；Skill 通过 `video-server-output-contract` 选择 |
| 引擎（调用） | 怎么调用模型：Codex App Server、Claude CLI、HTTP API | 通用适配器，按契约取 Schema 与契约提示，不感知具体 Skill |

同一契约可以被任意多个 Skill 复用；新增 Skill 只要沿用已有契约，就只需新增 Markdown 与测试样例。只有需要新的输出形态时才新增契约。

## 当前实现

结果契约注册表位于 `services/analysis/rules/contracts.py`，集中登记契约值、结果 kind、输入类型和结果类型；解析、持久化与报告渲染在各自层内以这些标识分派。模型侧 Schema 与提示位于 `integrations/ai_cli`；API 的判别联合和前端结果视图仍须随新增契约同步更新，由契约测试检查覆盖。注册表不意味着添加任意新输出形态都无需修改 API 或前端。

当前包含五种契约：`video-visual-analysis`、`video-article`、`screenplay-analysis`、`screenplay-rewrite`、`structured-report`。引擎按契约调用，产品 Skill 只选择方法和章节，不改变固定 Schema。

## 通用结构化报告契约（已实现，仅视频）

`structured-report` 供标题包装、开头钩子、发布文案等不需要专用结构的 Skill 复用：

- `language`、`title`、`summary`、`sections`、`limitations`。
- 每节包含唯一 `id`、`heading`、`body`、`items` 和 `evidence`；文本是纯文本，由报告渲染器转义。模型不能嵌入可执行 HTML、链接、图片或自行定义 Markdown 排版。
- 每节证据包含 `start_ms`、`end_ms`、`note`，必须落在权威视频时长内；没有证据时可为空。
- 1–16 节，每节最多 20 条候选、12 条证据，全报告最多 12 条局限；条目与局限最长 1,000 字符。具体文本上限由模型与严格解析器共同固定，Skill 不得放宽。
- 已接通模型 Schema、严格解析、数据库 CHECK、结果持久化、Markdown/DOCX 报告、OpenAPI 与通用前端视图。

剧本输入不开放此契约：剧本分析依赖分块与汇总，通用契约的分块合并规则需另行设计。

## 第三方 Skill 引入

第三方 Skill 可能含工具调用、项目工作流和不适用的输出要求，因此只引入经逐项审查的 Markdown，不接入市场、不在运行时下载。静态扫描只提供审查线索，不能代替逐段检查。

引入由 `python -m app.workers.skill_import`（在 `backend/` 执行，仅维护者机器联网）完成，规则固定：

1. 只从固定 commit 获取，记录仓库、commit、文件路径与 SHA-256；`--path` 支持 Skill 目录或单个 Markdown 文件，显式路径不得经过软链接。
2. 许可证白名单：MIT、Apache-2.0、BSD、CC-BY-4.0；无许可证或其他许可证拒绝引入。
3. 只保留 Markdown；脚本、可执行文件、MCP 配置、插件清单、安装脚本和二进制资源一律丢弃且不执行。
4. 静态提示注入扫描（忽略先前指令、调用工具或网络、读取文件或密钥、外发数据等模式）；命中需人工确认后才能写入。
5. 原文不修改地放入 `skills/modules/<来源>/`，附带原许可证；在 `modules/manifest.json` 固定哈希、许可证与选用章节（默认登记全部二级标题，维护者按需收窄），并追加 `NOTICE.md` 条目。已存在且内容不同的文件拒绝覆盖。
6. 由项目自己的产品 Skill 通过 `video-server-modules` 组合上游章节，产品 Skill 决定契约、边界与输出，上游文本只作为方法参考。

更新上游版本必须重新执行上述审查，并补静态样例与真实模型验收后才能发布。

## 首批接入

此次新增 9 个固定版本模块，挂载于以下 5 个产品 Skill；完整原文、许可证、SHA-256 与选用二级标题见 `skills/modules/manifest.json`，用途和扫描复核见 `skills/NOTICE.md`。

| 产品 Skill | 本次采用的方法 | 结果契约 |
| --- | --- | --- |
| 导演拉片 `director-breakdown` | drama-skills 镜头目的、摄影问题、轴线和调度 | video-visual-analysis |
| 剪辑节奏 `editing-rhythm-review` | drama-skills 切点工艺、marketingskills 剪辑解剖 | video-visual-analysis |
| 连续性审阅 `continuity-quality-review` | drama-skills 轴线、屏幕方向和可见状态衔接 | video-visual-analysis |
| 剧本结构 `screenplay-structure-review` | 保留既有结构/场景方法，追加前提主题和 Truby 诊断 | screenplay-analysis |
| 短视频包装 `short-video-packaging` | marketingskills 钩子、视觉表达与平台呈现参考 | structured-report |

短视频包装按内容定位、标题备选、封面文字、开头钩子和发布文案输出五节草稿；事实绑定原视频证据，拟新增文案与编辑动作明确标注。平台未指定时提供通用版并标记待确认，不据此发布内容或生成成片。

上游章节先编译，随后加载产品 Skill 正文和本地 references。产品正文明确约束适用范围：不执行上游脚本、项目文件操作或制作流程；视频不判断未经验证的音频；上游人口、算法、触达、发布时间和固定镜长说法不作为当前事实或验收门槛；剧本不强制套用页码或结构公式。选用章节以外的正文不注入模型。

## 成稿写作规范

报告是 Skill 的最终交付物，文字须读起来像经过编辑的专业稿件，而不是字段释义或模型输出。写作要求分三层维护：

| 层 | 位置 | 内容 |
| --- | --- | --- |
| 共享规范 | `skills/shared/report-writing.md` | 项目自有。结论先行、段落与句式、事实／判断／建议分层、标题与条目写法、需删除的套话、中文排版、交付前通读 |
| 契约写法 | `skills/shared/screenplay-coverage-writing.md` 与各契约提示 | 字段在渲染报告中的位置与写法；剧本审稿 7 个 Skill 共用一份 |
| Skill 重点 | 各 `SKILL.md` 的“成稿写法” | 本 Skill 的标题、导语与关键字段应当回答什么 |

`video-server-references` 可引用 `references/<名>.md`（Skill 自有）或 `shared/<名>.md`（项目自有、多 Skill 复用）；`shared/` 不含 `SKILL.md`，不会被注册为 Skill。

共享规范参照两类成熟写法：专业审阅报告（审稿 coverage、拉片笔记）的严谨，以及公众号深度稿的可读性——导语给结论、小标题可扫读、段落一个信息单元、以具体行为代替形容词、事实与判断分开。

同时固定引入两个 MIT 写作模块作为自查清单：`humanizer-zh`（op7418/Humanizer-zh，去除模板化表达的 A–F 模式与交付前核对）和 `zh-copywriting-guidelines`（sparanoid/chinese-copywriting-guidelines，中文空格、标点与专有名词）。它们只检查 Skill 自己写的报告文字，不用于评判被分析的剧本台词或画面文字，也不得为了“具体”补造事实；`screenplay-rewrite` 只加载排版规则，并保留人物有意为之的口语表达。

渲染器同步调整为文档版式：视频报告使用中性章节名（核心判断、内容如何展开、逐镜证据、值得回看的片段、修改建议、需保持一致的视觉资产、分析口径与局限），适用于全部视觉 Skill；剧本审稿报告保留字段中的分段，按“审稿结论 → 故事概览 → 结构与节奏 → 人物 → 对白 → 逐场附录”排版，英文结果使用英文章节名；改写报告按目标语言本地化，并以场次序号代替内部场景 ID。

写作规范改变了每个 Skill 的指令快照哈希，只影响新建任务；已有任务沿用创建时的快照。报告版式变化只影响新发布的报告。

## 验证边界

阶段 1–3 的契约重构、通用报告和引入工具已实现，阶段 4 的精选模块与五个产品 Skill 已接通。目录发现、契约绑定、章节排除、单文件许可证继承、软链接拒绝及包装样例的解析/持久化/API/报告链路由自动化测试覆盖。

2026-09-29 本地验证：后端 1,996 项通过，1 项上传大小边界测试因未配置隔离 MinIO 端点跳过；Ruff 与 mypy 通过。前端 510 项通过，format、lint、类型检查、生产构建通过；从当前源码导出 OpenAPI 后重新生成客户端无差异。16 个模块的哈希与选定章节均可编译，原有 7 个模块的固定版本与章节未变。

同日使用本机已登录的 Codex App Server 与 `gpt-6-sol` 实际调用：`short-video-packaging` 和 `director-breakdown` 分别分析 6 秒、两段色块的无声合成视频，`screenplay-structure-review` 分析自编两场短剧本。三者均通过严格解析、结果持久化往返、API 判别联合校验和 Markdown 渲染；包装报告返回五个预期章节、9 条时间证据并注明音频、平台、受众及切点精度局限。

这证明三种涉及契约的有限真实模型调用可用，不证明模型对真实作品的分析质量，也不替代长视频、长剧本分块汇总、真实业务 Workflow 和人工产品验收。验证未经过任务入队、报告发布或浏览器完整业务链路，不据此标记为全面发布验收。

执行边界保持不变：不执行第三方脚本，运行时不联网获取 Skill，每个任务固定不可变指令快照（SkillWorkflow 步骤日志依赖这一点复用结果）。
