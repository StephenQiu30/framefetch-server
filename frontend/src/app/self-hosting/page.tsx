import Link from 'next/link';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { SplitLayout } from '@/components/layout/split-layout';
import { breadcrumbList, JsonLd } from '@/components/seo/json-ld';
import { Field, FieldLabel } from '@/components/ui/field';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from '@/components/ui/item';
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from '@/components/ui/navigation-menu';
import { Textarea } from '@/components/ui/textarea';
import { publicMetadata } from '@/lib/public-metadata';
import { absoluteUrl, siteConfig } from '@/lib/site';

const title = '自托管部署指南：用 Docker Compose 运行帧取 Framefetch';
const description =
  '从克隆仓库到首个管理员登录：帧取 Framefetch 的运行环境要求、Docker Compose 启动步骤、端口与健康检查、可选 AI 分析 Worker，以及公开上线前的检查清单。';
export const metadata = publicMetadata(title, description, '/self-hosting/');

const requirements = [
  'Docker Engine 与 Docker Compose。',
  '部署者已有的 PostgreSQL、RabbitMQ、Redis 与 MinIO；Compose 只管理帧取自身的业务服务并复用这些基础环境。',
  'macOS 平台会话来源需要 uv（Python 3.12）、日常 Chrome 与帧取扩展。',
  '生产部署需要强随机密钥、稳定的 HTTPS 访问地址和规划好的对象存储容量。',
];

const steps = [
  {
    id: 'clone',
    title: '克隆仓库并准备环境文件',
    text: '复制示例配置后，把 .env 中的连接信息改为本机已运行的 PostgreSQL、RabbitMQ、Redis 与 MinIO。真实密钥只写入未提交的 .env 或 Secret Manager。',
    code: `git clone ${siteConfig.repositoryUrl}.git
cd framefetch-server
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
    title: '安装登录来源并启动业务服务',
    text: 'macOS 上安装 Chrome 会话来源，并在 chrome://extensions 加载命令输出目录中的扩展。复用日常 Chrome 已有平台登录；Compose 启动 Web、API、Worker、Runner 与出口代理。公开链接优先匿名解析。生产配置见 README。',
    code: `uv run --project backend python -m app.workers.session.source_cli install --env-file .env
docker compose up -d --build --wait --remove-orphans`,
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
  '更新代码后执行 git pull --ff-only 并按 README 重新安装来源并执行 Compose 构建启动；docker compose restart 不会应用新镜像或环境配置。',
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
    <article className="inner-page flex flex-col gap-8">
      <div>
        <JsonLd data={structuredData} />
        <PageNavigation fallbackHref="/" />
        <PageHeader title="自托管部署指南" description={description} />
      </div>
      <Item variant="muted">
        <ItemContent>
          <ItemDescription className="line-clamp-none">
            本页摘录当前部署流程。命令与配置以仓库 README
            为准；平台登录、换机与故障恢复请阅读对应设计文档。
          </ItemDescription>
        </ItemContent>
      </Item>
      <SplitLayout columns="primary">
        <section
          id="steps"
          aria-labelledby="steps-title"
          className="flex flex-col gap-4"
        >
          <ItemTitle>
            <h2 id="steps-title">如何用 Docker Compose 部署？</h2>
          </ItemTitle>
          <ol className="flex min-w-0 flex-col gap-4">
            {steps.map(({ id, title: stepTitle, text, code }, index) => (
              <Item asChild key={id} variant="muted">
                <li id={id} className="scroll-mt-24">
                  <ItemContent className="min-w-0 gap-4">
                    <ItemTitle className="line-clamp-none">
                      <h3>
                        {index + 1}. {stepTitle}
                      </h3>
                    </ItemTitle>
                    <ItemDescription className="line-clamp-none">
                      {text}
                    </ItemDescription>
                    <Field>
                      <FieldLabel htmlFor={`${id}-command`}>
                        {stepTitle}命令
                      </FieldLabel>
                      <Textarea
                        id={`${id}-command`}
                        readOnly
                        rows={code.split('\n').length + 1}
                        value={code}
                        wrap="off"
                      />
                    </Field>
                  </ItemContent>
                </li>
              </Item>
            ))}
          </ol>
        </section>
        <ItemGroup className="gap-6 self-start" role="presentation">
          <Item asChild variant="muted">
            <section id="requirements" aria-labelledby="requirements-title">
              <ItemContent className="gap-4">
                <ItemTitle className="line-clamp-none">
                  <h2 id="requirements-title">运行帧取需要准备什么？</h2>
                </ItemTitle>
                {requirements.map((item) => (
                  <ItemDescription className="line-clamp-none" key={item}>
                    {item}
                  </ItemDescription>
                ))}
              </ItemContent>
            </section>
          </Item>
          <Item asChild variant="muted">
            <section id="ai-analysis" aria-labelledby="ai-title">
              <ItemContent className="gap-4">
                <ItemTitle className="line-clamp-none">
                  <h2 id="ai-title">AI 视频分析是否必须启用？</h2>
                </ItemTitle>
                <ItemDescription className="line-clamp-none">
                  不是。AI Worker 独立于业务 Compose 运行，可复用宿主机已登录的
                  Codex App Server，或由管理员在 Web 中配置受支持的模型
                  Provider。只需要下载与剧本文档导入时，在 .env 中设置
                  ANALYSIS_ENABLED=false；关闭 AI 不影响下载和文档导入。
                </ItemDescription>
                <ItemDescription className="line-clamp-none">
                  使用外部模型时，分析所需内容会发送到该服务，并可能产生费用。启用前应确认素材授权和模型服务的数据处理约定。
                </ItemDescription>
              </ItemContent>
            </section>
          </Item>
          <Item asChild variant="muted">
            <section id="production" aria-labelledby="production-title">
              <ItemContent className="gap-4">
                <ItemTitle>
                  <h2 id="production-title">公开上线前应检查什么？</h2>
                </ItemTitle>
                {productionChecklist.map((item) => (
                  <ItemDescription className="line-clamp-none" key={item}>
                    {item}
                  </ItemDescription>
                ))}
              </ItemContent>
            </section>
          </Item>
        </ItemGroup>
      </SplitLayout>
      <NavigationMenu
        aria-label="延伸阅读"
        className="max-w-none justify-start"
        viewport={false}
      >
        <NavigationMenuList className="flex-wrap justify-start gap-3">
          <NavigationMenuItem>
            <NavigationMenuLink asChild>
              <Link href={`${siteConfig.repositoryUrl}#快速开始`}>
                README 快速开始
              </Link>
            </NavigationMenuLink>
          </NavigationMenuItem>
          <NavigationMenuItem>
            <NavigationMenuLink asChild>
              <Link
                href={`${siteConfig.repositoryUrl}/blob/main/docs/design/README.md`}
              >
                系统设计
              </Link>
            </NavigationMenuLink>
          </NavigationMenuItem>
          <NavigationMenuItem>
            <NavigationMenuLink asChild>
              <Link href="/guide/">使用指南</Link>
            </NavigationMenuLink>
          </NavigationMenuItem>
        </NavigationMenuList>
      </NavigationMenu>
    </article>
  );
}
