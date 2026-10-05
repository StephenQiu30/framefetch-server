# frontend 协作规范

本目录是 `video-server` 的 Web 前端，遵循根 [AGENTS.md](../AGENTS.md)。目录与接口规则见 [PROJECT.md 第 6 节](../PROJECT.md#6-前端)，视觉标准只有根 [design.md](../design.md)。

## 工作方式

- 使用 pnpm 与唯一 `pnpm-lock.yaml`，不引入 npm/yarn 锁文件或额外生成包装脚本。
- 后端接口变化后执行 `pnpm openapi` 并提交生成结果；`OPENAPI_SCHEMA_URL` 可指向运行中的后端或临时导出的 schema，临时 schema 不入库。
- 修改基础组件前先查 shadcn 官方 CLI 与文档并预览差异；可访问性修复需附回归测试。
- 页面状态组件按 [PROJECT.md 第 6.1 节](../PROJECT.md#61-页面状态)选用，不在业务页面复制 `Empty` 结构。
- 品牌图标复用 `public/logo.svg`，业务图标使用 Phosphor。
- Next.js standalone 监听 8101，FastAPI 监听 8111；前端只保留运行时代理与上传流式代理，业务规则由后端负责。

## 验证

```bash
pnpm install --frozen-lockfile
pnpm openapi:check
pnpm format:check
pnpm lint
pnpm test
pnpm build
```

界面改动在真实浏览器检查桌面与 390px、明暗主题、可访问名称、焦点恢复、溢出与错误恢复。
