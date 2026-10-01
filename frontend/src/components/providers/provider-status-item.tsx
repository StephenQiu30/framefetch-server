'use client';

import { isDownloadEnabled } from '@/components/providers/provider-availability';
import { Badge } from '@/components/ui/badge';
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
        className="text-left whitespace-normal [overflow-wrap:anywhere] lg:w-1/5"
        scope="row"
      >
        <div className="flex min-w-0 flex-col gap-1.5">
          <h2 className="font-medium">{provider.display_name}</h2>
          <p className="font-mono text-xs font-normal text-muted-foreground">
            {provider.key}
          </p>
          <div className="mt-1 flex flex-col gap-2 font-normal lg:hidden">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{status}</Badge>
              <span className="text-xs text-muted-foreground">{identity}</span>
            </div>
            <p className="text-xs text-muted-foreground">{capabilitySummary}</p>
            <p className="text-sm">{description}</p>
          </div>
        </div>
      </TableHead>
      <TableCell className="hidden whitespace-normal lg:table-cell">
        <div className="flex flex-col items-start gap-1.5">
          <Badge variant="secondary">{status}</Badge>
          <p className="text-xs text-muted-foreground">{identity}</p>
        </div>
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
