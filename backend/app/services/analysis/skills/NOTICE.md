# Analysis Skill third-party notices

Most built-in analysis skills are original, project-specific rewrites. The source modules listed under “Vendored source modules” are exact upstream Markdown files; only the sections named in `modules/manifest.json` are compiled into a skill snapshot. No upstream scripts, MCP definitions, plugins, network calls, file writes, or sub-agent workflows execute in the analysis worker.

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

## video-shotcraft

- Source: https://github.com/Vincentwei1021/video-shotcraft
- Reviewed commit: `b0cb89173c9278042db78c3fb9c339814966f874`
- License: Apache-2.0; copyright 2026 Wei Yihao.
- Local use: the opening-hook review independently emphasizes reviewing rendered evidence before delivery, legible on-screen text, a clear initial subject, purposeful visual progression, and shot-specific handoff checks. Upstream wording, shot cards, recipes, demos, media, Remotion templates, source code, gallery, generation workflow, sound library, examples, and assets were excluded.

## Vendored source modules

Each repository's original license is kept beside its files. `modules/manifest.json` pins every file's SHA-256, license and selected `##` sections, and the loader compiles only those sections. Sections outside the selection (workflows, templates, tool instructions, platform statistics, audio timing, links) never reach the model. Updating a source requires re-importing a pinned commit with `app.workers.skill_import`, a fresh license and prompt-injection review, and a new section selection.

### drama-skills

- Source: https://github.com/zenstory-ai/drama-skills (MIT; copyright 2026 drama-skills contributors)
- Commit `b71cb3ca9343eaf6c0375725ccc9261a4e79021e`:
  - `drama-story-script` ← `skills/short-drama-review/references/rubric-story-script.md`: story promise, entry and character memory, scene test, dialogue. Used by `screenplay-analysis`, `screenplay-drama-review`, `screenplay-character-review`, `screenplay-scene-review`, `screenplay-dialogue-review`, `screenplay-continuity-review`.
  - `drama-anti-template` ← `skills/short-drama-review/references/anti-template-repair.md`: four diagnostic layers and false-positive counterexamples. Used by `screenplay-analysis`, `screenplay-drama-review`.
- Commit `4e48ccbf0f77da757d7cacc6937b1cc59c124845`:
  - `drama-edit-cut-craft` ← `skills/short-drama-edit/references/cut-craft.md`: shot order and adjacency only. Used by `editing-rhythm-review`.
  - `drama-shot-craft` ← `skills/short-drama-storyboard/references/shot-craft.md`: shot purpose, blocking and geography, connected boundaries, common problems, review questions. Used by `director-breakdown`.
  - `drama-shot-grammar` ← `skills/short-drama-storyboard/references/production-shot-grammar.md`: narrative photography questions and scene-type diagnosis. Used by `director-breakdown`.
  - `drama-blocking-playbooks` ← `skills/short-drama-storyboard/references/blocking-playbooks.md`: axis and screen direction, single-room dialogue, evidence reveals, observation boundaries. Used by `director-breakdown`, `continuity-quality-review`.

### screenwriting-skills

- Source: https://github.com/jtydhr88/screenwriting-skills (MIT; copyright 2026 Terry Jia), commit `357d1348ccaa1ab75f2f51ef7c90a7f00a686c76`, files under `plugins/screenwriting/skills/`.
  - `sw-story-structure`: structure levels, Chinese short-play devices, inciting incident and progressive complications, crisis/climax/resolution, non-linear and ensemble forms. The minute-based nine-beat template is not compiled.
  - `sw-character-conflict`, `sw-scene-craft`, `sw-dialogue`: diagnostic sections; the authoring workflows and exercises are not compiled.
  - `sw-premise-theme`: controlling idea, desire vs. false belief, premise questions, dramatic core, conflict and plot.
  - `sw-truby-anatomy`: seven key steps, the five middle components and the ten-question diagnosis. Scene weave and anti-patterns are not compiled.
- Used by the screenplay review Skills as diagnostic perspectives. Page counts, minute marks and step counts inside the selected text are reference points, not acceptance criteria.

### Humanizer-zh

- Source: https://github.com/op7418/Humanizer-zh (MIT), commit `f4518a8eab97b8bfebc66a89d34320a89bef6930`, file `SKILL.md`.
- `humanizer-zh`: editing constraints, register, pattern usage, patterns A–F and the pre-delivery check. The file workflow, file protection, full example and source links are not compiled. Import scan findings (the `allowed-tools` frontmatter and source links) lie outside the selection.
- Used by every analysis Skill except `screenplay-rewrite`, through `shared/report-writing.md`, as a self-review checklist for the Skill's own report prose. It is never used to judge the analysed screenplay or on-screen text and never licenses adding facts.

### chinese-copywriting-guidelines

- Source: https://github.com/sparanoid/chinese-copywriting-guidelines (MIT), commit `9a5fbeb842f39644352fd79b5d8c6764718105cc`, file `README.zh-Hans.md`.
- `zh-copywriting-guidelines`: spacing, punctuation, full-width and half-width characters, proper nouns. The disputed rules, tool list, adopters and references are not compiled; import scan findings are links in those excluded sections.
- Used by every analysis Skill for report prose; `screenplay-rewrite` applies it to narration and stage directions and keeps characters' intentional speech as written.

Updating any reviewed commit requires a fresh license and prompt-injection review, static fixtures, and real-provider E2E before release.
