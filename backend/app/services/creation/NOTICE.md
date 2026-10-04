# Content analysis method sources

The method text and deterministic chapter indexing in this directory were written
for FrameFetch. No upstream scripts, prompts or runtime code were copied.

Drama analysis was informed by the public `zenstory-ai/drama-skills` analysis and
review workflows at revision `c2426e03c0e7722bebcc6a488b6658dc38c65ac3`:

- <https://github.com/zenstory-ai/drama-skills/tree/c2426e03c0e7722bebcc6a488b6658dc38c65ac3/skills/short-drama-novel-analyze>
- <https://github.com/zenstory-ai/drama-skills/tree/c2426e03c0e7722bebcc6a488b6658dc38c65ac3/skills/short-drama-review>

Upstream declares the MIT license, Copyright (c) 2026 drama-skills contributors.
The verified LICENSE SHA-256 is
`840bdb5ba503ca4397f5a6049e6e8da182330f83bb70006d5656d7dd00674e9b`.
The project adapts the analysis task boundaries rather than installing a remote
agent, executing upstream commands or enabling media production.

Container card rendering uses Debian's `fonts-noto-cjk` package. Its package
copyright and font license are retained in the container under
`/usr/share/doc/fonts-noto-cjk/copyright`. Host fonts and model weights are never
bundled by copying a user's local files.
