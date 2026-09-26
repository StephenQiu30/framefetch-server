'use client';

import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { getAdminEngineCatalog } from '@/api/admin';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import {
  DEFAULT_PAGE_SIZE,
  PagePagination,
} from '@/components/layout/page-pagination';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Spinner } from '@/components/ui/spinner';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

export function EngineCatalogPanel() {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const result = useQuery({
    queryKey: privateQueryKey('engine-catalog'),
    queryFn: ({ signal }) => getAdminEngineCatalog({ signal }),
    enabled: false,
  });
  const data = result.data;
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (data?.candidates ?? []).filter((item) =>
      `${item.key} ${item.name}`.toLowerCase().includes(query),
    );
  }, [data, search]);
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages);
  const visible = filtered.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );

  return (
    <section
      aria-labelledby="engine-catalog-title"
      className="mt-10 flex flex-col gap-4"
    >
      <h2 className="text-base font-medium" id="engine-catalog-title">
        引擎候选能力
      </h2>
      <p className="text-sm text-muted-foreground">
        由当前匿名 Runner
        的实际引擎和插件生成。一个站点可能有多个提取器，候选数量不代表可下载的平台数量；实际可用性仍以平台状态和真实下载验证为准。
      </p>
      <Button
        disabled={result.isFetching}
        onClick={() => void result.refetch()}
        variant="secondary"
      >
        {result.isFetching ? (
          <Spinner aria-hidden data-icon="inline-start" />
        ) : null}
        {result.isFetching ? '读取中…' : data ? '刷新引擎候选' : '读取引擎候选'}
      </Button>
      {result.error ? (
        <FeedbackNotice
          title={
            data ? '引擎候选刷新失败，保留上次读取结果' : '引擎候选暂时不可用'
          }
          description={displayError(result.error)}
          tone="error"
        />
      ) : null}
      {data ? (
        <>
          <div className="flex flex-col gap-1 break-all text-sm">
            <p>
              已识别 {data.candidates.length} 个提取器候选 · yt-dlp{' '}
              {data.engine_version}
            </p>
            <p>
              {data.pin_matches
                ? '安装版本与固定依赖一致'
                : '安装版本与固定依赖不一致，请检查 Runner 镜像'}
            </p>
            <p className="text-muted-foreground">
              引擎提交：{data.engine_commit ?? '无法确认'}
            </p>
            <p className="text-muted-foreground">
              插件摘要：{data.bundled_plugins_sha256}
            </p>
            <p className="text-muted-foreground">
              清单标识：{data.manifest_id}
            </p>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="engine-candidate-search">搜索提取器候选</Label>
            <Input
              id="engine-candidate-search"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="输入提取器名称或标识"
            />
          </div>
          {visible.length ? (
            <ul aria-label="引擎候选清单" className="grid gap-4 sm:grid-cols-2">
              {visible.map((item) => (
                <li className="min-w-0 break-words text-sm" key={item.key}>
                  <p className="font-medium">{item.name}</p>
                  <p className="text-muted-foreground">
                    {item.key} ·{' '}
                    {item.upstream_working
                      ? '候选，尚不代表下载验证'
                      : '上游标记失效'}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <PageEmptyNotice
              title="没有匹配的提取器"
              description="调整搜索词后重试。"
            />
          )}
          <footer className="flex flex-wrap items-center justify-between gap-4 text-sm text-muted-foreground">
            <p>
              显示 {visible.length} 项，共 {filtered.length} 项
            </p>
            <PagePagination
              pageSize={pageSize}
              onPageSizeChange={(size) => {
                setPageSize(size);
                setPage(1);
              }}
              ariaLabel="引擎候选分页"
              className="w-auto justify-end"
              onPageChange={setPage}
              page={currentPage}
              pages={pages}
            />
          </footer>
        </>
      ) : null}
    </section>
  );
}
