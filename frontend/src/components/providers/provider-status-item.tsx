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
  optional: '可选登录',
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

  return (
    <TableRow>
      <TableHead className="max-w-0 text-left whitespace-normal" scope="row">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="font-medium">{provider.display_name}</h2>
          <p className="truncate font-mono text-xs font-normal text-muted-foreground">
            {provider.key}
          </p>
        </div>
      </TableHead>
      <TableCell className="whitespace-normal">
        <div className="flex flex-col items-start gap-1.5">
          <Badge variant="secondary">{status}</Badge>
          <p className="text-xs text-muted-foreground">
            {IDENTITY_LABELS[provider.identity]}
          </p>
        </div>
      </TableCell>
      <TableCell className="hidden whitespace-normal sm:table-cell">
        {capabilities || '暂无已登记能力'}
      </TableCell>
      <TableCell className="whitespace-normal">
        {provider.user_action || '下载结果以实际文件为准。'}
      </TableCell>
    </TableRow>
  );
}
