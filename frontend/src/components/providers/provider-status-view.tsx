'use client';

import {
  ArrowClockwiseIcon,
  FunnelX,
  ShieldCheckIcon,
} from '@phosphor-icons/react';
import { type KeyboardEvent, useMemo, useState } from 'react';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import {
  DEFAULT_PAGE_SIZE,
  PagePagination,
} from '@/components/layout/page-pagination';
import { isDownloadEnabled } from '@/components/providers/provider-availability';
import { ProviderStatusItem } from '@/components/providers/provider-status-item';
import { useProviderStatuses } from '@/components/providers/use-provider-statuses';
import { Button } from '@/components/ui/button';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from '@/components/ui/item';
import { Spinner } from '@/components/ui/spinner';
import {
  Table,
  TableBody,
  TableCaption,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

type StatusFilter = 'all' | 'enabled' | 'disabled';
const STATUS_FILTERS: StatusFilter[] = ['all', 'enabled', 'disabled'];
const EMPTY_PROVIDERS: API.ProviderListResponse['items'][number][] = [];

export function ProviderStatusView() {
  const state = useProviderStatuses();
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const providers = state.data?.items ?? EMPTY_PROVIDERS;
  const filtered = useMemo(
    () => providers.filter((item) => matchesFilter(item, filter)),
    [filter, providers],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages);
  const visibleProviders = filtered.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );

  return (
    <div className="inner-page">
      <PageNavigation fallbackHref="/" />
      <PageHeader
        action={
          <Button
            aria-label={state.refreshing ? '正在刷新平台状态' : '刷新状态'}
            disabled={state.refreshing}
            onClick={state.retry}
            variant="outline"
          >
            {state.refreshing ? (
              <Spinner aria-hidden data-icon="inline-start" />
            ) : (
              <ArrowClockwiseIcon aria-hidden data-icon="inline-start" />
            )}
            {state.refreshing ? '刷新中…' : '刷新'}
          </Button>
        }
        description="这里展示平台的接入与身份要求。下载是否成功以实际文件结果为准。"
        title="平台状态"
        titleId="provider-status-title"
      />

      <div className="mt-6 flex flex-col gap-6">
        <Item variant="muted">
          <ItemMedia variant="icon">
            <ShieldCheckIcon aria-hidden />
          </ItemMedia>
          <ItemContent>
            <ItemTitle>平台身份来自你的 Chrome</ItemTitle>
            <ItemDescription className="line-clamp-none">
              需要登录的平台通过 Framefetch 扩展读取你日常使用的 Chrome
              登录态；公开内容无需登录。身份材料不会扩大可下载的内容范围。
            </ItemDescription>
          </ItemContent>
        </Item>
        {state.loading && !state.data ? (
          <StatusMessage label="正在加载平台状态" />
        ) : null}
        {state.error && !state.data ? (
          <PageErrorNotice
            message="我们暂时无法读取最新的平台状态，请稍后再试。"
            onRetry={state.retry}
            retryLabel="重新加载"
            title="平台状态暂时不可用"
          />
        ) : null}
        {state.error && state.data ? (
          <FeedbackNotice
            action={
              <Button onClick={state.retry} variant="outline">
                <ArrowClockwiseIcon aria-hidden data-icon="inline-start" />
                重新加载
              </Button>
            }
            description={state.error}
            title="平台状态刷新失败"
            tone="error"
          />
        ) : null}
        {state.data ? (
          <>
            <div className="flex justify-end">
              <ToggleGroup
                type="single"
                aria-label="筛选平台状态"
                className="flex w-auto flex-wrap items-center gap-1"
                onKeyDownCapture={(event) => {
                  const nextFilter = nextStatusFilter(event);
                  if (nextFilter) {
                    setFilter(nextFilter);
                    setPage(1);
                  }
                }}
                onValueChange={(value) => {
                  if (!value) return;
                  setFilter(value as StatusFilter);
                  setPage(1);
                }}
                value={filter}
              >
                <ToggleGroupItem data-filter="all" value="all">
                  全部
                </ToggleGroupItem>
                <ToggleGroupItem data-filter="enabled" value="enabled">
                  已接入
                </ToggleGroupItem>
                <ToggleGroupItem data-filter="disabled" value="disabled">
                  未开放
                </ToggleGroupItem>
              </ToggleGroup>
            </div>
            {visibleProviders.length > 0 ? (
              <div className="flex flex-col gap-5">
                <Table className="table-borderless">
                  <TableCaption className="sr-only">平台能力状态</TableCaption>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="whitespace-normal lg:w-1/5">
                        平台
                      </TableHead>
                      <TableHead className="hidden whitespace-normal lg:table-cell">
                        接入与身份
                      </TableHead>
                      <TableHead className="hidden whitespace-normal lg:table-cell lg:w-1/4">
                        能力
                      </TableHead>
                      <TableHead className="hidden whitespace-normal lg:table-cell">
                        说明
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {visibleProviders.map((provider) => (
                      <ProviderStatusItem
                        key={provider.key}
                        provider={provider}
                      />
                    ))}
                  </TableBody>
                </Table>
                <footer className="flex justify-end">
                  <PagePagination
                    pageSize={pageSize}
                    onPageSizeChange={(size) => {
                      setPageSize(size);
                      setPage(1);
                    }}
                    ariaLabel="平台状态分页"
                    className="w-auto justify-end"
                    onPageChange={setPage}
                    page={currentPage}
                    pages={pages}
                  />
                </footer>
              </div>
            ) : (
              <PageEmptyNotice
                description="切换状态筛选，查看其他平台。"
                icon={<FunnelX aria-hidden />}
                title="没有匹配的平台"
              />
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

function matchesFilter(
  provider: API.ProviderListResponse['items'][number],
  filter: StatusFilter,
) {
  if (filter === 'enabled') return isDownloadEnabled(provider);
  if (filter === 'disabled') return !isDownloadEnabled(provider);
  return true;
}

function nextStatusFilter(
  event: KeyboardEvent<HTMLDivElement>,
): StatusFilter | null {
  const direction =
    event.key === 'ArrowRight' || event.key === 'ArrowDown'
      ? 1
      : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
        ? -1
        : 0;
  const target = event.target;
  if (
    direction === 0 ||
    !(target instanceof HTMLButtonElement) ||
    target.getAttribute('role') !== 'radio'
  ) {
    return null;
  }

  const currentIndex = STATUS_FILTERS.indexOf(
    target.dataset.filter as StatusFilter,
  );
  if (currentIndex < 0) {
    return null;
  }
  const nextIndex =
    (currentIndex + direction + STATUS_FILTERS.length) % STATUS_FILTERS.length;
  return STATUS_FILTERS[nextIndex];
}

function StatusMessage({ label }: { label: string }) {
  return (
    <Item aria-label={label} role="status">
      <ItemMedia variant="icon">
        <Spinner aria-hidden />
      </ItemMedia>
      <ItemContent>
        <ItemDescription>{label}</ItemDescription>
      </ItemContent>
    </Item>
  );
}
