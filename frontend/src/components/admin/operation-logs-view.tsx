'use client';
import { ArrowClockwiseIcon } from '@phosphor-icons/react';
import { useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { listOperationLogs } from '@/api/admin';
import { DataTable } from '@/components/layout/data-table';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import {
  DEFAULT_PAGE_SIZE,
  PagePagination,
} from '@/components/layout/page-pagination';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Form } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

const outcomeLabels = {
  started: '结果未确认',
  succeeded: '请求成功',
  failed: '请求失败',
} as const;
const taskStates: Record<string, string> = {
  queued: '排队中',
  running: '执行中',
  ready: '解析完成',
  handed_off: '下载任务已创建',
  succeeded: '执行完成',
  failed: '执行失败',
  cancelled: '已取消',
  expired: '已过期',
  deleted: '已删除',
  pending: '等待处理',
  preparing: '准备中',
  resolving: '解析中',
  verifying: '校验中',
  uploading: '上传中',
  retry_wait: '等待重试',
};
const resultLabel = (item: API.OperationLogResponse) =>
  item.source === 'task'
    ? (taskStates[item.task_state ?? ''] ?? item.task_state ?? '状态更新')
    : outcomeLabels[item.outcome];
const time = (value: string) =>
  new Date(value).toLocaleString('zh-CN', { hour12: false });
export function OperationLogsView() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [outcome, setOutcome] = useState<
    API.OperationLogResponse['outcome'] | 'all'
  >('all');
  const [scope, setScope] = useState('all');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const detailTrigger = useRef<HTMLButtonElement | null>(null);
  const [selected, setSelected] = useState<API.OperationLogResponse | null>(
    null,
  );
  const params = {
    page,
    page_size: pageSize,
    q: q || undefined,
    outcome: outcome === 'all' ? undefined : outcome,
    admin_only: scope === 'admin',
    source:
      scope === 'task'
        ? ('task' as const)
        : scope === 'request'
          ? ('request' as const)
          : undefined,
    created_from: from ? new Date(from).toISOString() : undefined,
    // datetime-local has minute precision; include the whole selected minute.
    created_to: to
      ? new Date(new Date(to).getTime() + 59_999).toISOString()
      : undefined,
  };
  const invalidDates = !!(from && to && from > to);
  const logs = useQuery({
    queryKey: privateQueryKey('operation-logs', params),
    queryFn: ({ signal }) => listOperationLogs(params, { signal }),
    enabled: !invalidDates,
  });
  return (
    <div className="inner-page flex flex-col gap-6">
      <div>
        <PageNavigation fallbackHref="/" />
        <PageHeader
          title="系统操作日志"
          description="查看全系统业务请求与管理员操作，追踪操作人、对象和执行结果。"
          action={
            <Button
              variant="outline"
              disabled={logs.isFetching}
              onClick={() => {
                if (page !== 1) setPage(1);
                else void logs.refetch();
              }}
            >
              <ArrowClockwiseIcon data-icon="inline-start" />
              {logs.isFetching ? '更新中…' : '刷新'}
            </Button>
          }
        />
      </div>
      <Form
        onSubmit={(event) => {
          event.preventDefault();
          setQ(search.trim());
          setPage(1);
        }}
      >
        <FieldGroup className="grid gap-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_repeat(4,minmax(0,1fr))]">
          <Field>
            <FieldLabel htmlFor="log-search">操作人或操作名称</FieldLabel>
            <div className="flex gap-2">
              <Input
                id="log-search"
                maxLength={128}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索日志"
              />
              <Button type="submit" variant="outline">
                搜索
              </Button>
            </div>
          </Field>
          <Field>
            <FieldLabel htmlFor="log-scope">操作范围</FieldLabel>
            <Select
              value={scope}
              onValueChange={(value) => {
                setScope(value);
                setPage(1);
              }}
            >
              <SelectTrigger id="log-scope">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="all">全部操作</SelectItem>
                  <SelectItem value="request">接口请求</SelectItem>
                  <SelectItem value="task">系统任务</SelectItem>
                  <SelectItem value="admin">管理员操作</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="log-outcome">执行结果</FieldLabel>
            <Select
              value={outcome}
              onValueChange={(value) => {
                setOutcome(
                  value as API.OperationLogResponse['outcome'] | 'all',
                );
                setPage(1);
              }}
            >
              <SelectTrigger id="log-outcome">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="all">全部结果</SelectItem>
                  {Object.entries(outcomeLabels).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {value === 'succeeded' ? '成功 / 状态更新' : label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="log-from">开始时间</FieldLabel>
            <Input
              id="log-from"
              type="datetime-local"
              value={from}
              onChange={(event) => {
                setFrom(event.target.value);
                setPage(1);
              }}
            />
          </Field>
          <Field data-invalid={invalidDates}>
            <FieldLabel htmlFor="log-to">结束时间</FieldLabel>
            <Input
              id="log-to"
              type="datetime-local"
              value={to}
              aria-invalid={invalidDates}
              onChange={(event) => {
                setTo(event.target.value);
                setPage(1);
              }}
            />
          </Field>
        </FieldGroup>
      </Form>
      <p className="text-sm text-muted-foreground">
        展示日志启用后的操作。请求结果与系统任务状态分别记录；“结果未确认”表示请求尚未结束或执行曾中断。
      </p>
      {invalidDates ? (
        <PageErrorNotice message="结束时间不能早于开始时间。" />
      ) : logs.isPending ? (
        <div role="status" aria-label="正在读取操作日志">
          <Skeleton className="h-48 w-full" />
        </div>
      ) : logs.isError ? (
        <PageErrorNotice
          message={displayError(logs.error)}
          onRetry={() => void logs.refetch()}
        />
      ) : (
        <>
          {logs.data.items.length ? (
            <DataTable<API.OperationLogResponse>
              data={logs.data.items}
              getRowId={(item) => item.id}
              getRowLabel={(item) => item.description}
              caption="系统操作日志"
              columns={[
                {
                  id: '时间',
                  header: '时间',
                  className: 'whitespace-normal',
                  cell: (item) => <> {time(item.created_at)} </>,
                },
                {
                  id: '操作人',
                  header: '操作人',
                  className: 'whitespace-normal',
                  cell: (item) => <> {item.actor_name ?? '未识别账户'} </>,
                },
                {
                  id: '操作',
                  header: '操作',
                  className: 'whitespace-normal',
                  cell: (item) => (
                    <>
                      <div>{item.description}</div>
                      <div className="text-xs text-muted-foreground">
                        {item.source === 'task'
                          ? '系统任务'
                          : item.route.includes('/admin/')
                            ? '管理员操作'
                            : '业务操作'}
                      </div>
                    </>
                  ),
                },
                {
                  id: '对象',
                  header: '对象',
                  className: 'whitespace-normal',
                  cell: (item) => (
                    <>
                      <span
                        title={
                          item.resource_id ?? item.resource_key ?? undefined
                        }
                      >
                        {item.resource_key ??
                          item.resource_id?.slice(0, 8) ??
                          '—'}
                      </span>
                    </>
                  ),
                },
                {
                  id: '结果',
                  header: '结果',
                  className: 'whitespace-normal',
                  cell: (item) => (
                    <>
                      <Badge
                        variant={
                          item.outcome === 'failed'
                            ? 'destructive'
                            : item.outcome === 'started'
                              ? 'outline'
                              : 'secondary'
                        }
                      >
                        {resultLabel(item)}
                      </Badge>
                    </>
                  ),
                },
                {
                  id: '详情',
                  header: '详情',
                  className: 'text-right whitespace-normal',
                  cell: (item) => (
                    <>
                      <Button
                        variant="ghost"
                        onClick={(event) => {
                          detailTrigger.current = event.currentTarget;
                          setSelected(item);
                        }}
                        aria-label={`查看${item.description}详情`}
                      >
                        查看详情
                      </Button>
                    </>
                  ),
                },
              ]}
            />
          ) : (
            <PageEmptyNotice
              title="暂无操作日志"
              description="尚未产生符合条件的操作。可以调整筛选条件或稍后刷新。"
            />
          )}
          <PagePagination
            ariaLabel="操作日志分页"
            page={page}
            pages={Math.ceil(logs.data.total / pageSize)}
            pageSize={pageSize}
            onPageChange={setPage}
            onPageSizeChange={(value) => {
              setPageSize(value);
              setPage(1);
            }}
            busy={logs.isFetching}
          />
        </>
      )}
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <DialogContent
          className="max-h-svh overflow-y-auto overscroll-contain"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            detailTrigger.current?.focus();
          }}
        >
          <DialogHeader>
            <DialogTitle>操作详情</DialogTitle>
            <DialogDescription>
              只读记录，用于定位请求和核对执行结果。
            </DialogDescription>
          </DialogHeader>
          {selected ? (
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-3 text-sm">
              {Object.entries({
                '日志 ID': selected.id,
                操作人: selected.actor_name ?? '未识别账户',
                '账户 ID': selected.actor_id ?? '—',
                操作: selected.description,
                操作标识: selected.operation,
                接口: `${selected.method} ${selected.route}`,
                对象标识: selected.resource_id ?? selected.resource_key ?? '—',
                发起时间: time(selected.created_at),
                结束时间: selected.finished_at
                  ? time(selected.finished_at)
                  : '结果未确认',
                结果: resultLabel(selected),
                'HTTP 状态': selected.status_code ?? '—',
                错误码: selected.error_code ?? '—',
              }).map(([label, value]) => (
                <div key={label} className="contents">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="min-w-0 break-all">{value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
