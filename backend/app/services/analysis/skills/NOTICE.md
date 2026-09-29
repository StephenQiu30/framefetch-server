# Analysis Skill third-party notices

Most built-in analysis skills are original, project-specific rewrites. The screenplay source modules listed below vendor exact upstream Markdown files and compile named sections into the selected skill snapshot. No upstream scripts, MCP definitions, plugins, network calls, file writes, or sub-agent workflows execute in the analysis worker.

## Agent Skills specification

- Source: https://github.com/agentskills/agentskills
- Reviewed commit: `69ef37e9424c0a7ea9dd2293b559e43ec8176379`
- License: repository code Apache-2.0; documentation CC-BY-4.0.
- Local use: adopted the `SKILL.md` YAML frontmatter shape and one-level reference convention. Product bindings remain namespaced and are validated by this repository.

## DirectorSKILL

- Source: https://github.com/wuwangzhang1216/DirectorSKILL
- Reviewed commit: `47db7d9b951a9f27f7b4b727a6ca0e01ab56f7c6`
- License: MIT; copyright 2026 wangzhang-wu.
- Local use: the screenplay and director-breakdown rules independently express evidence-based scene function, observable blocking, shot purpose, edit relationships, continuity anchors, and actionable production thinking. Upstream examples, exact templates, tool adapters, assets, generation workflows, risk formulas, and pipeline orchestration were excluded.

## SeaArt storyboard-prompt-assistant

- Source: https://github.com/seaartpublic/skills/tree/main/storyboard-prompt-assistant
- Reviewed commit: `a3edc17605d525b54b2a5f61a4800f2dd8dd8b30`
- License: MIT; copyright 2026 Seaart AI.
- Local use: the local storyboard, editing-rhythm and continuity references independently adopt explicit shot purpose, concrete camera language, start/end states, motivated changes and continuity checks. Product-specific prompt templates, negative prompts, generation modes, platform routing, and execution workflows were excluded.

## cutmap

- Source: https://github.com/xykong36/cutmap
- Reviewed commit: `4743a1ece5234e4bd733dd334e7fe34f04e73d3b`
- License: MIT; copyright 2026 Xiangyu Kong.
- Local use: the video skills independently account for low-contrast transitions and meaningful within-shot visual evolution rather than relying on one fixed scene threshold. No Python code, CLI behavior, algorithms, default thresholds, output pages, examples, or media assets were copied or executed.

## doocs/md

- Source: https://github.com/doocs/md
- Reviewed commit: `1c2c2f41396225892b3b3f0b5765b7d2f5d1b435`
- License: WTFPL v2; copyright 2025 Doocs.
- Local use: the article report is emitted as clean Markdown with mobile-friendly headings and a removable editor appendix so it can enter a WeChat Markdown formatting workflow. No editor code, styles, themes, assets, image-hosting logic, or deployment configuration were copied.

## wechat-article-writer

- Source: https://github.com/sammyteng/wechat-article-writer
- Reviewed commit: `ebea28e40daa8c470339d657c585e16557f91ff0`
- License: MIT; copyright 2026 sammyteng.
- Local use: the local article skill independently adopts a thesis-first outline, mobile-readable short paragraphs, editorial evidence, and a pre-publication checklist. Categorical moderation claims, hard-coded credentials and paths, browser injection, external research, account-specific style, publishing commands, and automatic calls to other skills were explicitly excluded.

## Scene Scribe (review only; no adoption)

- Source: https://github.com/seki2020/scene-scribe
- Reviewed commit: `e84d871387979918793537579412683039a1b11d`
- License: no repository license was present at the reviewed commit.
- Local use: none. The repository was reviewed only to compare storyboard deliverables; no code, text, templates, examples, or assets were copied or adapted.

## jwynia/agent-skills

- Source: https://github.com/jwynia/agent-skills
- Reviewed commit: `e02ec7e226a6e4f8419fd3b88a1d8e472d421b32`
- Reviewed skills: `story-analysis`, `scene-sequencing`, `dialogue`, and `character-arc`; each declares MIT in its frontmatter and identifies `jwynia` as author.
- Local use: the project independently implements conflict, scene function, causal progression, dialogue subtext/voice, and character choice/change as screenplay diagnostics. Deno scripts, session persistence, interactive workflows, examples, and cross-Skill orchestration were excluded.

## translate-book

- Source: https://github.com/deusyu/translate-book
- Reviewed commit: `5d07e733fa9318ff9c718085191c0c2243f51383`
- License: MIT; copyright 2025 Rainman.
- Local use: the rewrite rules independently adopt source fingerprints, glossary consistency, adjacent context, ordered chunks, coverage validation, and deterministic merge principles. Conversion tools, Calibre/Pandoc integration, scripts, arbitrary file writes, network access, and parallel sub-agents were excluded.

## watch-skill

- Source: https://github.com/oxbshw/watch-skill
- Reviewed commit: `994ee7514c64a9ec4980eeabef789b5e10ea28be`
- License: MIT; copyright 2026 oxbshw.
- Local use: the opening-hook and continuity-quality reviews independently adopt bounded observation, visible change and on-screen-text review, evidence-backed creator feedback, and an explicit distinction between observation, risk and verified outcomes. The upstream runtime, scoring formulas, CLI, MCP, REST API, capture/index stores, OCR, ASR, model integrations, scripts, examples, tests, and assets were excluded.

## drama-skills

- Source: https://github.com/zenstory-ai/drama-skills
- Reviewed commit: `3ab6b8550bbccef71001d2187e2b2ac9a74ab917`
- License: MIT; copyright 2026 drama-skills contributors.
- Local use: the opening-hook review independently separates bounded evidence, viewer or production impact, and the required revision outcome. Upstream review wording, templates, rubrics, scripts, examples, production adapters, assets, generation workflow, and cross-Skill orchestration were excluded.

## drama-skills screenplay story review (2026-09-24)

- Source: https://github.com/zenstory-ai/drama-skills/tree/b71cb3ca9343eaf6c0375725ccc9261a4e79021e/skills/short-drama-review
- Reviewed commit: `b71cb3ca9343eaf6c0375725ccc9261a4e79021e`.
- License: MIT; copyright 2026 drama-skills contributors.
- Local use: `screenplay-analysis`, `screenplay-drama-review`, `screenplay-character-review`, `screenplay-scene-review`, `screenplay-dialogue-review`, and `screenplay-continuity-review` compile named sections directly from vendored upstream `review-method.md`, `rubric-story-script.md`, and `anti-template-repair.md`. The upstream `SKILL.md` is retained for provenance. File publication, scripts, examples, other media rubrics, and agent workflow are not executed.

## screenwriting-skills screenplay story review (2026-09-24)

- Source: https://github.com/jtydhr88/screenwriting-skills/tree/357d1348ccaa1ab75f2f51ef7c90a7f00a686c76/plugins/screenwriting/skills
- Reviewed commit: `357d1348ccaa1ab75f2f51ef7c90a7f00a686c76`.
- License: MIT; copyright 2026 Terry Jia.
- Local use: `screenplay-analysis`, `screenplay-character-review`, `screenplay-scene-review`, `screenplay-dialogue-review`, and `screenplay-structure-review` compile named diagnostic sections directly from the four vendored upstream `SKILL.md` files. Their fixed page counts, required beat shapes, authoring exercises, examples, and other Skill links are reference material, not product acceptance criteria or executable workflow.

Both repositories' original MIT licenses are included beside their vendored files. `modules/manifest.json` pins each source file SHA-256 and license, and `loader.py` embeds only explicitly named sections in each task's immutable instruction snapshot. A source change requires a deliberate hash and section review; no runtime GitHub fetch occurs.

## video-shotcraft

- Source: https://github.com/Vincentwei1021/video-shotcraft
- Reviewed commit: `b0cb89173c9278042db78c3fb9c339814966f874`
- License: Apache-2.0; copyright 2026 Wei Yihao.
- Local use: the opening-hook review independently emphasizes reviewing rendered evidence before delivery, legible on-screen text, a clear initial subject, purposeful visual progression, and shot-specific handoff checks. Upstream wording, shot cards, recipes, demos, media, Remotion templates, source code, gallery, generation workflow, sound library, examples, and assets were excluded.

Updating any reviewed commit requires a fresh license and prompt-injection review, static fixtures, and real-provider E2E before release.

## marketingskills (2026-09-29)

- Source: https://github.com/coreyhaines31/marketingskills/tree/5b2c0007766c6a1cf1d53fd8fc73e979e0821022/skills/video/references/edit-anatomy.md
- Reviewed commit: `5b2c0007766c6a1cf1d53fd8fc73e979e0821022`
- License: MIT
- Imported Markdown (unmodified): `marketingskills/video-edit-anatomy.md`
- Registered modules: `marketingskills-video-edit-anatomy`
- Dropped, never vendored or executed: none
- Prompt-injection scan: no findings
- Local use: `editing-rhythm-review`: beat-by-beat visual edit analysis only; download/execution sections excluded, audio and imitation instructions do not apply.

## marketingskills (2026-09-29)

- Source: https://github.com/coreyhaines31/marketingskills/tree/5b2c0007766c6a1cf1d53fd8fc73e979e0821022/skills/social/references/short-form-video.md
- Reviewed commit: `5b2c0007766c6a1cf1d53fd8fc73e979e0821022`
- License: MIT
- Imported Markdown (unmodified): `marketingskills/social-short-form-video.md`
- Registered modules: `marketingskills-social-short-form-video`
- Dropped, never vendored or executed: none
- Prompt-injection scan: 2 findings reviewed and accepted
- Local use: `short-video-packaging`: hook types, information order and visual patterns only; examples are not facts, audio is unverified and production/publishing workflows are not executed. Scan matches were two uses of "secret" in hook examples, not access to secrets.

## marketingskills (2026-09-29)

- Source: https://github.com/coreyhaines31/marketingskills/tree/5b2c0007766c6a1cf1d53fd8fc73e979e0821022/skills/social/references/platforms.md
- Reviewed commit: `5b2c0007766c6a1cf1d53fd8fc73e979e0821022`
- License: MIT
- Imported Markdown (unmodified): `marketingskills/social-platforms.md`
- Registered modules: `marketingskills-social-platforms`
- Dropped, never vendored or executed: none
- Prompt-injection scan: 1 findings reviewed and accepted
- Local use: `short-video-packaging`: TikTok and Instagram presentation references only; demographic, reach, algorithm, posting-time and frequency claims are not verified facts or output requirements. The scan match was "Post consistently to train algorithm", not a network instruction.

## drama-skills (2026-09-29)

- Source: https://github.com/zenstory-ai/drama-skills/tree/4e48ccbf0f77da757d7cacc6937b1cc59c124845/skills/short-drama-edit/references/cut-craft.md
- Reviewed commit: `4e48ccbf0f77da757d7cacc6937b1cc59c124845`
- License: MIT
- Imported Markdown (unmodified): `drama-skills/short-drama-edit-cut-craft.md`
- Registered modules: `drama-skills-short-drama-edit-cut-craft`
- Dropped, never vendored or executed: none
- Prompt-injection scan: no findings
- Local use: `editing-rhythm-review`: entry/exit points, adjacency, cuts and duration as visual review criteria; audio-dependent judgments excluded.

## drama-skills (2026-09-29)

- Source: https://github.com/zenstory-ai/drama-skills/tree/4e48ccbf0f77da757d7cacc6937b1cc59c124845/skills/short-drama-storyboard/references/shot-craft.md
- Reviewed commit: `4e48ccbf0f77da757d7cacc6937b1cc59c124845`
- License: MIT
- Imported Markdown (unmodified): `drama-skills/short-drama-storyboard-shot-craft.md`
- Registered modules: `drama-skills-short-drama-storyboard-shot-craft`
- Dropped, never vendored or executed: none
- Prompt-injection scan: no findings
- Local use: `director-breakdown`: selected shot purpose, geography, framing, timing, continuity and review questions; no storyboard or project output.

## drama-skills (2026-09-29)

- Source: https://github.com/zenstory-ai/drama-skills/tree/4e48ccbf0f77da757d7cacc6937b1cc59c124845/skills/short-drama-storyboard/references/production-shot-grammar.md
- Reviewed commit: `4e48ccbf0f77da757d7cacc6937b1cc59c124845`
- License: MIT
- Imported Markdown (unmodified): `drama-skills/short-drama-storyboard-production-shot-grammar.md`
- Registered modules: `drama-skills-short-drama-storyboard-production-shot-grammar`
- Dropped, never vendored or executed: none
- Prompt-injection scan: no findings
- Local use: `director-breakdown`: selected narrative photography questions, scene diagnosis and anti-patterns; production fields, prompts and workflow sections excluded.

## drama-skills (2026-09-29)

- Source: https://github.com/zenstory-ai/drama-skills/tree/4e48ccbf0f77da757d7cacc6937b1cc59c124845/skills/short-drama-storyboard/references/blocking-playbooks.md
- Reviewed commit: `4e48ccbf0f77da757d7cacc6937b1cc59c124845`
- License: MIT
- Imported Markdown (unmodified): `drama-skills/short-drama-storyboard-blocking-playbooks.md`
- Registered modules: `drama-skills-short-drama-storyboard-blocking-playbooks`
- Dropped, never vendored or executed: none
- Prompt-injection scan: no findings
- Local use: `director-breakdown` and `continuity-quality-review`: axis, screen direction, visible dialogue staging, evidence reveals and observation boundaries only; no audio judgments.

## screenwriting-skills (2026-09-29)

- Source: https://github.com/jtydhr88/screenwriting-skills/tree/357d1348ccaa1ab75f2f51ef7c90a7f00a686c76/plugins/screenwriting/skills/sw-premise-theme/SKILL.md
- Reviewed commit: `357d1348ccaa1ab75f2f51ef7c90a7f00a686c76`
- License: MIT
- Imported Markdown (unmodified): `screenwriting-skills/sw-premise-theme-SKILL.md`
- Registered modules: `screenwriting-skills-sw-premise-theme-skill`
- Dropped, never vendored or executed: none
- Prompt-injection scan: no findings
- Local use: `screenplay-structure-review`: selected premise/theme diagnostic perspectives grounded in supplied scenes; no authoring workflow or mandatory formula.

## screenwriting-skills (2026-09-29)

- Source: https://github.com/jtydhr88/screenwriting-skills/tree/357d1348ccaa1ab75f2f51ef7c90a7f00a686c76/plugins/screenwriting/skills/sw-truby-anatomy/SKILL.md
- Reviewed commit: `357d1348ccaa1ab75f2f51ef7c90a7f00a686c76`
- License: MIT
- Imported Markdown (unmodified): `screenwriting-skills/sw-truby-anatomy-SKILL.md`
- Registered modules: `screenwriting-skills-sw-truby-anatomy-skill`
- Dropped, never vendored or executed: none
- Prompt-injection scan: no findings
- Local use: `screenplay-structure-review`: selected Truby structure and scene-weave diagnostics; no mandatory step counts or page quotas.
