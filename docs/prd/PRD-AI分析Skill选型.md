# Framefetch AI 分析能力与 Skill 选型调研

## 1. 结论

建议采用组合接入：reelbench 的 video-shots 补实测拉片，ECC article-writing 写文章初稿，baoyu 系列整理并输出微信 HTML，screenwriting-skills 与 drama-skills 补剧本分析。三条主线都保留，小说/IP 全量拆文、Codex 配图、翻译和润色作为后续可选能力。

这批候选大多可以使用现有 Codex 额度，不需另外购买模型 API。真正的成本在受控脚本、原生产物、阶段恢复和三端展示；安装一个 Skill 不等于产品已经拥有可交付能力。建议先做 Server＋Web 的真实样本闭环，再同步 Electron 和 App。

**本报告是选型建议，尚未安装到产品，未进行真实模型或三端验收。** 已做 12 个候选仓库的源码核查，以及 video-shots 的确定性试跑。不能据此声称拉片质量、中文成稿质量或配图可用性已经通过。

## 2. 方法、范围与证据

使用用户指定的 pm-market-research 插件的 competitor-analysis 方法，按任务、能力、成熟度、持续成本、替代方案和帧取适配比较。五个核心来源为 reelbench、baoyu、ECC、screenwriting、drama；七个相邻来源为 oh-story、best-skills、wechat-article-skills、Humanizer-zh、video-recap、md2wechat、screen-creative。

证据时间为 2026-10-08。检查公开 GitHub 页面、浅克隆固定提交、LICENSE、关键 SKILL.md、脚本和引用资源。GitHub 匿名 API 限流，精确实时星数未取得；关注度来自 GitHub 页面近似显示。没有继承旧 PRD 的星数或直接把其结论视为本轮事实。

成熟度看完整流程、示例／脚本检查、维护活跃度和依赖明确程度。星数仅表示关注度；主仓星数不等于单个技能质量。没有足够独立资料估算市场份额、采纳率或质量提升百分比。

本轮按用户最新要求纳入剧本分析。已有[影视 Skill 接入 PRD](PRD-影视Skill接入.md)只围绕视频并排除剧本研读，与本次范围不同；正式实施前应统一规格。本轮不删除已有入口、历史报告或并行改动。

## 3. 当前项目：有基础，但完整 Skill 运行仍有缺口

源码正式注册六个入口：video-review 成片审阅、video-breakdown 素材拆解、screenplay-analysis 剧本审阅，以及 article-format、wechat-format、xhs-format 文档整理。这表明已有骨架，不表明分析质量已达标。

可以复用：视频下载／上传、剧本文档导入、全文分块、源单元覆盖和引用校验、FFmpeg 取帧、宿主 Codex App Server、Temporal 工作流、取消和未知回执保护、对象存储、结果校验、MD／DOCX 导出。

宿主 AI Worker 探针返回 local-codex、gpt-6.1-sol、Codex CLI 0.159.2、storage=ready；它证明运行依赖就绪，不证明真实分析任务完成。

| 当前实现 | 接入影响 |
| --- | --- |
| Loader 只接受产品专用 metadata，目录仅允许 SKILL.md 和 references，编译 Markdown 片段 | 上游 scripts、assets 和不同 frontmatter 不能直接原样放入 |
| Codex strict config、禁用 plugins／web search，清空 MCP 后加入观察工具 | 不能假定外部 Skill、脚本或生图已经可见 |
| 视频观察工具线路明确禁止模型自行运行 shell、FFmpeg／FFprobe | video-shots 的机械步骤需受控执行器承载，不能只换提示词 |
| 正式结果使用项目 schema，导出 MD／DOCX | shots.json、HTML、图片和多文件文章要增加产物收集与展示 |
| 当前公众号入口主要整理文档，没有视频到文章的正式一键串联入口 | 写稿、来源复核、排版、预览需明确工作流 |
| 剧本已有分块和覆盖校验 | 可复用；小说章节索引不能直接当剧本场景索引 |
| 本机有 Node、FFmpeg、FFprobe、Codex，PATH 中没有 Bun | reelbench 可机械运行；baoyu 脚本环境尚不完整 |

检查的源码包括 backend/app/services/analysis/skills/{registry,loader}.py、modules/README.md、backend/app/integrations/ai_cli/{codex_app_server_client,codex_policy,prompt}.py、analysis_execution/{video_executor,screenplay_executor}.py。对应规格见 [AI 分析](../design/09-AI分析.md)、[报告导出](../design/10-报告导出.md)与[工作流编排](../design/13-工作流编排.md)。

## 4. 十二个候选来源

适配等级针对帧取，而非安装命令：低为纯文本方法与既有材料可复用；中为脚本、依赖或产物适配；高为另接 API、复杂状态或长篇流水线。它们仍共享第 7 节的公共接入工作。

| 来源 | 任务与成熟信号 | 许可／关注度 | 依赖和费用 | 建议 |
| --- | --- | --- | --- | --- |
| [reelbench / video-shots](https://github.com/eternityspring/reelbench-skills) | 逐镜拉片，机械检查、示例与自测 | Apache-2.0／868 星 | Node＋FFmpeg／FFprobe；脚本无独立模型 Key，视觉仍消耗 Agent 额度 | 第一批；中；直接补切点与时长可信度 |
| [baoyu-skills](https://github.com/JimLiu/baoyu-skills) | 整理、微信 HTML、翻译、配图，完整脚本与引用 | MIT／约 26.4k | Agent＋Bun/npm，生图另有运行要求 | 第一批整理排版；中；配图单独验证 |
| [ECC article-writing](https://github.com/affaan-m/ecc/tree/main/skills/article-writing) | 来源材料转长文，纯文本方法 | MIT／主仓约 275k | 默认文风无新脚本/API；范文风格涉及 brand-voice | 第一批；低；中文成稿效果待测 |
| [screenwriting-skills](https://github.com/jtydhr88/screenwriting-skills) | 26 个剧作技能及参考资料 | MIT／约 1.6k | 文本 Agent，同级引用资源需一起保留 | 第一批剧本诊断；低至中 |
| [drama-skills](https://github.com/zenstory-ai/drama-skills) | 审稿、原著、改编、分镜、制作全流程 | MIT／约 2.6k | 分析用 Agent／Python，媒体生产另有供应商 | 第一批 review；中；不整体接制作链 |
| [oh-story-claudecode](https://github.com/zenstory-ai/oh-story-claudecode) | 小说长短篇拆文、情绪、人物、续跑 | MIT／约 7.4k | Agent＋Python，多阶段多文件，长篇额度大 | 小说/IP 候选；中高 |
| [best-skills wechat-article-writer](https://github.com/xstongxue/best-skills/tree/main/skills/wechat-article-writer) | 中文文风、标题、图示与可选上传 | Apache-2.0／主仓约 3.0k | 检索需网络，图示 draw.io，上传微信凭据 | 中文写作 A/B 备选；中 |
| [wechat-article-skills](https://github.com/aiworkskills/wechat-article-skills) | 写稿、审稿、排版、配图、发布九技能 | Apache-2.0／667 星 | API 或 Agent 代写，配置引导与跨技能依赖 | 本地排版备选；整套中高 |
| [Humanizer-zh](https://github.com/op7418/Humanizer-zh) | 中文去空话／模板表达，保留作者声音 | MIT／约 19.1k | 纯文本 Agent，多一次编辑调用 | 可选润色；低；不是事实或 AI 来源检测 |
| [video-recap-skills](https://github.com/zenstory-ai/video-recap-skills) | 场景＋ASR＋VLM，解说成片 | MIT／555 星 | 新素材完整理解绑定 MiMo Key | 音画联合参照；非 Codex 低成本首选 |
| [md2wechat-skill](https://github.com/geekjourneyx/md2wechat-skill) | 排版、草稿、发布 CLI | Source Available／BSL 派生 | 外部排版 API 与免费 AI 模式不同 | 非默认内置，许可和远端依赖更多 |
| [screen-creative-skills](https://github.com/VanGong1999/screen-creative-skills) | 中文剧本/IP 评估、人物与剧情，31 类技能 | MIT／445 星 | 主要文本方法，部分检索需工具 | 方法对照；部分偏模板评分，非第一选择 |

## 5. 第一批推荐的具体适配

### 5.1 拉片：video-shots

分析已经存在的片子，不是从剧本生成未来拍摄分镜。代码测切点、时长和帧差运动，Agent 看联系表填景别、画面和运镜，再交脚本检查。产物是 shots.json、track.json、Markdown、HTML、关键帧与联系表。[固定 Skill](https://github.com/eternityspring/reelbench-skills/blob/1b51af897b6a57556b85dfe96e0427e231b4b613/skills/video-shots/SKILL.md)

它降低模型编造时间的空间，但检测仍会漏切／多切；帧差不能充分区分主体与机位运动，质量门不证明全部视觉判断正确。没有 ASR，无烧录字幕时不能提供完整对白分析。长片先选段，控制视觉调用。

接入：原样完整目录，执行器提供只读输入、受控命令与工作区，保存原生产物及产品展示索引。切镜失败不回退模型估时。HTML 不含视频，须映射原片、关键帧和选段时间偏移。

### 5.2 文章初稿：ECC article-writing

用笔记、研究或素材观察生成长文，不绑定新模型 API；要求事实有来源。适合用拉片结果写视听解读，但不是微信渲染器，中文文章质量还需实测。[固定 Skill](https://github.com/affaan-m/ecc/blob/ef648e01899ba3e8dc6371642deaaf64b4477775/skills/article-writing/SKILL.md)

默认文风成本低。用户范文定文风路线要求先用 brand-voice，只接 article-writing 不能承诺完整范文提取；先使用默认文风，或另核查依赖。主仓高星不代替此 Skill 的评测。

接入：传读者、目的、篇幅、可引用材料，生成 MD 后做来源复核，再排版。缺台词或声音依据的视频写画面／视听解读，不编人物原话、完整剧情或外部背景。

### 5.3 整理与公众号 HTML：baoyu

先接 format-markdown 和 markdown-to-html，翻译按需。DOCX 可继续导出，但公众号成品另需微信 HTML、图片与预览。[排版 Skill](https://github.com/JimLiu/baoyu-skills/blob/1567581c26ec29f4216c6e6835415bf30343b0e3/skills/baoyu-markdown-to-html/SKILL.md)

依赖要算全：format-markdown 使用 unified/remark 等包；markdown-to-html 依赖 baoyu-md、baoyu-chrome-cdp，Mermaid 转图涉及浏览器。预装固定 Bun/npm，不能生产时临时 npx 下载。先验证普通文章、不含 Mermaid 的路线。

article-illustrator 配图单独评估。上游支持原生 imagegen 和 Codex CLI 包装器，后者在 packages/baoyu-codex-imagegen；只复制技能目录会缺它。包装器声明使用 Codex 登录态，帧取 Worker 权限、图片收集、未知回执仍待验证。[调用说明](https://github.com/JimLiu/baoyu-skills/blob/1567581c26ec29f4216c6e6835415bf30343b0e3/skills/baoyu-article-illustrator/references/codex-imagegen.md)

接入：先交付可预览 HTML，图片生成独立选择并计量。既有 PRD 倾向 Codex 生图，本调研不静默改为默认关键帧配图。微信后台粘贴、图片上传、最终效果必须实测。

### 5.4 剧本诊断：screenwriting-skills

先选 sw-story-structure、sw-character-conflict、sw-scene-craft、sw-dialogue、sw-premise-theme，补结构、人物、场景功能和对白诊断。参考文件和 sw-workflow 等同级引用必须一起保留。[固定技能目录](https://github.com/jtydhr88/screenwriting-skills/tree/51115f18d160aa8b2ac5813e4432b6f0b425358f/plugins/screenwriting/skills)

接入：复用全文材料化、分块、源引用和覆盖检查，按目标加载完整方法。理论用于诊断，不机械要求所有作品满足同一幕数或页数。输出问题、证据、影响、目标，不能只打分。

### 5.5 短剧审阅：drama-skills

short-drama-review 能对点名的独立文件审查，产出位置、证据、影响和修订目标，适合行动因果、节奏、对白与信息揭示；不需一起接生图或视频生产。上游偏好独立 reviewer，没有独立审查者应标注自检，本轮没有启动多代理。[审阅 Skill](https://github.com/zenstory-ai/drama-skills/blob/c2426e03c0e7722bebcc6a488b6658dc38c65ac3/skills/short-drama-review/SKILL.md)

short-drama-novel-analyze 可独立做小说／多集散稿的索引、逐章功能、剧情、人物和改编候选，更适合原著改短剧，不直接替代电影剧本格式。建议 review 第一批、原著/IP 第二批。[原著 Skill](https://github.com/zenstory-ai/drama-skills/blob/c2426e03c0e7722bebcc6a488b6658dc38c65ac3/skills/short-drama-novel-analyze/SKILL.md)

## 6. 备选方案与条件

### 6.1 小说与长篇原著

oh-story long-analyze 有章节、情绪、角色关系、文风、落盘缓存和续跑；short-analyze 适合短篇机制。多文件与阶段恢复令长篇成本高于一次剧本诊断。映射产品编排时避免两套状态互相覆盖；节选只能分析节选，不凭模型记忆补原文。[长篇 Skill](https://github.com/zenstory-ai/oh-story-claudecode/blob/87f2e7e223077023e0b0c0796d5704c1b0b02088/skills/story-long-analyze/SKILL.md)

### 6.2 中文公众号备选

best-skills 更贴近中文公众号，有风格、标题、图示及可选上传；默认检索、爆款表达、draw.io 和发布增加工具。与 ECC 用同材料做 A/B，比较采纳和修改耗时，再选择。[固定源码](https://github.com/xstongxue/best-skills/tree/9aa4e555950da6e43e7d98c5f0c7b70264204850/skills/wechat-article-writer)

aiworkskills 支持 write.py prompt 只输出 prompt JSON、由当前 Agent 写稿，不能笼统说必须另付模型费；完整 Skill 有配置引导和跨技能依赖。其 formatting 脚本声明零依赖纯本地，可作缺 Bun 时的脚本备选，完整 Agent 流程仍要配置。[写作](https://github.com/aiworkskills/wechat-article-skills/tree/ca036f75f4bac4fcefe6eaedd8d22d97bf8c92ca/skills/aws-wechat-article-writing)、[排版](https://github.com/aiworkskills/wechat-article-skills/tree/ca036f75f4bac4fcefe6eaedd8d22d97bf8c92ca/skills/aws-wechat-article-formatting)

Humanizer-zh 可末尾润色，不能证实事实或判断作者来源；先按需运行，避免默认增加调用。[说明](https://github.com/op7418/Humanizer-zh/tree/f4518a8eab97b8bfebc66a89d34320a89bef6930)

### 6.3 非首选

video-recap 理解阶段绑定 MiMo ASR/VLM，跳过 ASR 仍需 VLM Key；缓存复用不代表新素材免费理解。可参考音画融合设计，非现有 Codex 登录态路线。[理解源码](https://github.com/zenstory-ai/video-recap-skills/blob/539168622918e058bd250c793b82f043eced31e0/skills/video-understanding/SKILL.md)

md2wechat 现在有明确 Source Available License，不能沿用旧文档“许可不明”或标为 MIT。个人非商业等许可条件和远端 API 增加引入约束；已有 MIT 本地替代，故不默认内置。[许可原文](https://github.com/geekjourneyx/md2wechat-skill/blob/fce5fa3b4494fded0bdb942d50d17485281055d6/LICENSE)

screen-creative 覆盖广，但部分报告按思想性／艺术性／观赏性模板评分，需核查证据与真实编辑价值。最新提交 2026-05-26，维护弱于主要候选。[剧本评估](https://github.com/VanGong1999/screen-creative-skills/blob/6ced54f40c864e13717707bad887c22cd732ec41/category/evaluation/script-evaluator/SKILL.md)

## 7. 最小产品接入

| 产品动作 | 自动流程 | 最小成果 |
| --- | --- | --- |
| 拉片 | 范围 → 切镜／抽帧 → Agent 标注 → 检查 → 保存 | 可回看镜头表、MD、JSON、时间／覆盖依据，交互 HTML 逐步适配 |
| 写成公众号文档 | 复用拉片／文本 → 写稿 → 来源复核 → 整理 → HTML | 标题、摘要、实质正文、MD、微信 HTML、预览／复制 |
| 剧本分析拆解 | 全文／节选 → 源单元 → 剧作方法／review → 覆盖与引用检查 | 梗概、结构、人物、场景功能、对白、优先修订，MD／DOCX |

“一键”是以已保存的读者、目的、篇幅和主题默认值串联，而非让用户逐个选 Skill。必要输入在创建前收集；失败保留已成功成果并从明确失败的阶段恢复，未知回执不自动重发。配图、编辑确认和发布是不同动作，不混入首版完成条件。

工程建议：固定上游提交、完整引用和 LICENSE／NOTICE；方法原样保留，中文产品 metadata 在目录外。每个候选明确允许命令、参数、目录、网络与资源预算，执行器承载脚本，不全局开放任意命令。保留上游 MD／JSON／HTML／图片，建立展示索引，不再只截取几段方法。

继续复用宿主 Worker、Temporal 和 Step。HTML 隔离预览，映射受控资源。Web／Electron 可适配交互报告，Flutter 当前不用 WebView，要原生镜头表、文章和分享。契约变化按 Server → Frontend → Electron 同步／App 白名单快照验证。初期单重任务，避免长片、长篇和生图争用额度。

## 8. 成本与用量

以下为源码检查后的单人开发估计，假设熟悉项目、基础服务可用；不是已发生工时、报价或交付承诺。模型质量与三端细节会改变范围。

| 工作 | 估计增量 | 不确定性 |
| --- | --- | --- |
| 公共执行／成果接入 | 3–5 人日 | 原生加载或受控脚本、成果回收、取消、固定依赖 |
| 拉片首版 | 3–5 人日 | 公共能力后；暗场／叠化、区间偏移、路径 |
| 中文文章＋微信 HTML | 2–4 人日 | 公共能力后；Bun/npm、事实复核、微信实测 |
| 剧本审阅首版 | 2–4 人日 | 全文覆盖可复用；引用闭包与跨块质量 |
| 三端同步／验收 | 3–5 人日 | 成果稳定后；App 原生呈现与冻结契约 |
| Codex 配图 | 另计 2–4 人日 | 包装器、权限、确认、额度与回执未验证 |
| 原著/IP 全量拆解 | 另计 3–6 人日 | 索引、缓存、续跑、多文件、长上下文 |

三条主线连同公共能力和三端基础交付粗估 13–23 人日；可先做 Server＋Web 最小闭环。低成本来自复用方法与现有模型服务，不意味着完整产品适配只需几小时。

| 持续成本 | 控制方式 |
| --- | --- |
| Skill | 主要候选 MIT／Apache-2.0，无需另买 Skill 订阅，保留许可材料 |
| 模型 | 现有 Codex 额度；观察、写稿、复核均有用量，不能写免费无限 |
| 图片 | 按需独立启用，计量额度和耗时，以 Worker 实测为准 |
| CPU／存储 | 选段、单重任务，FFmpeg／关键帧／联系表随素材增长 |
| 外部平台 | 首版不依赖微信发布、MiMo 或另付费排版服务 |
| 维护 | 固定提交、锁依赖、同一组样本，升级先核查差异 |

每阶段记录调用次数、可获得的 token、耗时、镜头／图数、失败与重试；不为未运行样本编人民币单价。写文章复用拉片，排版不重复跑视觉模型，翻译与润色按需。

## 9. 验收建议

| 能力 | 样本 | 可观察完成条件 |
| --- | --- | --- |
| 拉片 | 快切、长镜、暗场／叠化 | 对照人工镜头表，记录漏切／多切／偏差，可回看；跳过检查不算通过 |
| 公众号 | 至少 3 份同材料，ECC 和中文备选 A/B | 实质事实／引语可追溯，人工评文风／信息量／修改时间，微信后台真实粘贴 |
| 剧本 | 短剧单集、电影节选、长于单次上下文剧本 | 覆盖与引用正确，问题有影响和目标，人工查跨块因果及后文反证 |
| 恢复 | 脚本失败、模型中断、取消、迟到 | 阶段明确，成果保留，未知回执不自动重发 |
| 三端 | 同身份／素材／结果 | Web／Electron 可读可导出，App 原生可读可分享，不用 Web 截图代替 App 验收 |

先建立人工镜头表和编辑耗时基线，再定提升目标。第一批做三条主线；第二批配图、翻译、润色、原著/IP。音频／字幕影响分析上限，但旧 PRD 排除它们，本轮只说明缺口，不擅自安装转写模型。自动发布、视频生成、配音和剪辑不作为三项分析任务的依赖。

## 10. 本轮验证记录

| 动作 | 实际结果 | 覆盖限制 |
| --- | --- | --- |
| 项目重启 | 当时现有七个业务容器完成 restart，有探针的服务均 healthy；宿主 AI Worker 重启并 doctor ready | 既有镜像重启，不等于重建同步源码；基础服务未重建 |
| HTTP | API live／ready、Web、Swagger、文档站点当时均 200 | 文档首次超时，编译后复查通过；随后并行任务移除了文档站点，非当前保留入口 |
| video-shots 自测 | 449 项断言通过 | 上游受控夹具，只证明脚本逻辑 |
| 合成视频 | 6 秒、25fps、320×180、三段纯色；2 秒／4 秒切点，共 3 镜，运动为 0 | 不代替真实影片检测或视觉判断 |
| frames／sheet | 6 张关键帧、1 张联系表 | 未调模型填景别／运镜，未完成真实素材质量检查 |
| 正式安装／外部 API | 未执行 | 未新增产品 Skill，未调用微信、MiMo 或生图 API |

## 11. 固定源码与许可

用于复核调研，不表示产品已经依赖这些版本。时间为仓库最新提交时间，不是每个 Skill 独立更新时间。许可证根据各仓库实际 LICENSE 核查。

| 仓库 | 提交 | 提交时间 | 许可 |
| --- | --- | --- | --- |
| [eternityspring/reelbench-skills](https://github.com/eternityspring/reelbench-skills) | [1b51af897b6a57556b85dfe96e0427e231b4b613](https://github.com/eternityspring/reelbench-skills/tree/1b51af897b6a57556b85dfe96e0427e231b4b613) | 2026-09-21T16:12:42+08:00 | [Apache-2.0](https://github.com/eternityspring/reelbench-skills/blob/1b51af897b6a57556b85dfe96e0427e231b4b613/LICENSE) |
| [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills) | [1567581c26ec29f4216c6e6835415bf30343b0e3](https://github.com/JimLiu/baoyu-skills/tree/1567581c26ec29f4216c6e6835415bf30343b0e3) | 2026-09-10T10:13:43-05:00 | [MIT](https://github.com/JimLiu/baoyu-skills/blob/1567581c26ec29f4216c6e6835415bf30343b0e3/LICENSE) |
| [affaan-m/ecc](https://github.com/affaan-m/ecc) | [ef648e01899ba3e8dc6371642deaaf64b4477775](https://github.com/affaan-m/ecc/tree/ef648e01899ba3e8dc6371642deaaf64b4477775) | 2026-10-01T21:01:14-05:00 | [MIT](https://github.com/affaan-m/ecc/blob/ef648e01899ba3e8dc6371642deaaf64b4477775/LICENSE) |
| [zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills) | [c2426e03c0e7722bebcc6a488b6658dc38c65ac3](https://github.com/zenstory-ai/drama-skills/tree/c2426e03c0e7722bebcc6a488b6658dc38c65ac3) | 2026-10-03T01:56:29-07:00 | [MIT](https://github.com/zenstory-ai/drama-skills/blob/c2426e03c0e7722bebcc6a488b6658dc38c65ac3/LICENSE) |
| [jtydhr88/screenwriting-skills](https://github.com/jtydhr88/screenwriting-skills) | [51115f18d160aa8b2ac5813e4432b6f0b425358f](https://github.com/jtydhr88/screenwriting-skills/tree/51115f18d160aa8b2ac5813e4432b6f0b425358f) | 2026-10-02T21:34:42-04:00 | [MIT](https://github.com/jtydhr88/screenwriting-skills/blob/51115f18d160aa8b2ac5813e4432b6f0b425358f/LICENSE) |
| [zenstory-ai/oh-story-claudecode](https://github.com/zenstory-ai/oh-story-claudecode) | [87f2e7e223077023e0b0c0796d5704c1b0b02088](https://github.com/zenstory-ai/oh-story-claudecode/tree/87f2e7e223077023e0b0c0796d5704c1b0b02088) | 2026-10-03T01:56:23-07:00 | [MIT](https://github.com/zenstory-ai/oh-story-claudecode/blob/87f2e7e223077023e0b0c0796d5704c1b0b02088/LICENSE) |
| [xstongxue/best-skills](https://github.com/xstongxue/best-skills) | [9aa4e555950da6e43e7d98c5f0c7b70264204850](https://github.com/xstongxue/best-skills/tree/9aa4e555950da6e43e7d98c5f0c7b70264204850) | 2026-09-13T13:04:40+08:00 | [Apache-2.0](https://github.com/xstongxue/best-skills/blob/9aa4e555950da6e43e7d98c5f0c7b70264204850/LICENSE) |
| [aiworkskills/wechat-article-skills](https://github.com/aiworkskills/wechat-article-skills) | [ca036f75f4bac4fcefe6eaedd8d22d97bf8c92ca](https://github.com/aiworkskills/wechat-article-skills/tree/ca036f75f4bac4fcefe6eaedd8d22d97bf8c92ca) | 2026-09-23T09:36:05+08:00 | [Apache-2.0](https://github.com/aiworkskills/wechat-article-skills/blob/ca036f75f4bac4fcefe6eaedd8d22d97bf8c92ca/LICENSE) |
| [op7418/humanizer-zh](https://github.com/op7418/humanizer-zh) | [f4518a8eab97b8bfebc66a89d34320a89bef6930](https://github.com/op7418/humanizer-zh/tree/f4518a8eab97b8bfebc66a89d34320a89bef6930) | 2026-09-23T10:24:26+08:00 | [MIT](https://github.com/op7418/humanizer-zh/blob/f4518a8eab97b8bfebc66a89d34320a89bef6930/LICENSE) |
| [zenstory-ai/video-recap-skills](https://github.com/zenstory-ai/video-recap-skills) | [539168622918e058bd250c793b82f043eced31e0](https://github.com/zenstory-ai/video-recap-skills/tree/539168622918e058bd250c793b82f043eced31e0) | 2026-10-04T14:40:12+08:00 | [MIT](https://github.com/zenstory-ai/video-recap-skills/blob/539168622918e058bd250c793b82f043eced31e0/LICENSE) |
| [geekjourneyx/md2wechat-skill](https://github.com/geekjourneyx/md2wechat-skill) | [fce5fa3b4494fded0bdb942d50d17485281055d6](https://github.com/geekjourneyx/md2wechat-skill/tree/fce5fa3b4494fded0bdb942d50d17485281055d6) | 2026-09-24T08:58:03Z | [Source Available，BSL 派生](https://github.com/geekjourneyx/md2wechat-skill/blob/fce5fa3b4494fded0bdb942d50d17485281055d6/LICENSE) |
| [vangong1999/screen-creative-skills](https://github.com/vangong1999/screen-creative-skills) | [6ced54f40c864e13717707bad887c22cd732ec41](https://github.com/vangong1999/screen-creative-skills/tree/6ced54f40c864e13717707bad887c22cd732ec41) | 2026-05-26T11:03:49+08:00 | [MIT](https://github.com/vangong1999/screen-creative-skills/blob/6ced54f40c864e13717707bad887c22cd732ec41/LICENSE) |
