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
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
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
      aria-labelledby="recent-downloads-title"
      className="flex flex-col gap-3"
    >
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-base font-medium" id="recent-downloads-title">
          最近下载
        </h2>
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
        <ItemGroup>
          {items.map((item) => (
            <RecentDownloadItem item={item} key={item.id} />
          ))}
        </ItemGroup>
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
    <Item asChild>
      <Link href={`/downloads/detail?jobId=${encodeURIComponent(item.id)}`}>
        <ItemMedia className="w-28">
          <MediaCover
            alt={`${item.title} 媒体封面`}
            className="w-full"
            compact
            fallback={{
              detail: item.format_name,
              eyebrow: sourceLabel,
              title: item.title,
            }}
            src={item.thumbnail_url}
          />
        </ItemMedia>
        <ItemContent className="min-w-0">
          <ItemTitle className="line-clamp-1">{item.title}</ItemTitle>
          {active ? (
            <div className="flex max-w-80 items-center gap-3">
              <Progress
                aria-label={`${item.title} 下载进度`}
                value={item.progress}
              />
              <span className="shrink-0 font-mono text-sm text-muted-foreground">
                {item.progress}%
              </span>
            </div>
          ) : (
            <ItemDescription>
              {sourceLabel} · {item.format_name}
            </ItemDescription>
          )}
        </ItemContent>
        <ItemActions className="max-sm:basis-full max-sm:justify-between">
          <Badge variant={statusVariant(item.status)}>
            {downloadStatusLabels[item.status]}
          </Badge>
          <time
            className="w-20 text-right text-sm text-muted-foreground"
            dateTime={item.created_at}
          >
            {formatRelative(item.created_at)}
          </time>
        </ItemActions>
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
      <div aria-hidden className="flex flex-col gap-4">
        {['first', 'second', 'third'].map((key) => (
          <div className="flex items-center gap-4 px-3" key={key}>
            <Skeleton className="aspect-video w-28" />
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-4 w-2/5" />
              <Skeleton className="h-3 w-1/4" />
            </div>
          </div>
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
