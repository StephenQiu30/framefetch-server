'use client';

import { isDownloadEnabled } from '@/components/providers/provider-availability';
import { Badge } from '@/components/ui/badge';
import { ItemContent, ItemDescription, ItemTitle } from '@/components/ui/item';
import { TableCell, TableHead, TableRow } from '@/components/ui/table';

const CAPABILITY_LABELS: Record<API.ProviderCapability, string> = {
  single_video: '单视频',
  short_video: '短视频',
  clip_or_vod: '片段/VOD',
  audio_video_split: '音视频分离',
  subtitles: '字幕',
  image_or_carousel: '图文/轮播',
  live: '直播',
  playlist: '播放列表',
};

const IDENTITY_LABELS = {
  none: '无需登录',
  prefer: '优先登录',
  required: '需要登录',
};

export function ProviderStatusItem({
  provider,
}: {
  provider: API.ProviderListResponse['items'][number];
}) {
  const enabled = isDownloadEnabled(provider);
  const capabilities = provider.capabilities
    .map((capability) => CAPABILITY_LABELS[capability])
    .join(' · ');
  const status = enabled
    ? '已接入'
    : provider.status === 'unsupported'
      ? '不支持'
      : '未开放';
  const identity = IDENTITY_LABELS[provider.identity];
  const capabilitySummary = capabilities || '暂无已登记能力';
  const description = provider.user_action || '下载结果以实际文件为准。';

  return (
    <TableRow>
      <TableHead
        className="whitespace-normal [overflow-wrap:anywhere] lg:w-1/5"
        scope="row"
      >
        <ItemContent className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <ItemTitle>
              <h2>{provider.display_name}</h2>
            </ItemTitle>
            <Badge variant={enabled ? 'default' : 'secondary'}>{status}</Badge>
          </div>
          <ItemDescription>{provider.key}</ItemDescription>
          <ItemContent className="mt-2 lg:hidden">
            <ItemDescription className="line-clamp-none">
              {identity}
            </ItemDescription>
            <ItemDescription className="line-clamp-none">
              {capabilitySummary}
            </ItemDescription>
            <ItemDescription className="line-clamp-none">
              {description}
            </ItemDescription>
          </ItemContent>
        </ItemContent>
      </TableHead>
      <TableCell className="hidden whitespace-normal lg:table-cell">
        <ItemDescription className="line-clamp-none">
          {identity}
        </ItemDescription>
      </TableCell>
      <TableCell className="hidden whitespace-normal lg:table-cell lg:w-1/4">
        {capabilitySummary}
      </TableCell>
      <TableCell className="hidden whitespace-normal [overflow-wrap:anywhere] lg:table-cell">
        {description}
      </TableCell>
    </TableRow>
  );
}
