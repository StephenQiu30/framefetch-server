# Frontend

帧取 Web 前端，属于 video-server。使用 Next.js App Router、React、TypeScript strict、Tailwind CSS、shadcn/ui、Radix 与 Phosphor。工程遵循 create-next-app 的 src 目录与 @/* 别名；唯一视觉设计标准是根 [design.md](../design.md)。

## 开发与验证

Node.js 24，pnpm 版本以 package.json 的 packageManager 为准。只维护 pnpm-lock.yaml。

```bash
pnpm install --frozen-lockfile
pnpm dev
pnpm format:check
pnpm lint
pnpm test
pnpm build
```

生产输出为 Next.js standalone。前端监听 8101，FastAPI 监听 8111；src/proxy.ts 按运行时 BACKEND_ORIGIN 将 /api/*、/health/* 转发到后端，上传使用流式代理。生产入口须将 /api/ws/tasks 的 WebSocket Upgrade 转发到 FastAPI。基础设施复用当前宿主机服务，部署命令见根 README。

## 目录

```text
src/
├── app/          路由、布局、元数据与全局主题
├── api/          Umi OpenAPI 生成的请求函数与 API 类型
├── components/   按业务组织组件、专用 Hooks 与展示逻辑；ui/ 为官方组件
├── hooks/        跨业务共享的 React Hooks
└── lib/          request.ts、错误处理、浏览器能力与共享函数；upload/ 为上传编排
```

完整放置规则见根 [PROJECT.md](../PROJECT.md)。不建立 services、utils、types 聚合目录；接口类型直接引用生成的 API.*。

## 自动生成接口

后端 FastAPI 从路由装饰器、类型注解、Pydantic 请求/响应模型自动产生 /openapi.json，/docs 展示 Swagger UI。接口定义只在后端代码维护，不手写 Swagger 文件。

```bash
pnpm openapi
```

@umijs/openapi 读取 openapi2ts.config.ts，默认从 http://127.0.0.1:8111/openapi.json 生成 src/api/。也可设置 OPENAPI_SCHEMA_URL 指向其他后端或从后端自动导出的临时 schema；不提交临时文档或本地地址。运行的是官方 CLI 的 Node 入口，避免已发布 bin 的 CRLF shebang 在 Unix 下执行失败，不增加包装脚本。

- 所有 REST 请求函数与接口类型都由生成器维护，禁止手写或修改 src/api 文件。
- 页面、Hooks 与业务编排直接导入生成函数。
- 所有生成函数调用 src/lib/request.ts 中的 Axios request，统一处理超时、Cookie、认证恢复和 RFC Problem Details。
- 路径参数按生成签名传入对象；幂等键、取消信号、上传回调和二进制 responseType 通过 RequestOptions 传递。
- 后端二进制响应必须声明 string/binary，生成器通过官方 customType hook 映射为 Blob；不手工补类型。
- Web 使用 PostgreSQL 持久化的不透明 HttpOnly Cookie，不刷新 JWT、不自动重放业务请求。登录／注册／退出通过同源 Web Locks 串行写入，要求 HTTPS（开发可用 localhost／回环地址）和支持 Web Locks 的现代浏览器；临时故障保留已确认身份，只有明确的本站会话失效才重新登录。
- 首屏在请求范围内调用生成的用户接口，2 秒内确认身份并将用户投影交给 AuthProvider，Cookie 不传入客户端属性。已有身份在后台复核时不闪回等待页；不可用保持 unknown，不显示匿名登录入口。服务端请求和私有 HTML 均 no-store；BACKEND_ORIGIN 仅来自部署配置。
- 根布局的 TanStack Query 缓存按身份代际隔离。下载历史、剧本文档、平台列表、分析 Skill 和管理统计直接调用生成 API 并传递 AbortSignal；切页保留已加载数据，换账号取消旧请求并清空旧缓存。写操作成功后定向失效相关列表；业务查询不自动重试写操作或把临时故障转成登录跳转。公开链接通过持久 intent 接单、观察和取消，sessionStorage 只保存 owner 与随机恢复键；原文仅在内存，刷新后查询原任务。恢复语义见[解析中心](../workspace/content/design/06-解析意图.md)。
- 接口变化时先更新后端注解并重启后端，再执行生成、类型检查和相关测试，提交生成差异。

## 官方组件

```bash
pnpm dlx shadcn@latest info --json
pnpm dlx shadcn@latest docs input select
pnpm dlx shadcn@latest add input --dry-run
pnpm dlx shadcn@latest add input --diff input.tsx
```

保留组件 API、焦点、错误与浮层行为；页面和基础控件的视觉样式以根 [design.md](../design.md) 为准，不通过全局 CSS 使组件变形。`components.json` 的配置仅说明当前实现，不是另一份设计标准。cn 使用官方组件依赖的 cn 包。Progress 向 Radix 传递 value，确保辅助技术可读进度；该修正由测试保护。

管理列表和下载记录使用 `components/layout/data-table.tsx`，按 [shadcn Data Table](https://ui.shadcn.com/docs/components/radix/data-table) 组合官方 Table、Checkbox、DropdownMenu 与 TanStack Table v9。列定义统一表头/单元格对齐，支持列显隐与本页行选择；现有页面继续管理服务端筛选、排序和分页，不对单页数据另做客户端排序。批量删除复用原有权限、确认和部分失败处理，当前账户及受保护 AI 线路不可选择。

Biome 对官方 ui 源码中有明确用途的角色、事件、数组 key 与图表 CSS 注入使用目录级规则豁免；业务代码继续执行完整规则。pnpm-workspace.yaml 明确拒绝不需要的 es5-ext 安装脚本。

## 通用正文组件

正文统一从 `@/components/editor` 引用 `Editor` 和 `Viewer`，两者共用官方 [Editor.js](https://github.com/codex-team/editor.js) 与官方块工具。`Viewer` 使用 `readOnly: true`，不维护另一套 React 块阅读器。组件接收 Editor.js `OutputData`，不会隐式转换 Markdown。

```tsx
import { Editor, Viewer, type EditorDocument } from '@/components/editor';

const [document, setDocument] = useState<EditorDocument>({ blocks: [] });
<Editor value={document} onChange={setDocument} />;
<Viewer value={document} />;
```

`Editor` 仅在浏览器动态加载，等待 `isReady` 后使用 API；普通受控回传不重新渲染，外部替换正文、保存与只读切换依序执行。只读切换调用官方 `readOnly.toggle()`，保留当前编辑内容。`ref.save()` 仅用于可编辑状态，只读时明确拒绝。卸载销毁实例，加载失败可重试；`placeholder` 和 `autofocus` 是初始化选项。未知工具由官方 Stub 占位展示并保留数据。

报告与剧本的 Markdown API 和 MD／DOCX 导出仍是当前业务契约，调用方通过 `markdownToEditorDocument()` 显式导入后交给 `Viewer`。该函数只支持已接入的正文、标题、列表／任务列表、引用、代码、表格和分隔线，不是无损 Markdown 往返转换：混合嵌套列表样式、表格列对齐和代码语言标记不属于当前块格式。前端导入不修改后端保存的原始报告，也没有新增正文保存接口。

块内富文本在交给官方工具前清除活动 HTML、远端图片和非 HTTP(S) 链接；剧本导入使用函数第二个参数 `'text'` 显示原始 HTML 标签，阅读时禁用链接。`headingOffset` 与 `headingIds` 保留页面标题层级与目录锚点。主题映射限定在共享组件内，沿用官方块 DOM、工具栏与只读行为。

## 内置 Skill

保留原视频／剧本详情、导航、分析配置器与报告布局：Skill、中文／英文、可编辑默认提示词、恢复默认与原执行提示均保持。调用和类型由后端原正式分析契约生成，具体方法及报告内容可优化，不新增Skill工作台、双源表单或文本处理弹窗。

方法必须使用完整实际来源，报告有实质分析／整理、准确依据和限制。MD／DOCX沿原操作读取保存结果；原reader的代码、表格、换行与长SHA显示缺陷只作最小修复。页面恢复、质量和真实验收见[执行计划](../workspace/content/plan/PLAN-内置Skill能力整合.md)。

## 验证边界

Vitest 覆盖认证恢复、生成请求、上传、下载、分析和页面交互。浏览器额外检查桌面/390px、明暗主题、导航、焦点和溢出。生成成功、单元测试或构建成功均不等于 YouTube、抖音等平台的真实解析/下载验收。

容器由本目录 Dockerfile 独立构建，构建上下文为 frontend；运行镜像只包含 Node.js 与 Next.js standalone。根 Compose 分别构建前后端镜像。

## 公开页面与 SEO

匿名首页与 `/guide/` 在服务端输出可阅读正文；存在会话 Cookie 的首页继续恢复工作区并禁止索引。`SITE_INDEXABLE` 默认 false，正式公开网站需明确设置 true，并使构建/运行时 `SITE_URL` 一致。调整后重建前端镜像。公开页面使用统一 canonical、OpenGraph 与 robots，sitemap 不包含私有路由。部署检查和 GEO 内容规则见 [Web 体验与 SEO](../workspace/content/design/11-Web体验.md)。

## 系统操作日志

管理员日志入口、记录范围、故障语义和部署验证见[解析与处理记录](../workspace/content/design/06-解析意图.md)。

## 使用统计

管理员在 `/admin/analytics` 切换下载与 AI 分析统计，共用 7、30、90 天周期。AI 数据通过生成的 `getAnalysisAnalytics` 请求读取，按 UTC 创建日统计数据库保留的分析执行记录，包含所属任务已软删除的执行；手动重试与重新执行分别计数。完成耗时只纳入有完整且有效起止时间的终态记录，无样本时显示空值。图表后的每日明细及分布数据可核对精确数值；这些执行记录不等同于供应商的模型请求次数、Token 或费用。

### 全站快捷操作

快捷操作位于全站页脚，不占用顶部导航。所有共享布局页面（包含登录、注册、使用指南和管理员页面）都可点击入口或按 `⌘K` / `Ctrl+K` 打开；按 Escape 或关闭按钮退出并恢复原焦点。输入页面名称可筛选并跳转公开页面或当前账户可访问的工作区页面，管理员额外可跳转管理页面。登录后仍支持链接解析、本地视频和剧本文档上传；匿名访问时提供登录、注册和公开页面入口，不自动发起业务请求。

个人资料页支持上传和移除头像；上传成功后账户页、桌面账户菜单和移动导航会显示更新后的头像。图片格式、大小限制与服务端校验保持一致，登录用户的头像通过同源鉴权地址读取。
