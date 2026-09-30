'use client';

import { ArrowClockwise, MagnifyingGlass, Plus } from '@phosphor-icons/react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { DownloadDeleteDialog } from '@/components/downloads/download-delete-dialog';
import DownloadHistoryList from '@/components/downloads/download-history-list';
import {
  DownloadStatusCode,
  downloadRecovery,
  downloadStatusLabels,
  isActiveDownloadStatus,
} from '@/components/downloads/download-state-model';
import { useDownloadActions } from '@/components/downloads/use-download-actions';
import { useDownloadHistory } from '@/components/downloads/use-download-history';
import { BulkSelectionBar } from '@/components/layout/bulk-selection-bar';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { markNavigationPush } from '@/components/layout/navigation-history';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import {
  DEFAULT_PAGE_SIZE,
  PagePagination,
} from '@/components/layout/page-pagination';
import { useWorkspaceState } from '@/components/layout/workspace-state-provider';
import { Button } from '@/components/ui/button';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from '@/components/ui/input-group';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Spinner } from '@/components/ui/spinner';
import { usePageSelection } from '@/hooks/use-page-selection';
import { useRequestScope } from '@/hooks/use-request-scope';
export default function DownloadHistoryView() {
  const router = useRouter();
  const { history, setHistory } = useWorkspaceState();
  const { page, searchInput, search, status } = history;
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const operations = useDownloadActions();
  const actionError = operations.error;
  const scope = useRequestScope('download-history');
  const state = useDownloadHistory({
    page,
    page_size: pageSize,
    search: search || undefined,
    status,
  });
  const [bulkAction, setBulkAction] = useState<
    'download' | 'retry' | 'delete' | null
  >(null);
  const bulkBusy = bulkAction !== null;
  const bulkLock = useRef(false);
  const actionsBusy =
    bulkBusy || state.refreshing || operations.pendingActions.length > 0;
  const [bulkProgress, setBulkProgress] = useState({ completed: 0, total: 0 });
  const [bulkMessage, setBulkMessage] = useState('');
  const items = state.data?.items ?? [];
  const selection = usePageSelection(
    JSON.stringify([page, pageSize, search, status]),
    items.map((item) => item.id),
  );
  const selectedItems = items.filter((item) =>
    selection.selected.includes(item.id),
  );
  const downloadable = selectedItems.filter(
    (item) =>
      item.status === DownloadStatusCode.Succeeded && item.file_available,
  );
  const retryable = selectedItems.filter(
    (item) => downloadRecovery(item) === 'retry',
  );
  async function runBulk(action: 'download' | 'retry' | 'delete') {
    if (actionsBusy || bulkLock.current) return;
    const targets =
      action === 'download'
        ? downloadable
        : action === 'retry'
          ? retryable
          : selectedItems;
    if (!targets.length) return;
    bulkLock.current = true;
    const request = scope.capture();
    setBulkAction(action);
    setBulkProgress({ completed: 0, total: targets.length });
    setBulkMessage('');
    const done: string[] = [];
    try {
      for (const item of targets) {
        if (!request.current()) break;
        const result = await operations.execute(item.id, action);
        if (result) done.push(item.id);
        if (request.current())
          setBulkProgress((value) => ({
            ...value,
            completed: value.completed + 1,
          }));
      }
      if (request.current()) {
        selection.remove(done);
        setBulkMessage(
          `${action === 'download' ? '已发起文件下载' : action === 'retry' ? '已提交重试' : '已删除'} ${done.length} 项，失败 ${targets.length - done.length} 项。${action === 'download' ? '浏览器可能要求允许下载多个文件。' : ''}`,
        );
      }
    } finally {
      bulkLock.current = false;
      if (request.current()) setBulkAction(null);
    }
  }
  const responsePage = state.data?.page;
  const lastPage = state.data
    ? Math.max(1, Math.ceil(state.data.total / state.data.page_size))
    : page;
  useEffect(() => {
    // Placeholder data belongs to the previous filter/page and cannot clamp a
    // new request. Correct only an authoritative response for this page.
    if (responsePage === page && page > lastPage) {
      setHistory((current) => ({ ...current, page: lastPage }));
    }
  }, [lastPage, page, responsePage, setHistory]);

  function applySearch() {
    setHistory((current) => ({
      ...current,
      page: 1,
      search: current.searchInput.trim(),
    }));
  }

  async function download(item: API.DownloadHistoryItemResponse) {
    await operations.execute(item.id, 'download');
  }
  async function retry(item: API.DownloadHistoryItemResponse) {
    const request = scope.capture();
    const result = await operations.execute(item.id, 'retry');
    if (!request.current() || result?.action !== 'retry') return;
    const target = `/downloads/detail?jobId=${encodeURIComponent(result.job.id)}`;
    markNavigationPush(target);
    router.push(target);
  }
  async function remove(item: API.DownloadHistoryItemResponse) {
    await operations.execute(item.id, 'delete');
  }

  return (
    <div className="inner-page">
      <PageNavigation fallbackHref="/" />
      <PageHeader
        action={
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <Link href="/history/activity">我的处理记录</Link>
            </Button>
            <Button asChild>
              <Link href="/">
                <Plus data-icon="inline-start" />
                解析新链接
              </Link>
            </Button>
          </div>
        }
        description="继续查看、获取或分析已创建的任务。"
        title="下载记录"
      />

      <FieldGroup className="mt-6 grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] sm:items-end">
        <Field>
          <FieldLabel className="sr-only" htmlFor="history-search">
            搜索下载记录
          </FieldLabel>
          <InputGroup>
            <InputGroupInput
              className="h-full"
              id="history-search"
              onChange={(event) => {
                const searchInput = event.target.value;
                setHistory((current) => ({ ...current, searchInput }));
              }}
              onKeyDown={(event) => {
                if (event.key !== 'Enter') return;
                event.preventDefault();
                applySearch();
              }}
              placeholder="按视频标题搜索"
              value={searchInput}
            />
            <InputGroupAddon align="inline-end">
              <InputGroupButton
                aria-label="搜索下载记录"
                onClick={applySearch}
                size="icon-sm"
                type="button"
              >
                <MagnifyingGlass aria-hidden data-icon="inline-start" />
              </InputGroupButton>
            </InputGroupAddon>
          </InputGroup>
        </Field>
        <Field>
          <FieldLabel className="sr-only" htmlFor="history-status">
            按状态筛选
          </FieldLabel>
          <Select
            onValueChange={(value) => {
              setHistory((current) => ({
                ...current,
                page: 1,
                status:
                  value === 'all' ? undefined : (value as API.DownloadStatus),
              }));
            }}
            value={status ?? 'all'}
          >
            <SelectTrigger className="w-full" id="history-status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">全部状态</SelectItem>
                {Object.entries(downloadStatusLabels).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <Button
          className="w-full sm:w-auto"
          aria-busy={state.refreshing}
          disabled={state.refreshing}
          onClick={state.retry}
          type="button"
          variant="outline"
        >
          <ArrowClockwise data-icon="inline-start" />
          {state.refreshing ? '更新中…' : '刷新'}
        </Button>
      </FieldGroup>

      {state.error && !state.data ? (
        <PageErrorNotice
          className="mt-6"
          message={state.error}
          onRetry={state.retry}
          retryLabel="重新加载"
          title="暂时无法读取下载记录"
        />
      ) : null}
      {state.error && state.data ? (
        <FeedbackNotice
          action={
            <Button onClick={state.retry} size="sm" variant="outline">
              重新加载
            </Button>
          }
          className="mt-6"
          description={state.error}
          title="下载记录刷新失败"
          tone="error"
        />
      ) : null}
      {actionError ? (
        <FeedbackNotice
          presentation="toast"
          className="mt-6"
          description={actionError}
          title="操作未完成"
          tone="error"
        />
      ) : null}

      {bulkBusy ? (
        <p role="status">
          正在处理所选记录：{bulkProgress.completed} / {bulkProgress.total}
        </p>
      ) : null}
      {bulkMessage ? (
        <FeedbackNotice
          presentation="toast"
          className="my-4"
          title="批量操作结果"
          description={bulkMessage}
        />
      ) : null}
      <DownloadHistoryList
        toolbar={
          items.length > 0 ? (
            <BulkSelectionBar
              count={selection.selected.length}
              busy={actionsBusy}
              onClear={() => selection.toggleAll(false)}
            >
              {downloadable.length > 0 || bulkAction === 'download' ? (
                <Button
                  variant="outline"
                  disabled={actionsBusy || !downloadable.length}
                  onClick={() => void runBulk('download')}
                >
                  {bulkAction === 'download' ? (
                    <Spinner aria-hidden data-icon="inline-start" />
                  ) : null}
                  批量下载（{downloadable.length}）
                </Button>
              ) : null}
              {retryable.length > 0 || bulkAction === 'retry' ? (
                <Button
                  variant="outline"
                  disabled={actionsBusy || !retryable.length}
                  onClick={() => void runBulk('retry')}
                >
                  {bulkAction === 'retry' ? (
                    <Spinner aria-hidden data-icon="inline-start" />
                  ) : null}
                  批量重试（{retryable.length}）
                </Button>
              ) : null}
              <DownloadDeleteDialog
                active={selectedItems.some((item) =>
                  isActiveDownloadStatus(item.status),
                )}
                busy={bulkAction === 'delete'}
                disabled={actionsBusy || !selectedItems.length}
                count={selectedItems.length}
                onDelete={() => runBulk('delete')}
              />
            </BulkSelectionBar>
          ) : null
        }
        selection={{
          ids: selection.selected,
          toggle: selection.toggle,
          busy: actionsBusy,
        }}
        data={state.data}
        loading={state.loading}
        onDownload={(item) => void download(item)}
        onDelete={remove}
        onRetry={(item) => void retry(item)}
        pendingActions={operations.pendingActions}
      />

      {state.data ? (
        <PagePagination
          pageSize={pageSize}
          busy={state.refreshing}
          onPageSizeChange={(size) => {
            setPageSize(size);
            setHistory((current) => ({ ...current, page: 1 }));
          }}
          ariaLabel="下载记录分页"
          className="mt-4 justify-end"
          onPageChange={(page) =>
            setHistory((current) => ({ ...current, page }))
          }
          page={page}
          pages={Math.ceil(state.data.total / state.data.page_size)}
        />
      ) : null}
    </div>
  );
}
