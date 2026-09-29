# Direct upstream screenplay modules

This directory contains unmodified Markdown files from two MIT-licensed repositories. The copies are pinned to the commits below and include each repository's original `LICENSE` file.

| Repository | Commit | Imported files |
| --- | --- | --- |
| [zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills) | `b71cb3ca9343eaf6c0375725ccc9261a4e79021e` | `short-drama-review/SKILL.md`, `references/review-method.md`, `references/rubric-story-script.md`, `references/anti-template-repair.md` |
| [jtydhr88/screenwriting-skills](https://github.com/jtydhr88/screenwriting-skills) | `357d1348ccaa1ab75f2f51ef7c90a7f00a686c76` | `sw-scene-craft/SKILL.md`, `sw-character-conflict/SKILL.md`, `sw-dialogue/SKILL.md`, `sw-story-structure/SKILL.md` |

The files retain their upstream text and frontmatter. `manifest.json` pins each file's SHA-256, license and selected sections; `app.services.analysis.skills.modules` validates it at load time. A skill opts into modules with `video-server-modules`; the loader places the selected original text into the immutable task instruction snapshot. The project-specific skill body and output contract constrain how the source material is applied. Only Markdown text is compiled; no upstream scripts or tools run, and the worker does not fetch content from GitHub.

Import new sources with `uv run python -m app.workers.skill_import --repository <url> --commit <sha> --path <skill dir> --source <name>` from `backend/`. It fetches exactly that commit, requires an allowlisted license (MIT, Apache-2.0, BSD, CC-BY-4.0), keeps only Markdown, drops scripts and manifests without executing them, blocks on prompt-injection findings until reviewed, writes the files unmodified, registers every `##` section in `manifest.json` and appends a `NOTICE.md` entry. Narrow `sections` in the manifest to what a product Skill needs. To upgrade a source, delete the old files deliberately and import the new commit; do not edit vendored files in place.
