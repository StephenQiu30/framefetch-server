import {
  ArrowRightIcon,
  ArrowUpRightIcon,
  GithubLogoIcon,
} from '@phosphor-icons/react/dist/ssr';
import Link from 'next/link';

import {
  PublicHomeCapabilities,
  PublicHomeSafeguards,
  PublicHomeWorkflow,
} from '@/components/intake/public-home-details';
import { PublicHomeFaq } from '@/components/intake/public-home-faq';
import { EditorialIntro } from '@/components/layout/editorial-intro';
import { SplitLayout } from '@/components/layout/split-layout';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { siteConfig } from '@/lib/site';

const capabilities = [
  [
    '公开视频',
    '公开视频工作流',
    '解析有权处理的公开链接，选择真实可用格式，并跟踪下载与最终制品。',
  ],
  [
    '剧本文档',
    '剧本与文档处理',
    '在内容工作台上传获授权的剧本文档，核对确认原文后分析；剧本文档区保留阅读与历史处理记录。',
  ],
  [
    'AI 分析',
    '结构化 AI 视频分析',
    '围绕剧情、人物、叙事、镜头与连续性形成分析候选，对照原始材料和关键帧核查。',
  ],
] as const;

const workflow = [
  ['解析', '识别公开媒体或文章中的候选视频'],
  ['选择', '确认目标与格式，避免隐式下载'],
  ['执行', '由隔离 Worker 处理下载、导入和分析'],
  ['交付', '通过授权短时入口预览或获取制品'],
] as const;

const safeguards = [
  '浏览器会话采用 HttpOnly Cookie；原生客户端使用可轮换令牌。',
  '下载、导入与 AI 分析通过独立队列和 Worker 执行。',
  '短时制品入口、所有者隔离与授权边界贯穿完整链路。',
  '公开视频并不等于可自由使用，请仅处理已获授权的内容。',
] as const;

export function PublicHome() {
  return (
    <div className="flex flex-col pb-6" data-home-view-root="public">
      <SplitLayout
        className="gap-12 pb-12 pt-10 sm:pt-12 lg:gap-24 lg:pb-16 lg:pt-14"
        columns="primary"
        data-slot="borderless-section"
      >
        <EditorialIntro
          description="开源、自托管地完成公开视频解析、本地视频与剧本文档导入、制品管理和 AI 分析。数据与运行边界由你掌控。"
          eyebrow="帧取 FrameFetch · 开源视频工作流"
          title={
            <>
              把素材，
              <span className="block sm:inline">带回本地。</span>
            </>
          }
          titleClassName="max-w-4xl sm:whitespace-nowrap"
        >
          <div className="mt-8 flex flex-wrap gap-3">
            <Button asChild size="lg">
              <Link href="/user/register">
                创建本地账户
                <ArrowRightIcon aria-hidden data-icon="inline-end" />
              </Link>
            </Button>
            <Button asChild size="lg" variant="secondary">
              <a
                href={siteConfig.repositoryUrl}
                rel="noreferrer"
                target="_blank"
              >
                <GithubLogoIcon aria-hidden data-icon="inline-start" />
                查看源代码
                <ArrowUpRightIcon aria-hidden data-icon="inline-end" />
              </a>
            </Button>
          </div>
        </EditorialIntro>

        <div>
          <Badge className="w-fit" variant="secondary">
            工作流
          </Badge>
          <h2
            className="mt-4 text-xl font-medium leading-snug"
            id="workflow-title"
          >
            一套可审计的完整链路
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            从识别到交付，每一步都有明确边界。
          </p>
          <div className="mt-8">
            <PublicHomeWorkflow items={workflow} />
          </div>
        </div>
      </SplitLayout>

      <div
        className="scroll-mt-24 py-12 lg:py-16"
        data-slot="borderless-section"
        id="capabilities"
      >
        <EditorialIntro
          as="h2"
          description="Web 控制面、API 与 Worker 共享同一套权限、任务和制品模型，适合个人本地使用，也便于团队自托管。"
          eyebrow="核心功能"
          title="视频解析、剧本处理与 AI 分析"
          titleId="capabilities-title"
        />
        <PublicHomeCapabilities items={capabilities} />
      </div>

      <SplitLayout
        className="scroll-mt-24 gap-12 py-12 lg:gap-24 lg:py-16"
        data-slot="borderless-section"
        id="architecture"
      >
        <EditorialIntro
          as="h2"
          description="FastAPI、Next.js、PostgreSQL、RabbitMQ、MinIO、FFmpeg 与 yt-dlp 组成可独立部署的工作流。MIT 许可证允许你免费检查、修改和自托管。"
          eyebrow="自托管架构"
          title="开源，不交出数据控制权"
          titleId="architecture-title"
        />
        <div>
          <Badge className="w-fit" variant="secondary">
            安全边界
          </Badge>
          <h3 className="mt-4 text-xl font-medium leading-snug">
            运行与授权边界
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            把访问、执行和交付拆成可检查的边界。
          </p>
          <div className="mt-8">
            <PublicHomeSafeguards items={safeguards} />
          </div>
        </div>
      </SplitLayout>

      <PublicHomeFaq />

      <div
        className="flex flex-col items-start justify-between gap-8 py-12 sm:flex-row sm:items-end lg:py-16"
        data-slot="borderless-section"
      >
        <EditorialIntro
          as="h2"
          description="从仓库的 Quick Start、架构文档和安全边界开始，按需启用媒体解析、剧本工作流与 AI 服务。"
          eyebrow="快速开始"
          title="在自己的基础设施上运行 FrameFetch"
        />
        <Button asChild size="lg" variant="secondary">
          <a href={`${siteConfig.repositoryUrl}/blob/main/README.md#快速开始`}>
            阅读部署说明
            <ArrowUpRightIcon aria-hidden data-icon="inline-end" />
          </a>
        </Button>
      </div>
    </div>
  );
}
