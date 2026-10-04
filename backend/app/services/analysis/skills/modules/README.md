# Vendored upstream modules

This directory holds unmodified Markdown files from MIT-licensed repositories, each pinned to a reviewed commit and kept beside its original `LICENSE`:

| Directory | Repository | Modules |
| --- | --- | --- |
| `drama-skills/` | [zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills) | `drama-story-script`, `drama-anti-template`, `drama-edit-cut-craft`, `drama-shot-craft`, `drama-shot-grammar`, `drama-blocking-playbooks` |
| `screenwriting-skills/` | [jtydhr88/screenwriting-skills](https://github.com/jtydhr88/screenwriting-skills) | `sw-story-structure`, `sw-character-conflict`, `sw-scene-craft`, `sw-dialogue`, `sw-premise-theme`, `sw-truby-anatomy` |
| `humanizer-zh/` | [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh) | `humanizer-zh` |
| `chinese-copywriting-guidelines/` | [sparanoid/chinese-copywriting-guidelines](https://github.com/sparanoid/chinese-copywriting-guidelines) | `zh-copywriting-guidelines` |
| `baoyu-skills/` | [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills) | `baoyu-article-title`（只选直述标题方法，供 `video-to-article` 使用） |

`manifest.json` pins each file's SHA-256, license, source URL and the `##` sections a product Skill may compile. Select only sections that serve the product task: a section that would have to be followed by "ignore this" in the Skill body does not belong in the selection. The per-module rationale is in `../NOTICE.md`.

A Skill opts into modules with `video-server-modules`; the loader places the selected text into the immutable task instruction snapshot, ahead of the Skill body. Only Markdown is compiled; no upstream scripts or tools run, and the worker never fetches from GitHub.

Import a source with `uv run python -m app.workers.skill_import --repository <url> --commit <sha> --path <skill dir or file> --source <name>` from `backend/`. The command requires an allowlisted license (MIT, Apache-2.0, BSD, CC-BY-4.0), keeps only Markdown, blocks on prompt-injection findings until reviewed, writes files unmodified, registers every `##` section and appends a `NOTICE.md` entry. Afterwards give the module a short id, narrow its sections and rewrite the NOTICE entry to describe the actual use. To upgrade a source, delete the old files and import the new commit; do not edit vendored files in place. Delete files that no Skill uses.
