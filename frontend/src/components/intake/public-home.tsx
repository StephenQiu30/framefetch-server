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
import { PageHeader } from '@/components/layout/page-header';
import { SplitLayout } from '@/components/layout/split-layout';
import { Button } from '@/components/ui/button';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from '@/components/ui/item';
import { siteConfig } from '@/lib/site';

const capabilities = [
  [
    '公开视频',
    '粘贴链接，选择画质',
    '检查公开、免费、非 DRM 的视频链接，选择实际可用的格式并下载。平台与链接是否可用，以解析结果和最终文件为准。',
  ],
  [
    '本地导入',
    '视频与剧本文档',
    '导入有权处理的本地视频，以及 Markdown、Fountain、TXT、PDF 或 DOCX 剧本文档，在工作区查看与管理。',
  ],
  [
    'AI 分析',
    '从素材到分析报告',
    '按所选分析方式生成场景、分镜或报告，并导出 Markdown / DOCX。需要可用的 AI 服务和分析 Worker。',
  ],
] as const;
const workflow = [
  ['解析', '粘贴公开视频链接，或导入本地视频与剧本'],
  ['选择', '确认目标与可用画质'],
  ['执行', '查看下载、导入与分析的处理进度'],
  ['交付', '预览文件，下载素材或导出报告'],
] as const;
const safeguards = [
  '下载范围为可证明公开、免费、非 DRM 的 HTTP(S) 内容；实际能力以当前实例的链接检查为准。',
  '无法确认可下载的内容，可导入自己有权处理的本地文件。',
  '素材与任务保存在自己的部署中；使用外部 AI 服务时，分析所需内容会发送到该服务。',
  '公开视频不等于可自由使用，请仅处理已获授权的内容。',
] as const;

export function PublicHome() {
  return (
    <div
      className="inner-page flex flex-col gap-12"
      data-home-view-root="public"
    >
      <PageHeader
        size="lg"
        title="FrameFetch 万能视频下载器"
        description="粘贴公开视频链接，选择画质并下载。也可以导入本地视频与剧本文档，按需进行 AI 分析。"
      />
      <div className="flex flex-wrap gap-3">
        <Button asChild>
          <Link href="/user/register">
            创建本地账户
            <ArrowRightIcon aria-hidden data-icon="inline-end" />
          </Link>
        </Button>
        <Button asChild variant="secondary">
          <a href={siteConfig.repositoryUrl} rel="noreferrer" target="_blank">
            <GithubLogoIcon aria-hidden data-icon="inline-start" />
            查看源代码
            <ArrowUpRightIcon aria-hidden data-icon="inline-end" />
          </a>
        </Button>
        <Button asChild variant="ghost">
          <Link href="/user/login">登录账户</Link>
        </Button>
      </div>
      <SplitLayout columns="primary">
        <section
          aria-labelledby="capabilities-title"
          className="flex flex-col gap-4"
          id="capabilities"
        >
          <ItemTitle>
            <h2 id="capabilities-title">下载、导入与分析</h2>
          </ItemTitle>
          <PublicHomeCapabilities items={capabilities} />
        </section>
        <section
          aria-labelledby="workflow-title"
          className="flex flex-col gap-4"
        >
          <ItemTitle>
            <h2 id="workflow-title">从链接到文件</h2>
          </ItemTitle>
          <PublicHomeWorkflow items={workflow} />
        </section>
      </SplitLayout>
      <SplitLayout columns="primary" id="architecture">
        <section
          aria-labelledby="architecture-title"
          className="flex flex-col gap-4"
        >
          <ItemTitle>
            <h2 id="architecture-title">开源，可自托管</h2>
          </ItemTitle>
          <Item variant="muted">
            <ItemContent>
              <ItemTitle>在自己的基础设施上运行</ItemTitle>
              <ItemDescription className="line-clamp-none">
                帧取是 MIT
                开源的个人视频工具。源码可自行部署、使用和修改，服务器、存储、流量与外部
                AI 服务的运行成本由你承担。
              </ItemDescription>
            </ItemContent>
          </Item>
          <Button asChild className="self-start" variant="secondary">
            <a
              href={`${siteConfig.repositoryUrl}/blob/main/README.md#快速开始`}
            >
              阅读部署说明
              <ArrowUpRightIcon aria-hidden data-icon="inline-end" />
            </a>
          </Button>
        </section>
        <section aria-label="下载与使用边界">
          <PublicHomeSafeguards items={safeguards} />
        </section>
      </SplitLayout>
      <PublicHomeFaq />
    </div>
  );
}
