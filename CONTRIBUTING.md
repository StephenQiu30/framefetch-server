# 贡献指南

感谢你改进帧取服务端。开始前请阅读 [AGENTS.md](AGENTS.md) 与 [PROJECT.md](PROJECT.md)；运行方式见 [README.md](README.md)，安全问题按 [SECURITY.md](SECURITY.md) 私下报告。

## 模块

| 目录 | 内容 |
| --- | --- |
| `backend/` | FastAPI、Worker、Runner、当前态 SQL 与 Python 测试 |
| `frontend/` | Next.js Web 与生成的 OpenAPI 客户端 |
| `extension/` | Chrome 身份扩展 |
| `docs/` | Obsidian 文档库：产品需求、系统设计与执行计划 |

## 本地检查

后端，从 `backend/` 执行：

```bash
uv sync --frozen --dev
uv run --frozen ruff check app tests
uv run --frozen ruff format --check app tests
uv run --frozen mypy app
uv run --frozen pytest -q
```

前端，从 `frontend/` 执行：

```bash
pnpm install --frozen-lockfile
pnpm openapi:check
pnpm format:check
pnpm lint
pnpm test
pnpm build
```

身份扩展测试，从仓库根目录执行：

```bash
node --test extension/*.test.cjs
```

文档，从仓库根目录执行：

```bash
node backend/scripts/check_docs.mjs
```

本机检查复用已运行的基础服务，不为验证另起数据库或覆盖 `.env`。涉及运行时、依赖或容器时，额外验证 `docker compose config` 与 `docker compose -f docker-compose-prod.yml config` 可解析，并按需构建镜像。

## CI

文档编写与沉淀遵循 [docs/AGENTS.md](docs/AGENTS.md)。

GitHub Actions 的 `Backend tests`、`Frontend tests` 与 `Docs` 是每次推送和 PR 的必跑检查，任一失败即 CI 失败。前端 Job 从后端源码导出 OpenAPI 并检查生成差异；`Docs` Job 运行身份扩展测试、文档链接与锚点检查。完整 Compose 启停、真实平台下载与发布演练按变更范围在本地验收，不在 CI 执行。

## 提交规范

每个可独立说明、验证和回滚的小任务对应一个提交。提交信息使用 Conventional Commits，类型与作用域为小写英文，描述为中文：

```text
<type>(<scope>): <中文描述>
```

| 类型 | 用途 |
| --- | --- |
| `feat` | 新增用户可见能力 |
| `fix` | 修复缺陷 |
| `refactor` | 不改变外部行为的重构 |
| `docs` | 仅修改文档 |
| `test` | 新增或调整测试 |
| `perf` | 性能优化 |
| `build` | 构建系统或依赖 |
| `ci` | 持续集成配置 |
| `chore` | 其他维护 |
| `style` | 不影响逻辑的格式调整 |
| `revert` | 回退已有提交 |

- 作用域使用稳定的模块名，如 `api`、`backend`、`frontend`、`worker`、`runner`、`identity`、`extension`、`docs`、`deps`；无法准确归属时省略，写作 `<type>: <中文描述>`，不留空括号。
- 描述是简洁的中文动作短语，不加句号，不堆叠实现细节。
- 破坏性变更在类型或作用域后加 `!`，并在正文写 `BREAKING CHANGE: <中文说明>`。
- 正文与标题空一行，说明动机、实现与影响；关联任务写在页脚，如 `Refs: #123`。

```text
feat(api): 增加下载任务取消接口
fix(frontend): 修复任务状态轮询泄漏
refactor(worker): 拆分分析任务持久化逻辑
docs: 补充本地开发说明
```

提交格式服务于协作可读性，不作为 CI 阻断条件。
