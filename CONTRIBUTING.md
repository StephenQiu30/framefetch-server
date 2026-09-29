# Contributing

感谢你愿意改进 `server`。

## 模块边界

- `backend/`：FastAPI、领域服务、Worker、当前态 SQL 与 Python 测试。
- `frontend/`：Next.js App Router 页面、Radix UI/shadcn 组件、Tailwind CSS 主题、已提交的 OpenAPI 客户端与前端测试。
- `docs/`：当前产品和架构事实。
- 根 `Dockerfile`、`docker-compose-env.yml`、`docker-compose.yml` 与 `docker-compose-prod.yml`：维护业务运行与 CI 验证，不建立独立部署目录。业务与生产 Compose 只启动应用容器；环境 Compose 仅供 GitHub CI 使用。

功能交付先更新 `docs/design/README.md`，并保持测试、契约、文档和实际运行方式一致。具体目录、依赖、安全、配置和测试规则以 `AGENTS.md` 为准。提交前分别运行后端与前端质量门禁；涉及运行时变更时还需验证环境 Compose、业务 Compose、生产 Compose 和统一镜像构建。

## Docker 使用规范

- 本机直接复用已有基础服务和环境配置；`docker-compose-env.yml` 仅用于 GitHub CI，`docker-compose.yml` 只启动业务服务；`docker-compose-prod.yml` 只启动生产业务服务。
- 业务服务通过 `.env` 的 `POSTGRES_HOST/PORT`、`RABBITMQ_HOST/PORT`、`REDIS_HOST/PORT`、`MINIO_HOST/PORT` 连接基础服务。填写宿主机可达地址和实际端口，容器默认使用 `host.docker.internal`。
- 不得覆盖已有 `.env`，也不为本机验证启动基础服务。MinIO 只使用一组共享的 `MINIO_ACCESS_KEY` 与 `MINIO_SECRET_KEY`。
- GitHub CI 使用隔离夹具；本地验证复用正在运行的基础服务，不创建新的环境或启动脚本。详细启动、停止和故障恢复规则见 [根目录 Compose 运行手册](docs/design/README.md)。

安全边界和漏洞报告方式见 `SECURITY.md`；任何下载能力变更都必须保留公开、授权、非 DRM 的产品边界。

前端路由只放在 `frontend/src/app/`，组件优先复用 `src/components/ui/` 中的 Radix/shadcn 源码并通过 Tailwind 语义 token 统一主题。`frontend/src/services/video/` 使用仓库内已提交的 OpenAPI 客户端，接口变化时必须同步审查契约和客户端差异；生成请求统一进入 `src/lib/request.ts`，页面通过 `src/services/` 的稳定入口调用。客户端鉴权只使用同源 HttpOnly Cookie，请求层最多刷新并重试一次，浏览器不得持久化 JWT。

前端提交前执行 `npm run lint`、`npm test` 和 `npm run build`。生产构建使用 Next.js standalone，前端与 FastAPI 独立运行；UI 变更同时验证键盘操作、可见焦点、错误状态以及 390px 窄屏无页面级横向溢出。

## 提交规范

每个可独立验证、可安全回滚的小任务对应一个提交。提交信息遵循 Conventional Commits，类型和作用域使用小写英文，冒号后的描述必须使用中文：

```text
<type>(<scope>): <中文描述>
```

作用域可省略；省略时使用 `<type>: <中文描述>`，不要保留空括号。提交说明建议使用明确的中文动作短语。推荐类型如下：

| 类型 | 用途 |
| --- | --- |
| `feat` | 新增用户可见能力 |
| `fix` | 修复缺陷 |
| `refactor` | 不改变外部行为的代码重构 |
| `docs` | 仅修改文档 |
| `test` | 新增或调整测试 |
| `perf` | 性能优化 |
| `build` | 构建系统或依赖变更 |
| `ci` | 持续集成配置变更 |
| `chore` | 其他维护工作 |
| `style` | 不影响逻辑的格式调整 |
| `revert` | 回退已有提交 |

作用域使用稳定、非空的小写英文模块名，如 `api`、`frontend`、`backend`、`runner`、`worker`、`docs`、`deps`。无法准确归属时省略作用域，不要临时发明含糊缩写：

```text
feat(api): 增加下载任务取消接口
fix(frontend): 修复任务状态轮询泄漏
refactor(worker): 拆分分析任务持久化逻辑
docs: 补充本地开发说明
```

`feat(): 增加功能` 不是合法格式：使用作用域时必须填写括号内容，不需要作用域时应写成 `feat: 增加功能`。

破坏性变更使用 `!` 标记，并在提交正文中提供 `BREAKING CHANGE:` 说明：

```text
feat(api)!: 移除旧下载接口

BREAKING CHANGE: 客户端需要迁移到新版下载接口
```

正文用于解释修改动机、实现方式和影响，与标题之间保留一个空行；关联任务可在页脚写 `Refs: #123`。不要在标题中堆叠实现细节。

提交前运行完整代码级门禁：

```bash
cd backend && uv sync --frozen --dev && uv run --frozen ruff check app tests && uv run --frozen ruff format --check app tests && uv run --frozen mypy app && uv run --frozen pytest -q
cd ../frontend && npm ci && npm run format:check && npm run lint && npm test && npm run build
```

Pull Request 和提交说明的格式约定只用于协作可读性，不作为 CI 阻断项。GitHub Actions 的 `Backend tests` 和 `Frontend tests` 是每次修改的必跑系统测试边界；任意一项失败即为 CI 失败。

提交前只暂存当前任务文件并完成相关业务验证；提交后运行 `git status --short`，确保没有本任务遗留的未提交文件。只有在明确要求时才推送远端或创建 PR。包括合并和回退在内的提交说明建议遵循上述中文约定，但不设置额外的格式阻断门禁。
