import {
  ArrowClockwise,
  FunnelX,
  PlugsConnected,
  Plus,
} from '@phosphor-icons/react';
import { useMemo, useState } from 'react';
import type { BulkDeleteOptions } from '@/components/layout/bulk-delete-selection';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import {
  DEFAULT_PAGE_SIZE,
  PagePagination,
} from '@/components/layout/page-pagination';
import { Button } from '@/components/ui/button';
import { Item, ItemContent, ItemDescription } from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';

import type { CatalogResultState } from './model';
import {
  type CatalogVisibility,
  ProviderCatalogFilters,
} from './provider-catalog-filters';
import { ProviderCatalogList } from './provider-catalog-list';

type ProviderCatalogScreenProps = {
  bulk?: BulkDeleteOptions;
  result: CatalogResultState;
  onCreate: () => void;
  onDelete: (item: API.ProviderCatalogEntryResponse) => void;
  onEdit: (item: API.ProviderCatalogEntryResponse) => void;
  onRetry: () => void;
};

export function ProviderCatalogScreen({
  bulk,
  result,
  onCreate,
  onDelete,
  onEdit,
  onRetry,
}: ProviderCatalogScreenProps) {
  const [query, setQuery] = useState('');
  const [visibility, setVisibility] = useState<CatalogVisibility>('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const filtered = useMemo(
    () => filterCatalog(result.items, query, visibility),
    [query, result.items, visibility],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages);
  const visibleItems = filtered.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );

  return (
    <div aria-busy={result.loading} className="flex flex-col gap-6">
      <div>
        <PageNavigation fallbackHref="/providers" />
        <PageHeader
          action={
            <Button onClick={onCreate}>
              <Plus aria-hidden data-icon="inline-start" />
              新增平台
            </Button>
          }
          description="维护平台状态页的名称、排序与可见性。下载域名和执行能力由系统 Profile 控制。"
          title="平台目录"
        />
      </div>

      <Item variant="muted">
        <ItemContent>
          <ItemDescription className="line-clamp-none">
            “仅目录”条目不会获得真实下载能力。
          </ItemDescription>
        </ItemContent>
      </Item>

      {result.error && result.items.length === 0 ? (
        <PageErrorNotice
          message={result.error}
          onRetry={onRetry}
          retryLabel="重新加载"
          title="暂时无法读取平台目录"
        />
      ) : null}
      {result.error && result.items.length > 0 ? (
        <FeedbackNotice
          action={
            <Button onClick={onRetry} size="default" variant="outline">
              <ArrowClockwise aria-hidden data-icon="inline-start" />
              重新加载
            </Button>
          }
          description={result.error}
          title="平台目录刷新失败"
          tone="error"
        />
      ) : null}
      {result.loading && result.items.length === 0 ? (
        <CatalogSkeleton />
      ) : result.items.length === 0 ? (
        result.error ? null : (
          <PageEmptyNotice
            action={
              <Button onClick={onCreate} type="button">
                <Plus aria-hidden data-icon="inline-start" />
                新增第一个平台
              </Button>
            }
            description="新增条目后，可在平台状态页公开展示。"
            icon={<PlugsConnected aria-hidden />}
            title="平台目录为空"
          />
        )
      ) : (
        <div className="flex flex-col gap-6">
          <ProviderCatalogFilters
            onQueryChange={(value) => {
              setQuery(value);
              setPage(1);
            }}
            onVisibilityChange={(value) => {
              setVisibility(value);
              setPage(1);
            }}
            query={query}
            visibility={visibility}
          />
          {visibleItems.length > 0 ? (
            <ProviderCatalogList
              bulk={
                bulk
                  ? {
                      ...bulk,
                      scope: JSON.stringify([
                        bulk.scope,
                        query,
                        visibility,
                        currentPage,
                        pageSize,
                      ]),
                    }
                  : undefined
              }
              items={visibleItems}
              onDelete={onDelete}
              onEdit={onEdit}
            />
          ) : (
            <PageEmptyNotice
              description="调整搜索词或公开状态后重试。"
              icon={<FunnelX aria-hidden />}
              title="没有匹配的平台"
            />
          )}
          <PagePagination
            pageSize={pageSize}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
            ariaLabel="平台目录分页"
            onPageChange={setPage}
            page={currentPage}
            pages={pages}
          />
        </div>
      )}
    </div>
  );
}

function filterCatalog(
  items: API.ProviderCatalogEntryResponse[],
  query: string,
  visibility: CatalogVisibility,
) {
  const normalized = query.trim().toLocaleLowerCase();
  return items.filter((item) => {
    const matchesQuery =
      !normalized ||
      item.display_name.toLocaleLowerCase().includes(normalized) ||
      item.key.toLocaleLowerCase().includes(normalized);
    const matchesVisibility =
      visibility === 'all' ||
      (visibility === 'visible' ? item.is_visible : !item.is_visible);
    return matchesQuery && matchesVisibility;
  });
}

function CatalogSkeleton() {
  return (
    <div
      aria-label="正在加载平台目录"
      className="flex flex-col gap-2"
      role="status"
    >
      {['first', 'second', 'third', 'fourth'].map((row) => (
        <div key={row}>
          <Skeleton className="h-12 w-full" />
        </div>
      ))}
    </div>
  );
}
