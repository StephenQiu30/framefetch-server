'use client';

import { ArrowRight, FilmStrip } from '@phosphor-icons/react';

import { Button } from '@/components/ui/button';
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
} from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';

const headerClassName = 'flex flex-wrap items-end justify-between gap-3 pb-5';

enum DiscoveryItemStatusCode {
  Ready = 'ready',
  IdentityUnverified = 'identity_unverified',
}

enum DiscoveryDecisionCode {
  Candidate = 'candidate',
  ExportRequired = 'export_required',
  Unsupported = 'unsupported',
}

const DISCOVERY_DECISION_LABELS: Record<API.DiscoveryDecisionHint, string> = {
  [DiscoveryDecisionCode.Candidate]: '已发现，下载能力待验收',
  [DiscoveryDecisionCode.ExportRequired]: '需要导入自有文件',
  [DiscoveryDecisionCode.Unsupported]: '仅查看支持状态',
};

const DISCOVERY_STATUS_PRESENTATION: Record<
  API.DiscoveryItemStatus,
  (item: API.SourceDiscoveryItemResponse) => string
> = {
  [DiscoveryItemStatusCode.Ready]: (item) =>
    DISCOVERY_DECISION_LABELS[item.decision_hint],
  [DiscoveryItemStatusCode.IdentityUnverified]: () => '身份无法可靠绑定',
};

export function SourceDiscoveryWorkspace({
  busyItemRef,
  discovery,
  onSelect,
}: {
  busyItemRef: string | null;
  discovery: API.SourceDiscoveryResponse;
  onSelect: (item: API.SourceDiscoveryItemResponse) => void;
}) {
  return (
    <div className="pt-10">
      <div className={headerClassName}>
        <div>
          <h2
            className="text-xl font-medium tracking-tight"
            id="source-discovery-title"
          >
            {discovery.title}
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {discovery.items.length > 0
              ? `发现 ${discovery.items.length} 个视频嵌入，请明确选择要处理的项目。`
              : '这篇公开文章中没有发现可识别的视频嵌入。'}
          </p>
        </div>
        <p className="text-xs text-muted-foreground">不会自动选择第一项</p>
      </div>

      {discovery.items.length > 0 ? (
        <ul aria-label="文章视频候选项" className="flex flex-col gap-1">
          {discovery.items.map((item, index) => {
            const busy = busyItemRef === item.item_ref;
            return (
              <Item asChild className="-mx-3 gap-4" key={item.item_ref}>
                <li>
                  <ItemMedia className="self-start">
                    <FilmStrip
                      aria-hidden
                      className="text-muted-foreground"
                      size={22}
                    />
                  </ItemMedia>
                  <ItemContent className="min-w-0">
                    <h3 className="truncate">
                      {item.title || `文章视频 ${index + 1}`}
                    </h3>
                    <ItemDescription className="mt-0">
                      {itemKindLabel(item.kind)} · {decisionLabel(item)}
                    </ItemDescription>
                  </ItemContent>
                  <ItemActions className="w-full sm:w-auto">
                    <Button
                      className="w-full sm:w-auto"
                      disabled={busyItemRef !== null}
                      onClick={() => onSelect(item)}
                      variant="secondary"
                    >
                      {busy ? (
                        <Spinner aria-hidden data-icon="inline-start" />
                      ) : (
                        <ArrowRight aria-hidden data-icon="inline-start" />
                      )}
                      {busy ? '处理中…' : '选择并查看'}
                    </Button>
                  </ItemActions>
                </li>
              </Item>
            );
          })}
        </ul>
      ) : (
        <p className="py-8 text-sm text-muted-foreground" role="status">
          请检查文章是否仍公开，或改用自有明文 MP4 导入。
        </p>
      )}
    </div>
  );
}

export function SourceDiscoverySkeleton() {
  return (
    <div aria-label="正在读取文章视频候选项" className="pt-10" role="status">
      <div aria-hidden className={headerClassName}>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <Skeleton className="h-7 w-3/4" />
          <Skeleton className="h-6 w-full" />
        </div>
        <Skeleton className="h-4 w-28" />
      </div>
      <div aria-hidden className="flex flex-col gap-1">
        {['first', 'second', 'third'].map((key) => (
          <Item className="-mx-3 gap-4" key={key}>
            <ItemMedia className="self-start">
              <Skeleton className="size-6" />
            </ItemMedia>
            <ItemContent className="min-w-0">
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-5 w-full" />
            </ItemContent>
            <ItemActions className="w-full sm:w-auto">
              <Skeleton className="h-8 w-full sm:w-28" />
            </ItemActions>
          </Item>
        ))}
      </div>
    </div>
  );
}

function itemKindLabel(kind: API.SourceDiscoveryItemResponse['kind']) {
  if (kind === 'official_account_native') return '公众号原生视频';
  if (kind === 'tencent_video') return '腾讯视频';
  if (kind === 'wechat_channels') return '微信视频号';
  return '未知嵌入';
}

function decisionLabel(item: API.SourceDiscoveryItemResponse) {
  return DISCOVERY_STATUS_PRESENTATION[item.status](item);
}
