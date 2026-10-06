import {
  ArrowClockwise,
  DotsThree,
  DownloadSimple,
  Eye,
  Trash,
} from '@phosphor-icons/react';
import Link from 'next/link';
import { type ReactNode, useRef, useState } from 'react';
import { DownloadDeleteDialog } from '@/components/downloads/download-delete-dialog';
import {
  DownloadStatusCode,
  downloadRecovery,
  downloadStatusLabels,
  isActiveDownloadStatus,
  statusVariant,
} from '@/components/downloads/download-state-model';
import type { DownloadAction } from '@/components/downloads/use-download-actions';
import { DataTable } from '@/components/layout/data-table';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import MediaCover from '@/components/media/media-cover';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';

export default function DownloadHistoryList({
  data,
  loading,
  onDownload,
  onDelete,
  onRetry,
  pendingActions,
  selection,
  toolbar,
}: {
  toolbar?: ReactNode;
  data: API.DownloadHistoryResponse | null;
  loading: boolean;
  onDownload: (item: API.DownloadHistoryItemResponse) => void;
  onDelete: (item: API.DownloadHistoryItemResponse) => Promise<void>;
  onRetry: (item: API.DownloadHistoryItemResponse) => void;
  selection?: {
    ids: string[];
    busy: boolean;
    toggle: (id: string, checked: boolean) => void;
  };
  pendingActions: Array<{ id: string; type: DownloadAction }>;
}) {
  return (
    <div className="mt-4">
      {loading && !data ? <LoadingRows /> : null}
      {data?.items.length ? (
        <DataTable<API.DownloadHistoryItemResponse>
          toolbar={toolbar}
          caption="下载记录"
          data={data.items}
          getRowId={(item) => item.id}
          getRowLabel={(item) => item.title}
          selection={
            selection
              ? {
                  ...selection,
                  eligible: (id) =>
                    !pendingActions.some((action) => action.id === id),
                }
              : undefined
          }
          columns={[
            {
              id: 'content',
              header: '视频',
              className: 'whitespace-normal',
              hideable: false,
              cell: (item) => <HistoryContent item={item} />,
            },
            {
              id: 'platform',
              header: '平台',
              className: 'hidden lg:table-cell',
              cell: (item) => displaySourceLabel(item),
            },
            {
              id: 'quality',
              header: '画质',
              className: 'hidden lg:table-cell',
              cell: (item) => item.format_name,
            },
            {
              id: 'status',
              header: '状态',
              // Narrow screens show the status inside the content cell so
              // the row actions stay reachable without horizontal scrolling.
              className: 'hidden lg:table-cell',
              cell: (item) => (
                <Badge variant={statusVariant(item.status)}>
                  {downloadStatusLabels[item.status]}
                  {isActiveDownloadStatus(item.status)
                    ? ` · ${item.progress}%`
                    : ''}
                </Badge>
              ),
            },
            {
              id: 'time',
              header: '时间',
              className: 'hidden lg:table-cell',
              cell: (item) => (
                <time dateTime={item.created_at}>
                  {formatDate(item.created_at)}
                </time>
              ),
            },
            {
              id: 'actions',
              header: '操作',
              className: 'text-right',
              hideable: false,
              cell: (item) => (
                <HistoryActions
                  item={item}
                  onDownload={onDownload}
                  onDelete={onDelete}
                  onRetry={onRetry}
                  selection={selection}
                  pendingAction={
                    pendingActions.find((action) => action.id === item.id) ??
                    null
                  }
                />
              ),
            },
          ]}
        />
      ) : null}
      {data && !data.items.length ? (
        <PageEmptyNotice
          compact
          description="调整筛选条件，或新建一个下载任务。"
          icon={<DownloadSimple aria-hidden />}
          title="没有匹配的下载记录"
        />
      ) : null}
    </div>
  );
}

function HistoryContent({ item }: { item: API.DownloadHistoryItemResponse }) {
  const detailHref = `/downloads/detail?jobId=${encodeURIComponent(item.id)}`;
  const sourceLabel = displaySourceLabel(item);
  return (
    <Item asChild className="flex-nowrap">
      <Link aria-label={item.title} href={detailHref}>
        <ItemMedia className="hidden w-24 sm:block">
          <MediaCover
            alt={`${item.title} 媒体封面`}
            className="w-full"
            compact
            fallback={{
              detail: item.format_name,
              eyebrow: sourceLabel,
              title: item.title,
            }}
            src={item.thumbnail_url}
          />
        </ItemMedia>
        <ItemContent className="min-w-0">
          <ItemTitle className="line-clamp-2 [overflow-wrap:anywhere]">
            {item.title}
          </ItemTitle>
          <ItemDescription className="hidden line-clamp-none lg:block">
            来源：{sourceLabel}
            {item.status === DownloadStatusCode.Succeeded
              ? ` · ${fileAvailabilityLabel(item)}`
              : ''}
          </ItemDescription>
          <ItemDescription className="line-clamp-none lg:hidden">
            {sourceLabel} · {item.format_name} ·{' '}
            <time dateTime={item.created_at}>
              {formatDate(item.created_at)}
            </time>
            {item.status === DownloadStatusCode.Succeeded
              ? ` · ${fileAvailabilityLabel(item)}`
              : ''}
          </ItemDescription>
          <Badge className="lg:hidden" variant={statusVariant(item.status)}>
            {downloadStatusLabels[item.status]}
            {isActiveDownloadStatus(item.status) ? ` · ${item.progress}%` : ''}
          </Badge>
        </ItemContent>
      </Link>
    </Item>
  );
}

function displaySourceLabel(item: API.DownloadHistoryItemResponse) {
  return item.source_kind === 'remote_provider' &&
    item.source_label === 'WechatChannelsPublic'
    ? '微信视频号'
    : item.source_label;
}

function HistoryActions({
  item,
  onDownload,
  onDelete,
  onRetry,
  pendingAction,
  selection,
}: {
  item: API.DownloadHistoryItemResponse;
  onDownload: (item: API.DownloadHistoryItemResponse) => void;
  onDelete: (item: API.DownloadHistoryItemResponse) => Promise<void>;
  onRetry: (item: API.DownloadHistoryItemResponse) => void;
  selection?: {
    ids: string[];
    busy: boolean;
    toggle: (id: string, checked: boolean) => void;
  };
  pendingAction: { id: string; type: DownloadAction } | null;
}) {
  const detailHref = `/downloads/detail?jobId=${encodeURIComponent(item.id)}`;
  const canDownload =
    item.status === DownloadStatusCode.Succeeded && item.file_available;
  const recovery = downloadRecovery(item);
  const busy = Boolean(selection?.busy || pendingAction);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            ref={menuTrigger}
            aria-label={`${item.title} 的操作`}
            disabled={busy}
            size="icon"
            variant="ghost"
          >
            {pendingAction ? (
              <Spinner aria-hidden />
            ) : (
              <DotsThree aria-hidden />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuGroup>
            <DropdownMenuItem asChild>
              <Link href={detailHref}>
                <Eye aria-hidden />
                查看任务
              </Link>
            </DropdownMenuItem>
            {canDownload ? (
              <DropdownMenuItem
                disabled={busy}
                onSelect={() => onDownload(item)}
              >
                <DownloadSimple aria-hidden />
                获取文件
              </DropdownMenuItem>
            ) : recovery === 'reimport' ? (
              <DropdownMenuItem asChild>
                <Link href="/">
                  <ArrowClockwise aria-hidden />
                  返回首页重新导入
                </Link>
              </DropdownMenuItem>
            ) : recovery === 'reparse' ? (
              <DropdownMenuItem asChild>
                <Link href="/">
                  <ArrowClockwise aria-hidden />
                  重新解析
                </Link>
              </DropdownMenuItem>
            ) : recovery === 'retry' ? (
              <DropdownMenuItem disabled={busy} onSelect={() => onRetry(item)}>
                <ArrowClockwise aria-hidden />
                重新下载
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuItem
              disabled={busy}
              variant="destructive"
              onSelect={() => setDeleteOpen(true)}
            >
              <Trash aria-hidden />
              删除下载记录
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <DownloadDeleteDialog
        active={isActiveDownloadStatus(item.status)}
        busy={pendingAction?.type === 'delete'}
        disabled={busy}
        onDelete={() => onDelete(item)}
        showTrigger={false}
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          menuTrigger.current?.focus();
        }}
      />
    </>
  );
}

function LoadingRows() {
  return (
    <>
      <span className="sr-only" role="status">
        正在加载下载记录
      </span>
      <div aria-hidden className="flex flex-col gap-2">
        {['first', 'second', 'third'].map((key) => (
          <Item key={key}>
            <ItemMedia className="w-24">
              <Skeleton className="aspect-video w-full" />
            </ItemMedia>
            <ItemContent>
              <Skeleton className="aspect-[16/1] w-2/5" />
              <Skeleton className="aspect-[16/1] w-3/5" />
            </ItemContent>
          </Item>
        ))}
      </div>
    </>
  );
}

function formatDate(value: string) {
  return historyDateFormatter.format(new Date(value));
}

function fileAvailabilityLabel(item: API.DownloadHistoryItemResponse) {
  return item.file_available ? '文件持久保存' : '文件已清理';
}

const historyDateFormatter = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium',
  timeStyle: 'short',
});
