'use client';

import { ArrowRightIcon, DownloadSimpleIcon } from '@phosphor-icons/react';
import Link from 'next/link';
import {
  downloadStatusLabels,
  isActiveDownloadStatus,
  statusVariant,
} from '@/components/downloads/download-state-model';
import { useDownloadHistory } from '@/components/downloads/use-download-history';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import MediaCover from '@/components/media/media-cover';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from '@/components/ui/item';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';

const RECENT_LIMIT = 4;
export function RecentDownloads() {
  const history = useDownloadHistory({ page: 1, page_size: RECENT_LIMIT });
  const items = history.data?.items ?? [];

  return (
    <section
      aria-busy={history.loading && !history.data}
      aria-labelledby="recent-downloads-title"
      className="flex flex-col gap-3"
    >
      <div className="flex items-center justify-between gap-4">
        <ItemTitle>
          <h2 id="recent-downloads-title">最近下载</h2>
        </ItemTitle>
        <Button asChild variant="ghost">
          <Link href="/history">
            全部记录
            <ArrowRightIcon aria-hidden data-icon="inline-end" />
          </Link>
        </Button>
      </div>
      {history.loading && !history.data ? <RecentLoading /> : null}
      {history.error && !history.data ? (
        <FeedbackNotice
          action={
            <Button onClick={history.retry} variant="outline">
              重新加载
            </Button>
          }
          description={history.error}
          title="最近下载暂时无法加载"
          tone="error"
        />
      ) : null}
      {history.data && !items.length ? (
        <PageEmptyNotice
          compact
          description="粘贴视频链接后，下载任务会显示在这里。"
          icon={<DownloadSimpleIcon aria-hidden />}
          title="还没有下载记录"
        />
      ) : null}
      {items.length ? (
        <ul className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
          {items.map((item) => (
            <li key={item.id} className="min-w-0">
              <RecentDownloadItem item={item} />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function RecentDownloadItem({
  item,
}: {
  item: API.DownloadHistoryItemResponse;
}) {
  const active = isActiveDownloadStatus(item.status);
  const sourceLabel = displaySourceLabel(item);

  return (
    <Item asChild className="flex-col items-stretch gap-3">
      <Link href={`/downloads/detail?jobId=${encodeURIComponent(item.id)}`}>
        <div className="relative w-full" data-slot="recent-download-cover">
          <MediaCover
            alt={`${item.title} 媒体封面`}
            compact
            lazy
            fallback={{
              detail: item.format_name,
              eyebrow: sourceLabel,
              title: item.title,
            }}
            src={item.thumbnail_url}
          />
          <Badge
            className="absolute left-3 top-3"
            variant={statusVariant(item.status)}
          >
            {downloadStatusLabels[item.status]}
            {active ? ` ${item.progress}%` : ''}
          </Badge>
          {active ? (
            <Progress
              className="absolute inset-x-0 bottom-0"
              aria-label={`${item.title} 下载进度`}
              value={item.progress}
            />
          ) : null}
        </div>
        <ItemContent className="min-w-0 w-full">
          <ItemTitle className="w-full">
            <span className="truncate">{item.title}</span>
          </ItemTitle>
          <ItemDescription className="line-clamp-1">
            {sourceLabel} ·{' '}
            <time dateTime={item.created_at}>
              {formatRelative(item.created_at)}
            </time>
          </ItemDescription>
        </ItemContent>
      </Link>
    </Item>
  );
}

function RecentLoading() {
  return (
    <>
      <span className="sr-only" role="status">
        正在加载最近下载
      </span>
      <div aria-hidden className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        {['first', 'second', 'third', 'fourth'].map((key) => (
          <Item className="flex-col items-stretch gap-3" key={key}>
            <Skeleton className="aspect-video w-full" />
            <ItemContent className="min-w-0 w-full">
              <Skeleton className="aspect-[12/1] w-2/3" />
              <Skeleton className="aspect-[12/1] w-1/2" />
            </ItemContent>
          </Item>
        ))}
      </div>
    </>
  );
}

function displaySourceLabel(item: API.DownloadHistoryItemResponse) {
  return item.source_kind === 'remote_provider' &&
    item.source_label === 'WechatChannelsPublic'
    ? '微信视频号'
    : item.source_label;
}

const relativeFormatter = new Intl.RelativeTimeFormat('zh-CN', {
  numeric: 'auto',
});
const dayFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: 'short',
  day: 'numeric',
});

function formatRelative(value: string) {
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return relativeFormatter.format(-minutes, 'minute');
  const hours = Math.round(minutes / 60);
  if (hours < 24) return relativeFormatter.format(-hours, 'hour');
  if (hours < 48) return '昨天';
  return dayFormatter.format(new Date(value));
}
