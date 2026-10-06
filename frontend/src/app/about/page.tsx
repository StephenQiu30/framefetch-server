import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { SplitLayout } from '@/components/layout/split-layout';
import { breadcrumbList, JsonLd } from '@/components/seo/json-ld';
import { Button } from '@/components/ui/button';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from '@/components/ui/item';
import { publicMetadata } from '@/lib/public-metadata';
import { absoluteUrl, siteConfig } from '@/lib/site';

const title = '关于帧取 FrameFetch：开源个人视频工具的定位、原则与边界';
const description =
  '帧取 FrameFetch 是 MIT 开源、可自托管的视频解析、剧本文档处理与 AI 视频分析项目。了解它面向谁、采用哪些工程原则、如何处理内容授权，以及服务端与移动端仓库的关系。';
export const metadata = publicMetadata(title, description, '/about/');

const audiences = [
  {
    name: '创作者',
    text: '整理自己拥有或已获授权的素材，用分镜、场景与关键帧证据复盘作品结构。',
  },
  {
    name: '内容研究者',
    text: '把视频与剧本文档组织为可追踪的任务，并导出 Markdown / DOCX 报告用于审阅。',
  },
  {
    name: '开发者',
    text: '在自己的基础设施上运行 FastAPI、Next.js 与 Worker，通过 OpenAPI 契约扩展 Web 或移动端。',
  },
];

const principles = [
  {
    name: '可恢复',
    text: 'PostgreSQL 保存任务事实，Transactional Outbox 保证数据库状态与消息意图一致；实时连接只用于展示进度。',
  },
  {
    name: '可隔离',
    text: '下载、媒体命令与 AI 长任务不在 HTTP 请求进程中执行，Runner 经过阻断私网的受控出口代理。',
  },
  {
    name: '可验证',
    text: 'Provider 返回值不会直接成为最终文件；Worker 重新解析并校验格式、时长、大小与 SHA-256 后才写入存储。',
  },
  {
    name: '可自托管',
    text: '数据保存在部署者配置的基础设施中，项目不依赖官方托管服务，也不内置第三方追踪器。',
  },
];

const repositories = [
  {
    name: 'video-server',
    href: siteConfig.repositoryUrl,
    text: 'FastAPI API、Next.js Web、下载 / 文档 / 报告 Worker、隔离 Media Runner 与 Docker Compose 部署。',
  },
  {
    name: 'video-app',
    href: siteConfig.mobileRepositoryUrl,
    text: '连接自托管 video-server 的 Flutter iOS / Android 客户端；媒体处理与 AI 推理仍在服务端执行。',
  },
];

export default function AboutPage() {
  const structuredData = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'AboutPage',
        '@id': absoluteUrl('/about/#webpage'),
        url: absoluteUrl('/about/'),
        name: title,
        description,
        inLanguage: 'zh-CN',
        isPartOf: { '@id': absoluteUrl('/#website') },
        about: { '@id': absoluteUrl('/#software') },
      },
      breadcrumbList([
        { name: siteConfig.name, path: '/' },
        { name: '关于', path: '/about/' },
      ]),
    ],
  };

  return (
    <article className="inner-page flex flex-col gap-8">
      <div>
        <JsonLd data={structuredData} />
        <PageNavigation fallbackHref="/" />
        <PageHeader title="关于帧取" description={description} />
      </div>
      <SplitLayout>
        <section
          id="audience"
          aria-labelledby="audience-title"
          className="flex flex-col gap-4"
        >
          <ItemTitle>
            <h2 id="audience-title">帧取为谁而做？</h2>
          </ItemTitle>
          <ItemGroup>
            {audiences.map(({ name, text }) => (
              <Item variant="muted" key={name} role="listitem">
                <ItemContent>
                  <ItemTitle>{name}</ItemTitle>
                  <ItemDescription className="line-clamp-none">
                    {text}
                  </ItemDescription>
                </ItemContent>
              </Item>
            ))}
          </ItemGroup>
        </section>
        <section
          id="principles"
          aria-labelledby="principles-title"
          className="flex flex-col gap-4"
        >
          <ItemTitle>
            <h2 id="principles-title">为什么采用异步工作流架构？</h2>
          </ItemTitle>
          <ItemGroup>
            {principles.map(({ name, text }) => (
              <Item variant="muted" key={name} role="listitem">
                <ItemContent>
                  <ItemTitle>{name}</ItemTitle>
                  <ItemDescription className="line-clamp-none">
                    {text}
                  </ItemDescription>
                </ItemContent>
              </Item>
            ))}
          </ItemGroup>
        </section>
      </SplitLayout>
      <Item asChild variant="muted">
        <section id="boundaries" aria-labelledby="boundaries-title">
          <ItemContent className="gap-4">
            <ItemTitle>
              <h2 id="boundaries-title">下载与使用边界</h2>
            </ItemTitle>
            <ItemDescription className="line-clamp-none">
              默认只处理用户有权使用、公开、免费且非 DRM 的 HTTP(S)
              内容。账号身份不扩张下载范围，受保护的内容可通过有权处理的本地文件导入。私网
              URL、任意 yt-dlp 参数和 shell 输入始终禁止。
            </ItemDescription>
            <ItemDescription className="line-clamp-none">
              MIT
              许可证授予软件的使用、修改和分发权，不代表授予第三方媒体的下载、复制或分析权。项目不提供官方
              SaaS、公共演示站或服务可用性 SLA。
            </ItemDescription>
          </ItemContent>
        </section>
      </Item>
      <section
        id="repositories"
        aria-labelledby="repositories-title"
        className="flex flex-col gap-4"
      >
        <ItemTitle>
          <h2 id="repositories-title">源码在哪里？</h2>
        </ItemTitle>
        <ItemGroup>
          {repositories.map(({ name, href, text }) => (
            <Item key={name} role="listitem">
              <ItemContent>
                <ItemTitle>
                  <Button asChild variant="link">
                    <a href={href}>{name}</a>
                  </Button>
                </ItemTitle>
                <ItemDescription className="line-clamp-none">
                  {text}
                </ItemDescription>
              </ItemContent>
            </Item>
          ))}
        </ItemGroup>
        <ItemDescription className="line-clamp-none">
          项目由{' '}
          <a href={siteConfig.maintainer.url}>{siteConfig.maintainer.name}</a>{' '}
          维护，欢迎通过 Issue 或 Pull Request 参与 Provider
          适配、前端与移动端体验、AI 报告、测试和文档建设。安全问题请按{' '}
          <a href={`${siteConfig.repositoryUrl}/blob/main/SECURITY.md`}>
            安全策略
          </a>{' '}
          私下报告。
        </ItemDescription>
      </section>
    </article>
  );
}
