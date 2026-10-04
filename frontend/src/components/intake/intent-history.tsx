'use client';

import { ArrowClockwise, Plus } from '@phosphor-icons/react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useRef, useState } from 'react';
import { listHistoryRecords } from '@/api/downloadIntents';
import { useAnalysisSkills } from '@/components/analysis/use-analysis-skills';
import {
  HistoryRecordFilters,
  useHistoryRecordFilters,
} from '@/components/intake/history-record-filters';
import {
  historyPollingInterval,
  historyRecordHref,
  historyRecordLabel,
  historyRecordStatus,
  historyRecordVariant,
  isAnalysisRecord,
} from '@/components/intake/history-record-presentation';
import { useIntakeDraft } from '@/components/intake/intake-draft-provider';
import { IntentHistoryDialog } from '@/components/intake/intent-history-dialog';
import {
  IntentStatusCode,
  intentHistoryActionLabel,
} from '@/components/intake/intent-status';
import { useBulkParseDownload } from '@/components/intake/use-bulk-parse-download';
import { BulkSelectionBar } from '@/components/layout/bulk-selection-bar';
import { DataTable } from '@/components/layout/data-table';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { PagePagination } from '@/components/layout/page-pagination';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { usePageSelection } from '@/hooks/use-page-selection';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

// History only locates existing owner-bound resources. Selecting a row never
// posts a new parse request or changes its deadline.
export function IntentHistory({
  onViewResult,
}: {
  onViewResult: (item: API.IntentHistoryItemResponse) => void;
}) {
  type ParseHistoryItem = API.ParseHistoryRecordResponse;
  const filters = useHistoryRecordFilters();
  const { setMode } = useIntakeDraft();
  const [selected, setSelected] = useState<ParseHistoryItem | null>(null);
  const detailTrigger = useRef<HTMLButtonElement | null>(null);
  const history = useQuery({
    queryKey: privateQueryKey('intent-history', filters.filters),
    queryFn: ({ signal }) =>
      listHistoryRecords(filters.filters, {
        signal,
        paramsSerializer: { indexes: null },
      }),
    staleTime: 0,
    refetchInterval: (query) =>
      query.state.error
        ? false
        : historyPollingInterval(query.state.data?.items ?? []),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
  const bulk = useBulkParseDownload();
  const eligible = (history.data?.items ?? []).filter(
    (item): item is API.ParseHistoryRecordResponse =>
      item.record_type === 'parse' &&
      item.status === IntentStatusCode.Ready &&
      !!item.inspection_id,
  );
  const selection = usePageSelection(
    JSON.stringify(filters.filters),
    eligible.map((item) => item.id),
  );
  const analysisSkills = useAnalysisSkills();
  const screenplaySkills = useAnalysisSkills('screenplay');
  const skills = [...analysisSkills.skills, ...screenplaySkills.skills];
  const skillNames = new Map(
    skills.map((skill) => [skill.id, skill.display_name]),
  );
  return (
    <div className="inner-page">
      <PageNavigation fallbackHref="/" />
      <PageHeader
        action={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button>
                <Plus data-icon="inline-start" />
                新建解析
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuGroup>
                {(
                  [
                    ['link', '粘贴链接'],
                    ['video', '上传视频'],
                    ['screenplay', '上传剧本'],
                  ] as const
                ).map(([mode, label]) => (
                  <DropdownMenuItem key={mode} asChild>
                    <Link href="/" onClick={() => setMode(mode)}>
                      {label}
                    </Link>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        }
        description="查看链接解析、视频 AI 分析、剧本基础解析与 AI 分析的处理记录。"
        title="我的处理记录"
      />
      <HistoryRecordFilters
        state={filters}
        skills={
          filters.category === 'video'
            ? analysisSkills.skills
            : filters.category === 'screenplay'
              ? screenplaySkills.skills
              : skills
        }
      />
      <section aria-label="已提交的解析" className="mt-6">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-base font-medium">解析任务</h2>
          <Button
            variant="outline"
            disabled={history.isFetching}
            onClick={() => {
              if (filters.page > 1) filters.first();
              else void history.refetch();
            }}
          >
            <ArrowClockwise data-icon="inline-start" />
            {history.isFetching ? '更新中…' : '刷新'}
          </Button>
        </div>
        {history.isPending ? (
          <>
            <span className="sr-only" role="status">
              正在读取解析记录…
            </span>
            <div aria-hidden className="mt-4 flex flex-col gap-2">
              {['first', 'second', 'third'].map((key) => (
                <div
                  className="flex items-center justify-between gap-4 py-5"
                  key={key}
                >
                  <div className="flex min-w-0 flex-1 flex-col gap-2">
                    <Skeleton className="h-4 w-1/2" />
                    <Skeleton className="h-3 w-1/3" />
                  </div>
                  <Skeleton className="h-6 w-24" />
                </div>
              ))}
            </div>
          </>
        ) : null}
        {history.error && !history.data ? (
          <PageErrorNotice
            compact
            title="暂时无法读取解析记录"
            message={displayError(history.error)}
            onRetry={() => void history.refetch()}
          />
        ) : null}
        {history.error && history.data ? (
          <FeedbackNotice
            className="mt-4"
            title="解析记录刷新失败"
            description={displayError(history.error)}
            tone="error"
          />
        ) : null}
        {history.data?.items.length === 0 ? (
          <PageEmptyNotice
            compact
            title={filters.hasFilters ? '没有匹配的解析记录' : '暂无解析记录'}
            description={
              filters.hasFilters
                ? '调整筛选条件，或清除筛选查看全部记录。'
                : '提交链接、上传剧本或运行 AI 分析后，可在这里继续查看。'
            }
          />
        ) : null}
        {bulk.busy ? (
          <p role="status">
            正在创建下载任务：{bulk.progress.completed} / {bulk.progress.total}
          </p>
        ) : null}
        {bulk.message ? (
          <FeedbackNotice
            presentation="toast"
            className="my-4"
            title="批量下载结果"
            description={bulk.message}
          />
        ) : null}
        {history.data?.items.length ? (
          <div className="mt-4">
            <DataTable
              data={history.data.items}
              caption="解析任务列表"
              getRowId={(item) => `${item.record_type}:${item.id}`}
              getRowLabel={(item) => item.title || '媒体解析'}
              selection={{
                ids: selection.selected.map((id) => `parse:${id}`),
                busy: bulk.busy || history.isFetching,
                eligible: (id) =>
                  eligible.some((item) => `parse:${item.id}` === id),
                toggle: (id, checked) =>
                  selection.toggle(id.slice('parse:'.length), checked),
              }}
              toolbar={
                <BulkSelectionBar
                  count={selection.selected.length}
                  busy={bulk.busy || history.isFetching}
                  onClear={() => selection.toggleAll(false)}
                >
                  <Button
                    variant="outline"
                    disabled={
                      bulk.busy || history.isFetching || !selection.some
                    }
                    onClick={async () => {
                      const done = await bulk.execute(
                        eligible.filter((item) =>
                          selection.selected.includes(item.id),
                        ),
                      );
                      selection.remove(done);
                    }}
                  >
                    批量下载（{selection.selected.length}）
                  </Button>
                  <span className="text-sm text-muted-foreground">
                    按默认画质创建下载任务
                  </span>
                </BulkSelectionBar>
              }
              columns={[
                {
                  id: 'content',
                  header: '内容',
                  cell: (item) => (
                    <div className="min-w-0 whitespace-normal">
                      <p className="line-clamp-2 break-words font-medium">
                        {item.title || '媒体解析'}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {historyRecordLabel(item)}
                        {isAnalysisRecord(item)
                          ? ` · ${skillNames.get(item.skill_id) ?? item.skill_id} · ${item.output_language}`
                          : ''}
                      </p>
                      {isAnalysisRecord(item) &&
                      item.source_availability === 'unavailable' ? (
                        <p className="mt-1 text-xs text-muted-foreground">
                          源文件不可用 · 已有结果仍可查看
                        </p>
                      ) : null}
                      <Badge
                        className="mt-1.5 sm:hidden"
                        variant={historyRecordVariant(item)}
                      >
                        {historyRecordStatus(item)}
                      </Badge>
                    </div>
                  ),
                },
                {
                  id: 'created',
                  header: '提交时间',
                  className: 'hidden w-44 sm:table-cell',
                  cell: (item) => (
                    <time
                      className="text-muted-foreground"
                      dateTime={item.created_at}
                    >
                      {new Date(item.created_at).toLocaleString('zh-CN', {
                        hour12: false,
                      })}
                    </time>
                  ),
                },
                {
                  id: 'status',
                  header: '状态',
                  // Shown inside the content cell on narrow screens.
                  className: 'hidden w-32 sm:table-cell',
                  cell: (item) => (
                    <Badge variant={historyRecordVariant(item)}>
                      {historyRecordStatus(item)}
                    </Badge>
                  ),
                },
                {
                  id: 'actions',
                  header: '操作',
                  className: 'w-28 text-right',
                  hideable: false,
                  cell: (item) =>
                    item.record_type !== 'parse' ? (
                      <Button asChild variant="ghost" size="sm">
                        <Link href={historyRecordHref(item)}>
                          {item.record_type === 'document_parse'
                            ? '查看文档'
                            : '查看分析'}
                        </Link>
                      </Button>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(event) => {
                          if (
                            item.status === IntentStatusCode.Ready &&
                            item.inspection_id
                          ) {
                            onViewResult(item);
                            return;
                          }
                          detailTrigger.current = event.currentTarget;
                          setSelected(item);
                        }}
                      >
                        {intentHistoryActionLabel(item.status)}
                      </Button>
                    ),
                },
              ]}
            />
          </div>
        ) : null}
        {history.data ? (
          <PagePagination
            pageSize={filters.pageSize}
            onPageSizeChange={(size) =>
              filters.update({ pageSize: String(size) })
            }
            ariaLabel="解析记录分页"
            page={filters.page}
            hasNext={Boolean(history.data.next_cursor)}
            busy={history.isFetching}
            onPageChange={(page) => {
              if (page <= filters.page) filters.goToPage(page);
              else if (history.data?.next_cursor)
                filters.next(history.data.next_cursor);
            }}
          />
        ) : null}
      </section>
      <IntentHistoryDialog
        item={selected}
        onClose={() => setSelected(null)}
        triggerRef={detailTrigger}
      />
    </div>
  );
}
