import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { breadcrumbList, JsonLd } from '@/components/seo/json-ld';
import { publicMetadata } from '@/lib/public-metadata';
import { absoluteUrl, siteConfig } from '@/lib/site';

const title = '自托管部署指南：用 Docker Compose 运行帧取 FrameFetch';
const description =
  '从克隆仓库到首个管理员登录：帧取 FrameFetch 的运行环境要求、Docker Compose 启动步骤、端口与健康检查、可选 AI 分析 Worker，以及公开上线前的检查清单。';
export const metadata = publicMetadata(title, description, '/self-hosting/');

const requirements = [
  'Docker Engine 与 Docker Compose。',
  '部署者已有的 PostgreSQL、RabbitMQ、Redis 与 MinIO；Compose 只管理帧取自身的业务服务并复用这些基础环境。',
  '运行统一启动器所需的 uv（Python 3.12 项目环境）。',
  '生产部署需要强随机密钥、稳定的 HTTPS 访问地址和规划好的对象存储容量。',
];

const steps = [
  {
    id: 'clone',
    title: '克隆仓库并准备环境文件',
    text: '复制示例配置后，把 .env 中的连接信息改为本机已运行的 PostgreSQL、RabbitMQ、Redis 与 MinIO。真实密钥只写入未提交的 .env 或 Secret Manager。',
    code: `git clone ${siteConfig.repositoryUrl}.git
cd video-server
test -f .env || cp .env.example .env`,
  },
  {
    id: 'schema',
    title: '为空数据库加载当前态结构',
    text: '首次使用空项目数据库时，以该库的 DDL 账号加载 schema.sql。已有数据库升级前先备份。',
    code: `psql -X -v ON_ERROR_STOP=1 -W -h 127.0.0.1 -U video -d video \\
  -f backend/sql/schema.sql`,
  },
  {
    id: 'start',
    title: '使用统一启动器启动服务',
    text: '启动器先校验 Provider 来源，再启动 Web、API、Worker、可用 Runner 与受控出口代理。生产环境使用 .env.prod 与 docker-compose-prod.yml。',
    code: `uv run --project backend python -m app.workers.runner.provider_startup start \\
  --env-file .env --compose-file docker-compose.yml`,
  },
  {
    id: 'admin',
    title: '初始化首个管理员',
    text: '全新空库在部署机终端执行一次，密码交互输入。命令只在用户表为空时创建管理员，不开放 HTTP 初始化接口。',
    code: `uv run --project backend python -m app.workers.bootstrap_admin \\
  --env-file .env --username your-admin --email you@example.com`,
  },
  {
    id: 'verify',
    title: '检查服务健康状态',
    text: '默认 Web 端口为 8101，API 端口为 8111，Swagger UI 位于 :8111/docs。健康检查只证明服务可运行，不代表每个平台都有可下载的媒体。',
    code: `curl --fail http://127.0.0.1:8111/health/live
curl --fail http://127.0.0.1:8111/health/ready
curl --fail --head http://127.0.0.1:8101/`,
  },
] as const;

const productionChecklist = [
  '替换 .env.prod 中所有占位凭据，并确认密钥来源可在换机时恢复。',
  '外部媒体访问必须经过阻断私网的出口代理；入口 URL 校验不能替代网络隔离。',
  '为 MinIO 规划容量、备份与显式清理策略；预签名链接过期不会删除最终文件。',
  '只在计划公开介绍项目的网站设置 SITE_INDEXABLE=true，并把 SITE_URL 设为稳定的 HTTPS 域名。',
  '更新代码后执行 git pull --ff-only 并重新运行统一启动命令；docker compose restart 不会应用新镜像或环境配置。',
];

export default function SelfHostingPage() {
  const structuredData = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'TechArticle',
        '@id': absoluteUrl('/self-hosting/#article'),
        headline: title,
        description,
        inLanguage: 'zh-CN',
        url: absoluteUrl('/self-hosting/'),
        about: { '@id': absoluteUrl('/#software') },
        author: {
          '@type': 'Person',
          name: siteConfig.maintainer.name,
          url: siteConfig.maintainer.url,
        },
        proficiencyLevel: 'Expert',
        dependencies: 'Docker Compose, PostgreSQL, RabbitMQ, Redis, MinIO, uv',
      },
      breadcrumbList([
        { name: siteConfig.name, path: '/' },
        { name: '自托管部署', path: '/self-hosting/' },
      ]),
    ],
  };

  return (
    <article className="inner-page">
      <JsonLd data={structuredData} />
      <PageNavigation
        fallbackHref="/"
        breadcrumbs={[{ label: '帧取', href: '/' }, { label: '自托管部署' }]}
      />
      <PageHeader title="自托管部署指南" description={description} />
      <p className="mt-6 max-w-3xl text-sm leading-7 text-muted-foreground">
        本页摘录当前部署流程。命令与配置以仓库 README 和运行手册为准；Provider
        来源登记、换机与故障恢复请阅读对应手册。
      </p>

      <section
        aria-labelledby="requirements-title"
        className="scroll-mt-24 py-12"
        data-slot="borderless-section"
        id="requirements"
      >
        <h2
          className="text-xl font-semibold tracking-tight"
          id="requirements-title"
        >
          运行帧取需要准备什么？
        </h2>
        <ul className="mt-5 grid max-w-3xl list-disc gap-3 pl-5 leading-8 text-muted-foreground">
          {requirements.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section
        aria-labelledby="steps-title"
        className="scroll-mt-24 py-12"
        data-slot="borderless-section"
        id="steps"
      >
        <h2 className="text-xl font-semibold tracking-tight" id="steps-title">
          如何用 Docker Compose 部署？
        </h2>
        <ol className="mt-5 grid max-w-3xl gap-10">
          {steps.map(({ id, title: stepTitle, text, code }, index) => (
            <li className="scroll-mt-24" id={id} key={id}>
              <h3 className="font-medium">
                {index + 1}. {stepTitle}
              </h3>
              <p className="mt-3 leading-8 text-muted-foreground">{text}</p>
              <pre className="mt-4 overflow-x-auto rounded-md bg-muted p-4 font-mono text-xs leading-6">
                <code>{code}</code>
              </pre>
            </li>
          ))}
        </ol>
      </section>

      <section
        aria-labelledby="ai-title"
        className="scroll-mt-24 py-12"
        data-slot="borderless-section"
        id="ai-analysis"
      >
        <h2 className="text-xl font-semibold tracking-tight" id="ai-title">
          AI 视频分析是否必须启用？
        </h2>
        <p className="mt-5 max-w-3xl leading-8 text-muted-foreground">
          不是。AI Worker 独立于业务 Compose 运行，可复用宿主机已登录的 Codex
          App Server，或由管理员在 Web 中配置受支持的模型
          Provider。只需要下载与剧本文档导入时，在 .env 中设置
          ANALYSIS_ENABLED=false；关闭 AI 不影响下载和文档导入。
        </p>
        <p className="mt-5 max-w-3xl leading-8 text-muted-foreground">
          使用外部模型时，分析所需内容会发送到该服务，并可能产生费用。启用前应确认素材授权和模型服务的数据处理约定。
        </p>
      </section>

      <section
        aria-labelledby="production-title"
        className="scroll-mt-24 py-12"
        data-slot="borderless-section"
        id="production"
      >
        <h2
          className="text-xl font-semibold tracking-tight"
          id="production-title"
        >
          公开上线前应检查什么？
        </h2>
        <ul className="mt-5 grid max-w-3xl list-disc gap-3 pl-5 leading-8 text-muted-foreground">
          {productionChecklist.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <nav aria-label="延伸阅读" className="flex flex-wrap gap-x-6 gap-y-3">
        <a
          className="focus-ring text-sm underline underline-offset-4"
          href={`${siteConfig.repositoryUrl}#快速开始`}
        >
          README 快速开始
        </a>
        <a
          className="focus-ring text-sm underline underline-offset-4"
          href={`${siteConfig.repositoryUrl}/blob/main/docs/design/README.md`}
        >
          运行手册
        </a>
        <a
          className="focus-ring text-sm underline underline-offset-4"
          href="/guide/"
        >
          使用指南
        </a>
      </nav>
    </article>
  );
}
