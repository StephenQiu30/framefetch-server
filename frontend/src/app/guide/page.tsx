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
import { siteConfig } from '@/lib/site';

const title = '视频解析、AI 分析与自托管使用指南 · 帧取 FrameFetch';
const description =
  '了解 FrameFetch 如何导入视频与文档、调用内置 Skill 分析影视和整理文章，以及查看和导出报告。';
export const metadata = publicMetadata(title, description, '/guide/');

const sections = [
  {
    id: 'video-analysis',
    title: '如何从视频得到可复核的 AI 分析报告？',
    paragraphs: [
      '先导入自己拥有或已获授权的本地视频，也可以检查公开媒体链接、确认可用格式并下载。在成功的视频详情页选择当前可用的成片审阅或素材拆解 Skill，使用原分析表单提交。',
      '服务端 Worker 读取该次输入并执行 Skill，返回相应分析报告。关键结论应对照视频、源时间与实际观察范围核查；可查看结果并导出 Markdown 或 DOCX。',
      '媒体处理成功不代表分析已经完成；AI 服务不可用时，检查管理员配置的模型 Provider 与 AI Worker 状态。',
    ],
    source: '/blob/main/README.md#产品能力',
    sourceLabel: '查看 AI 视频分析与报告能力',
  },
  {
    id: 'screenplays',
    title: '如何处理剧本文档？',
    paragraphs: [
      '上传 Markdown、Fountain、TXT、PDF 或 DOCX 文档，在原文档详情阅读正文并选择故事审稿、文章、公众号或小红书整理 Skill。整理保持完整原文与事实，结果沿原报告操作查看和导出。',
      '文档是否能够完整提取取决于原文件结构。扫描件、复杂版式或缺失文本的文件需要检查导入结果，不能仅凭任务成功就判断原文已经完整保留。',
    ],
    source: '/blob/main/README.md#产品能力',
    sourceLabel: '查看当前文档处理能力',
  },
  {
    id: 'deployment',
    title: '自托管需要部署哪些服务？',
    paragraphs: [
      'video-server 包含 Next.js Web 页面、FastAPI API，以及独立的下载、媒体处理与 AI Worker。Docker Compose 管理业务服务，并连接部署者已有的 PostgreSQL、RabbitMQ、Redis 和 MinIO。默认 Web 端口为 8101，API 端口为 8111。',
      '使用根 README 的快速开始说明安装和配置，按实际需求启用模型服务与媒体 Provider。MIT 许可证开放源代码；基础设施、存储、流量和外部模型的费用由部署者承担。',
      '自托管不表示数据永远不离开设备：使用外部 AI Provider 时，分析所需内容会发送到该服务。启用模型前应核对其数据处理约定，并确认素材可用于该分析。',
    ],
    source: '/blob/main/README.md#快速开始',
    sourceLabel: '阅读自托管部署步骤',
  },
  {
    id: 'clients',
    title: 'Web 与 iOS / Android 客户端如何选择？',
    paragraphs: [
      'Web 随 video-server 部署，适合在浏览器中管理素材、任务、分析报告与管理员配置。video-app 是单独维护的 Flutter 原生客户端，面向 iOS 和 Android，需要连接可访问的 video-server。',
      '手机端负责上传、任务操作与结果展示，媒体处理与 AI 推理仍由服务端完成。当前移动端从源码构建，不提供 App Store 或 Google Play 预构建安装包，也不提供离线 AI。',
    ],
    source: siteConfig.mobileRepositoryUrl,
    sourceLabel: '查看 Flutter 移动客户端与构建说明',
  },
  {
    id: 'availability',
    title: '为什么同一个平台的不同链接会有不同结果？',
    paragraphs: [
      '平台支持由部署实例、Provider 版本、访问条件和内容授权共同决定。存在某个平台的适配器，并不意味着该平台的所有链接均可处理。以当前实例的链接检查、Provider 状态与最终文件验证为准。',
      '默认匿名流程面向可正向确认的公开、免费、非 DRM 内容。只处理自己有权使用的素材；账号能看到内容不能替代下载、导出或后续使用授权。',
    ],
    source: '/blob/main/README.md#产品能力',
    sourceLabel: '查看能力范围与运行边界',
  },
] as const;

export default function GuidePage() {
  const breadcrumbs = {
    '@context': 'https://schema.org',
    ...breadcrumbList([
      { name: siteConfig.name, path: '/' },
      { name: '使用指南', path: '/guide/' },
    ]),
  };
  return (
    <article className="inner-page flex flex-col gap-8">
      <div>
        <JsonLd data={breadcrumbs} />
        <PageNavigation
          fallbackHref="/"
          breadcrumbs={[{ label: '帧取', href: '/' }, { label: '使用指南' }]}
        />
        <PageHeader title="从素材到分析报告" description={description} />
      </div>
      <Item variant="muted">
        <ItemContent>
          <ItemDescription className="line-clamp-none">
            本指南介绍当前产品流程。配置与实现以链接的仓库文档为准，实例可用性以实际检查结果为准。
          </ItemDescription>
        </ItemContent>
      </Item>
      <SplitLayout columns="sidebar-start">
        <nav aria-label="指南目录" className="self-start">
          <ul className="flex flex-col gap-4">
            {sections.map(({ id, title: sectionTitle }) => (
              <li key={id}>
                <Button
                  asChild
                  className="w-full justify-start whitespace-normal"
                  variant="ghost"
                >
                  <a href={`#${id}`}>{sectionTitle}</a>
                </Button>
              </li>
            ))}
          </ul>
        </nav>
        <ItemGroup className="gap-6" role="presentation">
          {sections.map(
            ({ id, title: sectionTitle, paragraphs, source, sourceLabel }) => (
              <Item asChild variant="muted" key={id}>
                <section
                  id={id}
                  aria-labelledby={`${id}-title`}
                  className="scroll-mt-24"
                >
                  <ItemContent className="gap-4">
                    <ItemTitle className="line-clamp-none">
                      <h2 id={`${id}-title`}>{sectionTitle}</h2>
                    </ItemTitle>
                    {paragraphs.map((paragraph) => (
                      <ItemDescription
                        className="line-clamp-none"
                        key={paragraph}
                      >
                        {paragraph}
                      </ItemDescription>
                    ))}
                    <Button
                      asChild
                      className="self-start whitespace-normal"
                      variant="ghost"
                    >
                      <a
                        href={
                          source.startsWith('https:')
                            ? source
                            : `${siteConfig.repositoryUrl}${source}`
                        }
                      >
                        {sourceLabel}
                      </a>
                    </Button>
                  </ItemContent>
                </section>
              </Item>
            ),
          )}
        </ItemGroup>
      </SplitLayout>
      <nav aria-label="延伸阅读" className="flex flex-wrap gap-3">
        <Button asChild variant="ghost">
          <a href="/#questions">返回首页常见问题</a>
        </Button>
        <Button asChild variant="ghost">
          <a href="/self-hosting/">自托管部署指南</a>
        </Button>
      </nav>
    </article>
  );
}
