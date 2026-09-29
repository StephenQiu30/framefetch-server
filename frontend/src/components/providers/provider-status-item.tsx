'use client';

import { CaretDownIcon } from '@phosphor-icons/react';
import { cn } from 'cn';
import { useId, useState } from 'react';
import {
  isCurrentlyAvailable,
  ProviderAccessStateCode,
  ProviderSupportStatusCode,
} from '@/components/providers/provider-availability';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { TableCell, TableHead, TableRow } from '@/components/ui/table';

const STATUS_LABELS = {
  [ProviderSupportStatusCode.Unknown]: '待验证',
  [ProviderSupportStatusCode.Verified]: '已验证',
  [ProviderSupportStatusCode.Degraded]: '服务降级',
  [ProviderSupportStatusCode.AccessRequired]: '需要平台授权',
  [ProviderSupportStatusCode.RateLimited]: '平台限流',
  [ProviderSupportStatusCode.Blocked]: '出口受限',
  [ProviderSupportStatusCode.Disabled]: '已停用',
  [ProviderSupportStatusCode.Unsupported]: '不支持',
} satisfies Record<API.ProviderSupportStatus, string>;

const SUPPORTED_STATUS_LABELS: Partial<
  Record<API.ProviderSupportStatus, string>
> = {
  [ProviderSupportStatusCode.AccessRequired]: '已接入 · 当前不可用',
  [ProviderSupportStatusCode.Degraded]: '支持下载 · 当前降级',
  [ProviderSupportStatusCode.RateLimited]: '支持下载 · 当前限流',
  [ProviderSupportStatusCode.Blocked]: '支持下载 · 当前受限',
};
const UNKNOWN_SUPPORTED_STATUS_LABEL = '支持下载 · 待复验';

const STATUS_VARIANTS = {
  [ProviderSupportStatusCode.Unknown]: 'secondary',
  [ProviderSupportStatusCode.Verified]: 'secondary',
  [ProviderSupportStatusCode.Degraded]: 'secondary',
  [ProviderSupportStatusCode.AccessRequired]: 'secondary',
  [ProviderSupportStatusCode.RateLimited]: 'secondary',
  [ProviderSupportStatusCode.Blocked]: 'destructive',
  [ProviderSupportStatusCode.Disabled]: 'secondary',
  [ProviderSupportStatusCode.Unsupported]: 'destructive',
} satisfies Record<
  API.ProviderSupportStatus,
  'destructive' | 'secondary' | 'default'
>;

const INTEGRATION_DESCRIPTIONS = {
  [ProviderSupportStatusCode.Unknown]: '解析器已部署',
  [ProviderSupportStatusCode.Verified]: '解析器已部署',
  [ProviderSupportStatusCode.Degraded]: '解析器已部署',
  [ProviderSupportStatusCode.AccessRequired]: '解析器已部署',
  [ProviderSupportStatusCode.RateLimited]: '解析器已部署',
  [ProviderSupportStatusCode.Blocked]: '解析器已部署',
  [ProviderSupportStatusCode.Disabled]: '仅识别链接，未开放下载',
  [ProviderSupportStatusCode.Unsupported]: '解析器已部署',
} satisfies Record<API.ProviderSupportStatus, string>;

const DOWNLOAD_INTEGRATION_DESCRIPTIONS = {
  [ProviderSupportStatusCode.Unknown]: '下载解析器已部署',
  [ProviderSupportStatusCode.Verified]: '下载解析器已部署',
  [ProviderSupportStatusCode.Degraded]: '下载解析器已部署',
  [ProviderSupportStatusCode.AccessRequired]: '下载解析器已部署',
  [ProviderSupportStatusCode.RateLimited]: '下载解析器已部署',
  [ProviderSupportStatusCode.Blocked]: '下载解析器已部署',
  [ProviderSupportStatusCode.Disabled]: '仅识别链接，未开放下载',
  [ProviderSupportStatusCode.Unsupported]: '下载解析器已部署',
} satisfies Record<API.ProviderSupportStatus, string>;

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

export function ProviderStatusItem({
  provider,
}: {
  provider: API.ProviderListResponse['items'][number];
}) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  const capabilities = provider.capabilities
    .map((capability) => CAPABILITY_LABELS[capability])
    .join(' · ');

  return (
    <>
      <TableRow>
        <TableHead className="max-w-0 text-left whitespace-normal" scope="row">
          <div className="flex min-w-0 flex-col gap-1">
            <h2 className="font-medium">{provider.display_name}</h2>
            <p className="truncate font-mono text-xs font-normal text-muted-foreground">
              {provider.key} · {integrationDescription(provider)}
            </p>
          </div>
        </TableHead>
        <TableCell className="whitespace-normal">
          <div className="flex flex-col items-start gap-1.5">
            <Badge variant={statusVariant(provider)}>
              {statusLabel(provider)}
            </Badge>
            <p className="text-xs text-muted-foreground">
              {accessStateLabel(provider.access_state)}
            </p>
          </div>
        </TableCell>
        <TableCell className="hidden whitespace-normal sm:table-cell">
          {capabilities || '暂无已登记能力'}
        </TableCell>
        <TableCell className="text-right whitespace-nowrap">
          <Button
            aria-label="验证详情"
            aria-controls={expanded ? detailsId : undefined}
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
            size="sm"
            variant="ghost"
          >
            <span className="hidden sm:inline">验证</span>详情
            <CaretDownIcon
              aria-hidden
              className={cn(
                'transition-transform motion-reduce:transition-none',
                expanded && 'rotate-180',
              )}
            />
          </Button>
        </TableCell>
      </TableRow>
      {expanded ? (
        <TableRow>
          <TableCell className="whitespace-normal" colSpan={4}>
            <div
              className="grid grid-cols-1 gap-5 text-sm leading-6 text-muted-foreground sm:grid-cols-2"
              id={detailsId}
            >
              <div>
                <p className="font-medium text-foreground">验证记录</p>
                <p className="mt-1">{latestCheckDescription(provider)}</p>
                <p>{mediaVerificationDescription(provider)}</p>
                <p>{analysisVerificationDescription(provider)}</p>
              </div>
              <div>
                <p className="font-medium text-foreground">访问与下一步</p>
                <p className="mt-1">{accessDescription(provider)}</p>
                {provider.user_action ? <p>{provider.user_action}</p> : null}
              </div>
            </div>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

function accessStateLabel(state: API.ProviderAccessState): string {
  const labels: Record<API.ProviderAccessState, string> = {
    [ProviderAccessStateCode.PublicProbe]: '公开线路待验证',
    [ProviderAccessStateCode.PublicReady]: '公开线路可用',
    [ProviderAccessStateCode.AuthorizationRequired]: '需要授权或平台验证',
    [ProviderAccessStateCode.OperatorProbe]: '受控线路待验证',
    [ProviderAccessStateCode.OperatorReady]: '受控线路可用',
    [ProviderAccessStateCode.Degraded]: '服务降级',
    [ProviderAccessStateCode.Blocked]: '出口受限',
    [ProviderAccessStateCode.Disabled]: '已停用',
    [ProviderAccessStateCode.Unsupported]: '不支持',
  };
  return labels[state];
}

function statusLabel(
  provider: API.ProviderListResponse['items'][number],
): string {
  if (provider.download_supported) {
    if (isCurrentlyAvailable(provider)) return '当前可用';
    const statusLabel =
      provider.status === ProviderSupportStatusCode.Unknown
        ? undefined
        : SUPPORTED_STATUS_LABELS[provider.status];
    if (statusLabel) return statusLabel;
    if (provider.download_available) {
      return '近期媒体样本通过';
    }
    if (provider.status === ProviderSupportStatusCode.Unknown) {
      return UNKNOWN_SUPPORTED_STATUS_LABEL;
    }
    return '已接入 · 待重新验证';
  }
  if (
    provider.status === ProviderSupportStatusCode.Unknown &&
    provider.registered &&
    provider.extractor_exists
  ) {
    return '已接入，待验证';
  }
  return STATUS_LABELS[provider.status];
}

function integrationDescription(
  provider: API.ProviderListResponse['items'][number],
): string {
  if (!provider.registered) return '未登记';
  if (!provider.extractor_exists) return '已登记，暂无解析器';
  return provider.download_supported
    ? DOWNLOAD_INTEGRATION_DESCRIPTIONS[provider.status]
    : INTEGRATION_DESCRIPTIONS[provider.status];
}

function accessDescription(
  provider: API.ProviderListResponse['items'][number],
): string {
  const anonymous = provider.access_modes.includes('anonymous');
  const operatorManaged = provider.access_modes.includes('operator_managed');
  if (provider.default_access_policy_id === null) {
    if (operatorManaged && !anonymous) return '服务端受控线路已配置';
    if (operatorManaged) return '匿名公开内容 + 服务端受控线路';
    if (anonymous) return '仅匿名公开内容';
  }
  const routes = [
    anonymous && '匿名公开内容',
    operatorManaged && '服务端受控线路',
  ].filter(Boolean);
  if (routes.length === 0) return '当前未开放';
  const defaultRoute =
    provider.default_access_policy_id === 'public'
      ? '匿名公开线路'
      : provider.default_access_policy_id === 'operator_public' ||
          provider.default_access_policy_id === 'personal_entitled'
        ? '服务端受控线路'
        : null;
  return `${routes.join(' + ')}${
    defaultRoute ? ` · 默认：${defaultRoute}` : ''
  }`;
}

function latestCheckDescription(
  provider: API.ProviderListResponse['items'][number],
): string {
  if (!provider.last_checked_at || provider.last_check_succeeded === null) {
    return '状态检查：暂无当前版本记录';
  }
  const outcome = provider.last_check_succeeded ? '通过' : '未通过';
  return `状态检查：${formatDate(provider.last_checked_at, true)} · ${outcome}`;
}

function mediaVerificationDescription(
  provider: API.ProviderListResponse['items'][number],
): string {
  if (!provider.last_media_verified_at) return '真实下载：暂无当前版本证据';
  if (provider.download_available) {
    const sample =
      provider.default_access_policy_id === 'operator_public' ||
      provider.default_access_policy_id === 'personal_entitled'
        ? '受控线路样本'
        : provider.access_modes.includes('operator_managed') &&
            !provider.access_modes.includes('anonymous')
          ? '受控线路样本'
          : provider.access_modes.includes('anonymous')
            ? '公开样本'
            : '样本';
    return `${sample}下载：可用 · ${formatDate(
      provider.last_media_verified_at,
    )}`;
  }
  return `真实下载：${formatDate(provider.last_media_verified_at)}`;
}

function analysisVerificationDescription(
  provider: API.ProviderListResponse['items'][number],
): string {
  if (!provider.last_verified_at) return '完整分析：暂无当前版本证据';
  return `完整分析：${formatDate(provider.last_verified_at)}`;
}

function formatDate(value: string, includeTime = false): string {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    ...(includeTime ? { timeStyle: 'short' as const } : {}),
  }).format(new Date(value));
}

function statusVariant(
  provider: API.ProviderListResponse['items'][number],
): 'destructive' | 'secondary' | 'default' {
  if (
    isCurrentlyAvailable(provider) ||
    (!provider.download_supported &&
      provider.status === ProviderSupportStatusCode.Verified)
  ) {
    return 'default';
  }
  return STATUS_VARIANTS[provider.status];
}
