# 影视 Skill 接入 PRD

| 项目 | 内容 |
| --- | --- |
| 产品／日期 | 帧取 Framefetch／2026-10-05 |
| 状态 | 三轮调研和选择已完成，最终 6 个 Skill（见 7.5 决策记录），待编写执行计划 |
| 取代 | [内置 Skill 能力整合](PRD-内置Skill能力整合.md)：本 PRD 的阶段 0 完成后，旧 PRD 与对应 PLAN 一并删除 |
| 核心决策 | 清掉全部自写 Skill，只接入用户选定的 6 个成熟开源 Skill，整包原样使用；所有模型调用和配图生成都走本机 Codex；能力只围绕视频 |

## 1. 概述

本文档说明如何重建帧取的 Skill 能力。我们会删除现在所有自写的 Skill 和方法片段，然后按固定版本整包接入用户选定的 6 个开源 Skill，不改其中任何文件。所有模型判断和配图生成都交给本机已登录的 Codex 完成。

素材只有两类：从平台解析下载的视频，以及用户自己上传的视频。能力围绕一条主线：

**视频解析（拉片）→ 分镜表 → 根据视频写公众号文章 → 整理和翻译 → 配图 → 公众号排版**

本期不做字幕、语音转写等声音相关功能，也不做剧本或文档研读。每份素材的每个 Skill 只保留最新一份结果。

## 2. 参与人

| 角色 | 人员 | 说明 |
| --- | --- | --- |
| 产品负责人、唯一用户 | Stephen Qiu | 确定范围和 Skill 清单，用自己的视频验收 |
| PRD 与规划 | Claude | 调研、写 PRD 和执行计划 |
| 实现 | Codex | 按执行计划实现清理与接入，提交验证证据 |
| 上游维护方 | eternityspring、affaan-m、JimLiu | 不直接参与；发现缺陷时提 Issue，不在本地私改 |

## 3. 背景

### 3.1 现在的问题

帧取是部署者一人使用的视频工作站，负责下载视频、导入剧本和文档，再用 AI 分析。现有 Skill 由项目自己编写，只从开源 Skill 中截取少量段落。这样做有四个问题：

1. **方法不完整。** 截出的段落离开原 Skill 的流程、检查表和脚本后，很难再现原作者的分析质量。
2. **维护成本高。** 上游每次升级，都要人工重新挑段落、核对哈希。
3. **拉片不可信。** 镜头时间靠模型估计，模型最不擅长报时间。
4. **报告冗余。** 同一份素材反复分析，历史报告越积越多，有用的只有最新一份。

### 3.2 为什么是现在

- **生态成熟了。** 2026 年出现了一批遵循 [Agent Skills 规范](https://agentskills.io/specification) 的高星 Skill，近一个月都有更新，可以整包运行。
- **出现了"代码量、模型判"的拉片 Skill。** reelbench 的 `video-shots` 用 ffmpeg 测切点和运动量，模型只判断景别、运镜和画面，再由 15 道脚本检查核对。它不需要 API Key，直接支持 Codex。
- **Codex 能生图了。** 本机 Codex（0.159.2）的 `image_generation` 功能已经稳定。baoyu 的配图 Skill 在 Codex 里运行时，会优先用 Codex 自带的 `imagegen` 出图，不需要其他图片 API。
- **运行环境具备了。** 宿主 AI Worker 已经通过本机 Codex 运行；本机已有 node 和 ffmpeg，还缺 bun（见 F12）。

### 3.3 调研与选型

#### 调研范围与方法

第一轮调研只是点状搜索，覆盖不够。第二、三轮（2026-10-05）按"来源 × 工作流环节"系统扫描，星数、许可和更新时间都通过 GitHub API 读取：

| 来源 | 覆盖方式 |
| --- | --- |
| [awesome-claude-video-skills](https://github.com/zhuyansen/awesome-claude-video-skills) | 读取全部 230 个仓库的结构化数据（data/skills.json，10-03 生成） |
| [skills.sh](https://skills.sh/) 注册表 | 按约 100 组中英文关键词检索：拉片、分镜、剧本、短剧、字幕、转写、ASR、说话人、OCR、翻译、公众号、小红书、影评、豆瓣、TMDB、剪辑、剪映等 |
| [everything-skills](https://github.com/findscripter/everything-skills) 索引 | 浏览媒体、音频、中文平台相关分类 |
| 官方 Skill 库 | [openai/skills](https://github.com/openai/skills)、本机 Codex 自带的 `.system` Skill、[anthropics/skills](https://github.com/anthropics/skills) |
| 候选仓库本身 | 逐个读取 SKILL.md、LICENSE 和目录结构，核实能否单独运行、有哪些依赖 |

**结论：** 230 个视频类仓库里，约九成是"做视频"（动效、宣传片、口播剪辑、AI 生成）。"分析已有素材"的成熟 Skill 很少，并且集中在三家：zenstory（drama-skills、oh-story、video-recap）、reelbench 和 baoyu。

#### 筛选门槛

1. **成熟。** 至少 500 星，或者是知名维护方的仓库，并且近 90 天有更新。
2. **许可兼容。** 许可与本项目的 MIT 许可兼容。AGPL 和"禁止商用"（NC）许可不能放进项目。
3. **能单独运行。** 不依赖上游整套项目目录和其他 Skill 的产物。
4. **模型只用本机 Codex。** 不能写死第三方云端模型 API。本机离线模型（例如语音转写）不属于 Codex，是否允许见 7.6 的 G1。

#### 按工作流环节的候选

状态说明（结论以 7.5 决策记录为准）：
- **已选**：产品负责人选定，本期接入。
- **未选（第二轮）**：第二轮新发现，产品负责人决定本期不加。
- **条件**：只有放宽某条门槛才能用。
- **排除**：已有明确的不接入理由。

**① 视频结构：拉片、分镜、拆解**

| 候选 | 星数／许可／更新 | 做什么 | 状态 |
| --- | --- | --- | --- |
| reelbench `video-shots` | 860／Apache-2.0／09-21 | 逐镜头分镜表；ffmpeg 测切点和运动量；15 道质量检查；交互报告 | 已选 |
| [lapian-notes](https://github.com/bkingfilm/lapian-notes) | 713／MIT／08-22 | 本地拉片应用：剧情泳道时间轴、结构树、情绪曲线 | 排除：是独立应用，不是 Skill；可以作为报告界面的参考 |
| [ll-video-decomposer](https://github.com/liuliu-66-create/ll-video-decomposer)、[100x-video-reverse](https://github.com/kezd088/100x-skill-tiktok)、viral-video-decomposer | 24／10／7 | 短视频五层拆解、反推、爆款拆解 | 排除：太不成熟；后两个面向复刻 |
| video-recap `video-understanding` | 549／MIT | 切场景、转写、画面理解 | 排除：写死小米 MiMo |
| [ffmpeg-analyse-video](https://github.com/fabriqaai/ffmpeg-analyse-video-skill) | 32／无许可 | 抽帧加视觉总结 | 排除：没有许可证 |

**② 声音与字幕：台词、转写、说话人**

| 候选 | 星数／许可／更新 | 做什么 | 状态 |
| --- | --- | --- | --- |
| baoyu `youtube-transcript` | 26339／MIT／09-10 | 获取 YouTube 平台字幕、章节和封面 | 第一轮选中，第二轮移除：用户不需要字幕功能 |
| [daymade `asr-transcribe-to-text`](https://github.com/daymade/claude-code-skills) | 1443／MIT／10-05 | 本机 MLX 转写（Apple Silicon 上 15–27 倍速），带说话人分离和时间码；可输出字幕 | 未选：用户不需要声音和字幕功能（备注：使用本机离线模型，说话人分离需要 HuggingFace 令牌） |
| [openclaw `openai-whisper`](https://github.com/openclaw/openclaw) | 39 万（openclaw 主仓）／MIT／10-05 | 本机 Whisper 命令行转写，不需要 API Key | 未选：用户不需要声音和字幕功能 |
| [youtube-clipper](https://github.com/op7418/youtube-clipper-skill) | 2222／MIT／01-22 | YouTube 章节分析、中英双语字幕、剪片段 | 排除：超过 90 天没更新，主要功能是剪辑 |
| openai `transcribe` | 官方 | 转写和说话人分离 | 排除：需要 OpenAI API Key，不能用 Codex 登录态 |
| [subtitle-correction](https://github.com/sugarforever/01coder-agent-skills) | 136／MIT | 校对转写字幕 | 排除：不成熟 |
| bilibili-subtitle、douyin-video-summary | 14／2 | B 站字幕、抖音总结 | 排除：太不成熟或者没有许可证 |

**③ 剧本、原著与故事**（素材只有视频，本期整组不做）

| 候选 | 星数／许可／更新 | 做什么 | 状态 |
| --- | --- | --- | --- |
| drama-skills `short-drama-novel-analyze` | 2500／MIT／10-03 | 改编视角的原著研读：索引、抽样初评、逐章、故事单元、改编价值 | 第一轮选中，第三轮移除：素材只有视频 |
| [oh-story `story-long-analyze`](https://github.com/zenstory-ai/oh-story-claudecode) | 7258／MIT／10-03 | 长篇拆文：黄金三章、逐章摘要、剧情、情绪、三维节奏、角色关系图、设定、文风；可以断点续跑；官方支持 Codex | 未选（第二轮） |
| oh-story `story-short-analyze` | 同上 | 短篇拆文：故事核、结构、情感线、反转设计、写作手法、共鸣层次 | 未选（第二轮） |
| oh-story `story-review` | 同上 | 多视角对抗式审查文本 | 未选（第二轮） |
| drama-skills `short-drama-develop` | 2500／MIT | 把小说或多集整稿发展成改编方案和分集地图 | 未选（第二轮） |
| screenwriting-skills | 1562／MIT／10-03 | 剧作方法：结构、冲突、场景、对白 | 第一轮未选 |
| [screen-creative-skills](https://github.com/vangong1999/screen-creative-skills)（宫凡） | 437／MIT／05-26 | 剧本评估、IP 评估、人物小传、人物关系、情节点、故事五元素、剧集拉片、思维导图 | 未选（第二轮；星数不足，并且超过 90 天没更新） |
| drama-skills `short-drama-storyboard` | 2500／MIT | 剧本生成分镜表 | 第一轮决定先不接 |
| oh-story `story-long-scan`、`story-short-scan` | 同上 | 抓网文平台排行榜 | 排除：要爬取平台数据，偏选题 |

**④ 文章整理、翻译、配图与排版**（作用于根据视频写成的文章）

| 候选 | 星数／许可／更新 | 做什么 | 状态 |
| --- | --- | --- | --- |
| baoyu `format-markdown`、`markdown-to-html`、`translate`、`article-illustrator` | 26339／MIT | 整理、公众号排版、翻译（只翻译文章）、Codex 配图 | 已选 |
| [humanizer-zh](https://github.com/op7418/humanizer-zh) | 18924／MIT／09-23 | 删掉中文稿里的空话、重复和模板化表达，保留事实、语气确定程度和作者的声音 | 未选（第二轮） |
| oh-story `story-deslop` | 7258／MIT | 网文去 AI 味 | 未选（第二轮） |
| [dbskill](https://github.com/dontbesilent2025/dbskill) | 10418／**CC BY-NC 4.0**／09-28 | 短视频逐字稿流失点检查、发布风险和敏感词检查、小红书标题公式、公众号 HTML | 未选（第二轮；禁止商用许可，与本项目的 MIT 许可冲突） |
| [md2wechat](https://github.com/geekjourneyx/md2wechat-skill) | 3687／无明确许可 | 公众号 HTML、配图、草稿 | 排除：许可不明；与已选重复 |
| [wechat-article-extractor](https://github.com/freestylefly/wechat-article-extractor-skill) | 136／无许可 | 从公众号链接抓取文章 | 排除：没有许可证 |
| [xiaohongshu-note-analyzer](https://github.com/softbread/xiaohongshu-doctor) | 3／无许可 | 小红书笔记诊断 | 排除：没有许可证，也不成熟 |
| [pdf-converter-mineru](https://github.com/tanis90/pdf-converter-mineru) | 54／无许可 | 扫描版 PDF 识别 | 排除：没有许可证；扫描版导入的需求见 G6 |

**⑤ 根据视频写公众号文章**（第三轮补充调研）

| 候选 | 星数／许可／更新 | 做什么 | 状态 |
| --- | --- | --- | --- |
| [ecc `article-writing`](https://github.com/affaan-m/ecc) | 273054（主仓）／MIT／10-02 | 长文写作：先写具体的例子再解释，用证据代替形容词，**不编造事实**；可以按范文定文风；纯 SKILL.md，没有脚本和外部依赖；英文编写 | 已选 |
| [xstongxue `wechat-article-writer`](https://github.com/xstongxue/best-skills) | 2938／Apache-2.0／09-13 | 公众号全流程：写作、封面、插图、提取和克隆文风；含调用公众号 API 自动发布的步骤 | 未选 |
| [`khazix-writer`](https://github.com/kkkkhazix/khazix-skills) | 21163／MIT／10-01 | 公众号长文写作，质量高 | 未选：以真实博主"数字生命卡兹克"的身份和口吻写作，不适合用户自己的公众号 |
| [aiworkskills `aws-wechat-article-writing`](https://github.com/aiworkskills/wechat-article-skills) | 656／Apache-2.0／09-23 | 公众号写稿套件，可以调 DeepSeek／GPT，也可以由 Agent 代写 | 未选 |
| [huashu `huashu-wechat-image`](https://github.com/alchaincyf/huashu-skills) | 1647／MIT／09-22 | 公众号封面和插图 | 排除：AI 生图路线写死 Gemini API |
| [clueso `video-to-article`](https://github.com/clueso-ai/skills) | 27／Apache-2.0 | 视频直接转文章 | 排除：依赖 Clueso 平台 |

**⑥ 影视资料与口碑（片名、演职员、评分、影评）**

| 候选 | 状态 |
| --- | --- |
| TMDB 相关（caffeinelabs `connector-tmdb` 等） | 排除：绑定特定平台，或者星数极低 |
| 豆瓣影评（agentbay `douban-movie-review`） | 排除：依赖阿里云无影 AgentBay 云服务 |
| B 站弹幕、评论分析 | 排除：没有成熟 Skill |

这一环节**没有可用的成熟 Skill**；用户确认本期不需要（G7）。

**⑦ 剪辑与工程交接（剪映草稿、EDL、Premiere）**

| 候选 | 状态 |
| --- | --- |
| jianying-editor（2002 安装）、chengfeng-videocut（3030 星）、FireRed-OpenStoryline、Premiere MCP 等 | 排除：都是剪辑和生成，超出"只分析"的产品边界 |

### 3.4 drama-skills 逐项检查

检查对象：[zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills) v0.8.1（commit `c2426e0`，2026-10-03），MIT 许可，2500 星。方法是克隆整个仓库，逐个阅读 11 个 Skill 的 SKILL.md、references 和 scripts。

**总体结论：** 它是一条完整的 AI 短剧**创作生产线**：原著 → 开发 → 剧本 → 视觉设定 → 图片提示词 → 分镜 → 视频提示词 → 生产 → 剪辑 → 审查。每个 Skill 的输入都是它自己的项目文件（`剧本.md`、`视觉设定.md`、`分镜.md` 等），**没有一个 Skill 以外部成片视频为输入**。在全仓库搜索"拉片""参考视频""已有视频"等关键词，只找到视频生成模型的参考视频参数。

按我们"只有视频、只做解析和写文章"的范围逐项判断：

| Skill | 做什么 | 输入 | 能否用于我们的视频 | 结论 |
| --- | --- | --- | --- | --- |
| `short-drama` | 项目初始化、路由、本地 Dashboard、Look Development | 项目目录 | 不能：管理创作项目 | 不接 |
| `short-drama-novel-analyze` | 原著研读、改编价值 | 小说文本 | 不能：只吃文本 | 不接（第三轮已移除） |
| `short-drama-develop` | 改编方案、故事引擎、分集地图；含"对标作品机制摘取" | 小说、梗概、剧本、对标材料 | 部分：对标摘取能把拉片结果当"对标作品"，提炼"它靠什么机制抓人"，但整个 Skill 的目标是开发新剧，会顺带建立开发文件 | 不接（属于创作；可以作为将来"对标拆解"的候选） |
| `short-drama-write` | 写或改单集剧本 | 大纲、剧本 | 不能 | 不接 |
| `short-drama-assets` | 拆人物、场景、道具，写视觉设定 | 剧本 | 不能 | 不接 |
| `short-drama-image-prompts` | 参考图提示词 | 视觉设定 | 不能：属于生成 | 不接 |
| `short-drama-storyboard` | 剧本 → 分镜表和冻结关键帧提示词 | `剧本.md` 和 `视觉设定.md`（都必需） | 不能：方向相反，它是从剧本做分镜，我们是从视频拉出分镜 | 不接（分镜表由 `video-shots` 产出） |
| `short-drama-video-prompts` | 分镜 → 视频生成提示词 | 分镜 | 不能：属于生成 | 不接 |
| `short-drama-produce` | 调用生图、视频、配音、音乐的供应商 | 已确认的提示词 | 不能：属于生成，要付费调用 API | 不接 |
| `short-drama-edit` | 把生成的镜头剪成成片，写剪辑单 | 项目内已生成的素材，以及剧本、分镜 | 不能：属于剪辑，需要它的剧本和分镜做依据 | 不接 |
| `short-drama-review` | 审查剧本、提示词、分镜和"已有媒体" | 项目文件；"已有媒体"指项目内生成的素材 | 不能：要拿成片和它自己的剧本、分镜对照，没有这些就只能给"暂时无法判断"的结论 | 不接 |

**结论：** drama-skills **本期没有可以直接接入的能力**。它的方法知识写得很好，例如 storyboard 的调度和轴线、edit 的入出点和镜序、review 的视觉运动审查表。但这些都绑定在它的创作流程里，单独截取就回到了"切片段"的老路，这正是本次要清理的做法。如果将来做"对标拆解"（从别人的片子里学机制），`short-drama-develop` 的对标摘取是首选候选，需要另做验证。

### 3.5 已选 Skill 的深度核查

逐个克隆上游仓库，阅读全部脚本，并在本机实测（2026-10-05）：

| Skill | 固定版本 | 脚本与依赖 | 联网 | 会不会向用户提问 | 偏好配置 | 实测结果 |
| --- | --- | --- | --- | --- | --- | --- |
| `video-shots` | reelbench `1b51af8`（09-21），Apache-2.0 | 1 个 node 脚本，只用标准库，零 npm 依赖；调用本机 ffmpeg 和 ffprobe | 无 | Step 0 会问"拉全片还是一段、拉来干什么"，问不到就按默认值 | 无 | 自测 449 项断言全部通过。合成的 12 秒测试片上，3 个切点准确落在第 3、6、9 秒；动态画面实测运动量约 4.6，静止画面为 0；关键帧和联系表正常生成。景别等字段没填时，有 4 道检查按设计报错 |
| `article-writing` | ecc `ef648e0`（10-01），MIT | 只有 SKILL.md，没有脚本 | 无 | 没有范文时用默认文风；要定文风时建议先跑同仓库的 `brand-voice` | 无 | 规则包含"不编造事实，事实必须来自提供的材料"，和"只根据拉片结果写"一致 |
| `baoyu-format-markdown` | baoyu `1567581`（09-10），MIT | bun 脚本；依赖 remark、unified、yaml 等 8 个 npm 包，有 bun.lock | 无 | 默认不需要初次设置 | `.baoyu-skills/baoyu-format-markdown/EXTEND.md`（项目、XDG、用户目录三级） | 待阶段 0 实测 |
| `baoyu-markdown-to-html` | 同上 | bun 脚本；依赖 `baoyu-md`、`baoyu-chrome-cdp`；文中有 Mermaid 图时用无头 Chrome 渲染，没有 Chrome 就退回代码块 | 无（Chrome 只在本机渲染） | 会问主题等偏好 | 同上，`baoyu-markdown-to-html/EXTEND.md` | 待阶段 0 实测 |
| `baoyu-translate` | 同上 | bun 脚本，依赖 `markdown-it`；精译模式会启动子代理 | 无 | 初次使用会问偏好，可以由 EXTEND.md 预设 | 同上，`baoyu-translate/EXTEND.md` | 待阶段 0 实测 |
| `baoyu-article-illustrator` | 同上 | 没有自己的脚本；在 Codex 里运行时直接调用 Codex 自带的 `imagegen`（本机 `~/.codex/skills/.system/imagegen` 已存在） | 只有 Codex 生图 | 会问配图类型、密度、风格和配色 | 同上，固定 `preferred_image_backend: codex-imagegen` | 待阶段 0 实测 |

**核查中发现的注意点：**

- **只装需要的 Skill。** **不要**安装 `baoyu-image-gen`。它内置了即梦、Seedream、Z.AI、Agnes 等十几家第三方图片 API 的调用代码。`article-illustrator` 在 Codex 里不需要它。
- **npm 依赖要预先锁定。** baoyu 的 3 个脚本 Skill 依赖 npm 包，必须在部署时按上游的 bun.lock 预装，运行时禁止联网安装（F12）。
- **EXTEND.md 放在独立配置目录。** 它是上游支持的偏好文件，放在项目自己的配置目录里，不放进 Skill 目录，因此不违反"不改上游文件"。
- **ecc 只取需要的目录。** ecc 仓库很大，只取 `skills/article-writing`（以及选用时的 `skills/brand-voice`）和仓库 LICENSE。

**同仓库的两个补充候选**（与已选能力直接配套，待产品负责人选择）：

| 候选 | 版本／许可 | 做什么 | 依赖 |
| --- | --- | --- | --- |
| reelbench `video-sync` | 同 `video-shots` | 把拉片结果和原片合成一条视频：一边播放画面，一边是滚动高亮的分镜表；横版上下排，竖版左右排 | node、ffmpeg、无头 Chrome（只用来渲染面板），零 npm 依赖 |
| ecc `brand-voice` | 同 `article-writing` | 从用户自己的旧文章里提炼"文风档案"，`article-writing` 写作时复用，避免每次重新分析 | 只有 SKILL.md 和一份档案格式说明 |


## 4. 目标

### 4.1 目标

让用户把自己下载或上传的视频，变成两类可以直接使用的成果：
- **专业、可核对的拉片报告和分镜表；**
- **一篇有配图、排好版的公众号文章。**

方法完全来自成熟的上游 Skill，项目只负责"接入、串联、运行、展示"。

- **对用户：** 拉片有真实的镜头时间；文章里的每个事实都能对回某个镜头；成品能直接粘进公众号编辑器。
- **对项目：** 删除自写方法；升级只要换版本号再跑回归；不增加 Codex 以外的模型供应商。
- **对战略：** 符合"单人自用、减少日常维护"的产品定位（见[设计 01](../design/01-产品定位与边界.md)）。

### 4.2 关键结果

暂时没有质量基线。下面的数字是首轮目标，第一次测量后再校准。

| 编号 | 关键结果 | 时间 |
| --- | --- | --- |
| KR1 | 项目里自写的 Skill 文件数为 0；6 个 Skill 全部记录来源、固定版本、内容哈希和许可；运行时只有本机 Codex 一个模型出口 | 阶段 0 结束时 |
| KR2 | 拉片：至少 5 条真实视频（包含下载的短剧、电影片段、短视频，以及自己上传的视频）通过全部 15 道质量检查，无人工干预的完成率至少 90% | 阶段 1 结束时 |
| KR3 | 视频转文章：用 5 条视频各生成 1 篇公众号文章；抽查文章里的事实，100% 能对回拉片结果中的镜头（不编造）；用户判断"改一改就能发"的文章至少 3 篇 | 阶段 1.1 结束时 |
| KR4 | 整理、翻译和排版不改动事实、引文和链接；配图被用户采纳的比例要实测记录 | 阶段 1.1 结束时 |
| KR5 | 每份素材的每个 Skill 只保留 1 份结果；旧报告清理后，存储量下降的比例要实测记录 | 阶段 0 结束时 |
| KR6 | 任一上游 Skill 升级到新版本，从改版本号到完成样本回归不超过 1 个工作日 | 阶段 2 起每次升级 |

## 5. 用户与场景

只有一个用户：部署者本人。素材是解析下载的视频和自己上传的视频。

| 任务 | 优先级 | 现在的痛点 | 约束 |
| --- | --- | --- | --- |
| 视频解析／拉片：把视频拆成逐镜头分镜表，看懂剪辑节奏和镜头语言 | 最高 | 镜头时间靠估计；运镜描述常是幻觉 | 长片按段拉；没有声音信息，台词只读画面上的字幕 |
| 根据视频写公众号文章 | 高 | 从看片到成文全靠手工 | 事实只能来自拉片结果，不编造；可以提供自己的范文来定文风 |
| 整理、翻译、配图、排版文章 | 中 | 排版和配图靠手工 | 不改事实；配图只用 Codex 生成；不自动发布 |

## 6. 价值主张

| 维度 | 现在 | 接入后 |
| --- | --- | --- |
| 拉片可信度 | 模型估计时间 | ffmpeg 测切点和运动量，15 道检查拦下运镜幻觉 |
| 从视频到文章 | 手工看片、手工写 | 拉片结果直接作为写作素材，文章事实可以对回镜头 |
| 成品可用性 | 只有分析建议 | 分镜表、文章、译文、配图、公众号 HTML，拿来就能用 |
| 模型 | 多个 Provider | 只用本机 Codex（文字和图片都是） |
| 报告 | 历史堆积 | 每份素材的每个 Skill 只保留最新一份 |
| 维护 | 每次人工挑段落 | 换版本号，跑回归，完成 |

**价值曲线：** 拉片可信度、从视频到成文的效率和维护成本明显超过现状。为此放弃自定义方法、多模型选择、历史版本对比、剧本研读、声音和字幕，这几项降为 0。

## 7. 方案

### 7.1 使用流程

**流程 A：视频解析／拉片／分镜表**（`video-shots`）

```text
视频详情（下载的或上传的）→ 选「拉片」→ 选全片或时间段，选用途（仿写参考／剪辑节奏／素材盘点）
 → 进度：测切点 → 抽关键帧和联系表 → Codex 逐批填写景别／类别／运镜／画面／节奏
   → 补刀并刀 → 15 道质量检查（不通过就修，直到通过）
 → 报告页：交互拉片报告（播放器同步高亮、节奏带、可筛选镜头表、首尾关键帧、景别和运镜分布）
 → 导出：分镜表（Markdown）、shots.json、交互报告（HTML）
```

**流程 B：根据视频写公众号文章**（串联：`article-writing` → `baoyu-format-markdown` → `baoyu-article-illustrator` → `baoyu-markdown-to-html`）

```text
已完成拉片的视频 → 选「写成公众号文章」→ 填写读者和目的；可选上传 1–3 篇自己的范文定文风
 → 写作：article-writing 只以拉片结果（分镜表、画面描述、节奏、统计）为事实来源写初稿
 → 整理：format-markdown 调整标题层级、列表和强调，不改内容
 → 【暂停】展示初稿，用户可以直接修改，或者「继续」
 → 配图：article-illustrator 给出配图位置和风格方案 →【暂停】确认后由 Codex 出图
 → 排版：markdown-to-html 选公众号主题 → 预览 → 复制进公众号编辑器
```

还没拉片的视频，选「写成公众号文章」时，会先自动跑一遍流程 A。

**流程 C：翻译文章**（`baoyu-translate`）

```text
文章结果页 → 「翻译」→ 选目标语言和快译／常规／精译 → 译文 → 可以继续配图和排版
```

**所有流程通用：** 同一份素材用同一个 Skill 再次运行成功后，新结果替换旧结果。失败或取消时保留旧结果。

### 7.2 关键功能

| 编号 | 功能 | 说明 | 验收 |
| --- | --- | --- | --- |
| F1 | 全量清理 | 删除所有自写 Skill、共享写作规范、片段模块清单、相关提示词、文档研读入口，以及 Codex 以外的模型调用路径 | 代码中没有自写 SKILL.md 或方法片段 |
| F2 | 结果精简 | 每份素材的每个 Skill 只保留最新一份成功结果。一次性清理存量时，先列出要删除的数量和占用空间，用户确认后才删除 | 每份素材的每个 Skill 最多 1 份结果；清理前有确认，有清理记录 |
| F3 | 上游 Skill 原样接入 | 按固定 commit 整包放入项目（ecc 只取 `skills/article-writing` 目录和仓库 LICENSE），保留 LICENSE 和 NOTICE，记录来源、版本和整包哈希；Skill 目录内的文件一律不改。偏好只写进上游支持的配置文件（例如 baoyu 的 EXTEND.md） | 包哈希和上游 commit 一致；改动会被检查拦下 |
| F4 | 适配层与串联 | 项目代码只负责：放好素材、传入读者／目的／语言／范文、调起 Codex、把上一步的产出文件交给下一步、转交 Skill 的提问、收集产出、映射进度。适配写在 Skill 目录之外，不写"怎么分析、怎么写" | 适配层没有分析或写作方法类内容 |
| F5 | 只用本机 Codex | 文字判断由宿主 AI Worker 中已登录的 Codex 完成；配图后端固定为 Codex `imagegen`（`preferred_image_backend: codex-imagegen`） | 运行时没有其他模型或图片 API 请求 |
| F6 | Skill 目录页 | 显示上游名称、中文说明、版本、来源链接和许可；不允许上传自定义 Skill | Web 和 App 都可见、可选 |
| F7 | 视频解析／拉片 | 见流程 A；支持下载和上传的视频，全片或时间段；台词只来自画面上烧录的字幕，读不到就留空并说明 | 15 道检查全部通过，或者明确列出跳过原因；报告离线可打开，可以跳转播放 |
| F8 | 视频写文章 | 见流程 B；事实来源只有拉片结果；范文可选，没有范文时用上游默认文风；输出语言默认中文 | 文章中每个事实都能对回镜头；没有编造的数据、引语或经历 |
| F9 | 人工确认点 | 初稿和配图方案等需要确认的地方，任务进入"等待确认"，期间不消耗模型调用；初稿可以在线修改后继续 | 可以确认、修改后继续、终止，或者超时后自动终止 |
| F10 | 整理、翻译、排版 | 见流程 B 和 C；正文的事实、引文和链接保持不变；不发布 | 抽查前后文本，事实零改动 |
| F11 | 配图 | 先存提示词文件，再由 Codex 出图；配图插入建议的位置，可以单张替换或删除 | 每张图有对应的提示词文件；只经由 Codex 生成 |
| F12 | 运行环境与安全 | 宿主预装固定版本的 bun、node 和 ffmpeg，禁止运行时用 `npx -y bun` 临时下载；上游脚本只在沙箱中运行，只能访问输入和输出目录；网络只开放 Codex；取消时结束整个进程组 | 越权读写和越权联网被拒绝，并记录日志 |
| F13 | 升级流程 | 改固定版本 → 查看上游差异 → 重跑样本 → 用户确认后切换 | 满足 KR6；结果标注生成时的 Skill 版本 |

### 7.3 技术要点

- **运行方式：** 宿主 AI Worker 让 Codex 原生加载 Skill，不在服务端重新实现 Skill 解析器。各 Skill 需要的 bun、node 和 ffmpeg 放在哪里，在设计文档中确定。
- **可靠性：** 编排、取消、未知回执保护等约束沿用现有工作流设计；串联的每一步和每次生图都受这些约束保护。具体技术方案写入新的设计文档，本 PRD 不规定实现细节。
- **结果：** 原样保存并展示上游产出（JSON、Markdown、HTML、图片），不转换成项目自定义的结构；交互报告用沙箱方式展示。

### 7.4 假设（需验证）

| 编号 | 假设 | 验证方式 | 不成立时 |
| --- | --- | --- | --- |
| A1 | Codex 能看懂 `video-shots` 的联系表和关键帧，填出可用的景别和运镜 | 阶段 0 用 3 条真实视频跑完，人工抽查 20 个镜头 | 调整 Codex 的模型设置；仍不行就推迟 |
| A2 | 只靠拉片结果（没有声音），`article-writing` 也能写出有内容的中文公众号文章，并且不编造事实；这个 Skill 是英文写的，输出语言由适配层指定 | 阶段 0 用 3 条视频各写 1 篇，逐条核对事实 | 限定文章类型为"拉片解读／视听分析"；如果仍然空洞，重新选写作 Skill |
| A3 | `baoyu-article-illustrator` 在宿主 Worker 的 Codex 中能识别 `imagegen`，并按固定后端出图 | 阶段 0 用 1 篇文章出 3 张图 | 改走上游支持的 `codex-cli` 路径；仍不行就推迟配图 |
| A4 | baoyu 系列在 Skill 里提问时，适配层能把问题转给用户或按默认值回答，流程不会卡住 | 阶段 0 逐个 Skill 跑一次 | 在 EXTEND.md 中预设默认值 |
| A5 | 只保留最新一份结果不会丢失用户需要的信息 | 阶段 1 使用观察 | 增加"固定保留"标记 |
| A6 | 长片按段拉片、配图批量出图的 Codex 用量可以接受 | 阶段 0 记录一部 90 分钟影片和一篇长文的用量和耗时 | 默认只拉选定段落；配图默认数量调低 |

### 7.5 决策记录（2026-10-05 产品负责人确认）

| 问题 | 决定 |
| --- | --- |
| 模型 | 只用本机 Codex，文字和配图都是；不接写死第三方 API 的 Skill |
| 素材范围 | 只有解析下载的视频和自己上传的视频 |
| 接入的 Skill（共 6 个） | `video-shots`、`article-writing`（ecc）、`baoyu-format-markdown`、`baoyu-markdown-to-html`、`baoyu-translate`、`baoyu-article-illustrator` |
| 视频解析 | 拉片报告就是解析结果，不另做整体解读 |
| 写公众号文章 | 用 ecc `article-writing`；不用 `khazix-writer`（它以真实博主的身份和口吻写作） |
| 配图来源 | 只用 Codex 生成，不用拉片的关键帧 |
| 剧本／原著研读 | 移除（第一轮选中的 `short-drama-novel-analyze`）；第二轮的剧本类新候选也不加 |
| 文章翻译 | 保留 |
| 剧本生成分镜表、小红书图卡 | 不做 |
| 声音、字幕、转写 | 不做（移除第一轮选中的 `baoyu-youtube-transcript`） |
| 影视资料与口碑 | 不做 |
| 历史报告 | 每份素材的每个 Skill 只保留最新一份；存量清理前需要用户确认 |
| 产品边界变化 | 新增"根据自己的视频写公众号文章"和"Codex 配图"；不再提供剧本和文档的 AI 研读。[设计 01](../design/01-产品定位与边界.md)中的"不做内容写作"等条目在阶段 0 同步修改 |

### 7.6 之前没有考虑周全的问题

| 编号 | 问题 | 影响 | 建议 |
| --- | --- | --- | --- |
| G1 | **Codex 听不到声音。** 拉片只能读画面上烧录的字幕；没有剧本的视频无法做故事和对白分析 | 影视分析缺少"台词"这一层 | **已决定：** 本期不做声音和字幕功能；拉片只读画面上的字幕，报告里写明这个限制 |
| G2 | **已经下载的平台字幕没有利用。** 下载引擎（yt-dlp）本来就能拿到 YouTube、B 站等平台的字幕 | 重复转写，浪费时间 | **已决定：** 本期不使用平台字幕 |
| G3 | **Skill 之间要串联。** 流程 B 是"拉片 → 写作 → 整理 → 配图 → 排版"五步串联 | 单个 Skill 产出零散；一步失败会影响后面 | 适配层只按固定顺序传递文件，不加方法；每一步的结果单独保存，失败时可以从这一步重跑（F4） |
| G4 | **Skill 会向用户提问，或者要求先部署。** baoyu 系列运行中会向用户提问；`article-writing` 想定文风时会建议先运行同仓库的 `brand-voice`（未接入） | 无人值守的 Worker 会卡住，或者改动工作目录 | 每个任务在独立工作区运行；提问转成"等待确认"（F9），或者在上游支持的配置里预设默认值；`article-writing` 只用用户上传的范文或上游默认文风 |
| G5 | **第三方 Skill 的安全。** SKILL.md 本身就是给模型的指令，可能夹带提示注入；脚本可能临时下载依赖（`npx -y`、`uv run`、`pip`），有的还会联网或读浏览器 Cookie | 供应链风险和越权风险 | 接入和升级前人工审查 SKILL.md 和脚本的差异；依赖预装并固定版本；运行时网络默认关闭，按 Skill 单独放行（F12） |
| G6 | **没有声音时文章会不会空洞。** 拉片只有画面信息，写不出人物说了什么 | 文章可能只剩画面描述 | 定位为"拉片解读／视听分析"类文章；A2 在阶段 0 验证 |
| G7 | **影视资料与口碑。** 片名、演职员、评分、影评、弹幕，是拉片和研读的重要背景 | 报告缺少外部背景 | **已决定：** 本期不需要 |
| G8 | **用量与时长。** 一部 90 分钟的电影需要几十张联系表；一篇文章从写作到配图要多次调用；配图每张都要调用一次 Codex | 单人的 Codex 订阅可能触发限额，任务也会很久 | 记录每个任务的 Codex 调用次数和耗时；默认按段或按章节范围运行；同一时间只跑一个重任务 |
| G9 | **结果会随 Codex 变化。** 同一个 Skill 用不同版本的 Codex 或模型，结果会不同 | 回归对比不可靠 | 每份报告记录 Skill 版本、Codex 版本和模型名称 |
| G10 | **评测样本。** KR 需要固定的样本集，否则无法比较升级前后的结果 | 质量无法量化 | 阶段 0 建立个人样本集：下载的短剧、电影片段、短视频，以及自己上传的视频各若干条，并记录用户评分 |
| G11 | **三端展示。** 交互 HTML 报告和关键帧图片要在 Web 和 Flutter App 中显示；DOCX 导出不适合 JSON 和 HTML 产出 | 在 App 上可能看不了 | 设计文档中规定各类产出在每一端怎么展示、能导出什么格式 |
| G12 | **存储。** 关键帧、联系表和配图体积大 | 磁盘增长 | 只保留最新一份（F2），中间文件任务结束后清理，只留报告需要的部分 |
| G13 | **许可的细节。** Apache-2.0 要求保留 NOTICE；CC BY 要求署名；NC 和 AGPL 不能进仓库 | 合规风险 | 每个 Skill 保留 LICENSE 和 NOTICE；在 Skill 目录页展示许可；NC 和 AGPL 只允许在宿主机单独安装 |
| G14 | **素材版权与发布。** 拉片报告包含关键帧；根据下载的他人视频写的文章发到公众号，涉及原作版权 | 发布有风险 | 拉片报告仅供本人使用；文章导出时提示"基于他人作品的解读，发布前请确认引用范围"；产品不自动发布 |

## 8. 发布计划

| 阶段 | 预计时长 | 内容 | 退出条件 |
| --- | --- | --- | --- |
| 阶段 0：清理与验证 | 约 1 周 | F1、F2 清理；F3、F5、F12 的最小可用版本；验证 A1–A4、A6；建立视频样本集（G10）；删除旧 PRD 和旧 PLAN，更新设计 01、10、11 | 满足 KR1、KR5；A1、A2 成立 |
| 阶段 1：拉片 | 约 2 周 | 视频解析／拉片／分镜表（F7）、目录页（F6）、报告与导出 | 满足 KR2 |
| 阶段 1.1：视频写文章 | 约 2 周 | 流程 B 串联（F4、F8、F9）、整理与排版（F10）、配图（F11）、翻译（流程 C） | 满足 KR3、KR4 |
| 阶段 2 | 持续 | 升级流程（F13）；每季度复查 3.3 节中未选的候选 | 满足 KR6；用户重新选定后才进入新版本 |

**不在本次范围内：** 剧本和文档研读、写剧本、剧作诊断、根据剧本生成分镜、字幕获取、语音转写、影视资料与口碑、生成视频、配音、剪辑、自动发布、小红书图卡、用户自定义 Skill、修改上游 Skill 内容，以及接入本机 Codex 以外的模型。

## 参考来源

- [eternityspring/reelbench-skills](https://github.com/eternityspring/reelbench-skills)（[video-shots](https://github.com/eternityspring/reelbench-skills/tree/main/skills/video-shots)）
- [affaan-m/ecc](https://github.com/affaan-m/ecc)（[article-writing](https://github.com/affaan-m/ecc/blob/main/skills/article-writing/SKILL.md)）、[kkkkhazix/khazix-skills](https://github.com/kkkkhazix/khazix-skills)、[xstongxue/best-skills](https://github.com/xstongxue/best-skills)、[aiworkskills/wechat-article-skills](https://github.com/aiworkskills/wechat-article-skills)、[alchaincyf/huashu-skills](https://github.com/alchaincyf/huashu-skills)
- [zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills)（[short-drama-novel-analyze](https://github.com/zenstory-ai/drama-skills/blob/main/skills/short-drama-novel-analyze/SKILL.md)、[short-drama-storyboard](https://github.com/zenstory-ai/drama-skills/blob/main/skills/short-drama-storyboard/SKILL.md)）
- [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills)
- [zenstory-ai/video-recap-skills](https://github.com/zenstory-ai/video-recap-skills)、[jtydhr88/screenwriting-skills](https://github.com/jtydhr88/screenwriting-skills)、[op7418/guizang-social-card-skill](https://github.com/op7418/guizang-social-card-skill)
- [zhuyansen/awesome-claude-video-skills](https://github.com/zhuyansen/awesome-claude-video-skills)、[skills.sh](https://skills.sh/)、[everything-skills](https://github.com/findscripter/everything-skills)、[openai/skills](https://github.com/openai/skills)、[anthropics/skills](https://github.com/anthropics/skills)
- [zenstory-ai/oh-story-claudecode](https://github.com/zenstory-ai/oh-story-claudecode)、[daymade/claude-code-skills](https://github.com/daymade/claude-code-skills)、[openclaw/openclaw](https://github.com/openclaw/openclaw)、[op7418/humanizer-zh](https://github.com/op7418/humanizer-zh)、[dontbesilent2025/dbskill](https://github.com/dontbesilent2025/dbskill)、[vangong1999/screen-creative-skills](https://github.com/vangong1999/screen-creative-skills)、[bkingfilm/lapian-notes](https://github.com/bkingfilm/lapian-notes)
- [Agent Skills 规范](https://agentskills.io/specification)
