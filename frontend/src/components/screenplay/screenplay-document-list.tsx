import { FileText } from '@phosphor-icons/react';
import Link from 'next/link';
import {
  type BulkDeleteOptions,
  BulkDeleteSelection,
} from '@/components/layout/bulk-delete-selection';
import { type DataColumn, DataTable } from '@/components/layout/data-table';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { ScreenplayDocumentDeleteDialog } from '@/components/screenplay/screenplay-document-delete-dialog';
import {
  documentFormatLabels,
  documentStatusLabels,
  documentStatusVariant,
  formatDocumentDate,
  languageLabel,
} from '@/components/screenplay/screenplay-document-format';
import { ScreenplayUploadDialog } from '@/components/screenplay/screenplay-upload-dialog';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';

export function ScreenplayDocumentList({
  bulk,
  data,
  loading,
  onDelete,
  pendingDeleteId,
}: {
  bulk?: BulkDeleteOptions;
  data: API.DocumentPageResponse | null;
  loading: boolean;
  onDelete: (document: API.DocumentResponse) => Promise<void>;
  pendingDeleteId: string | null;
}) {
  return (
    <BulkDeleteSelection
      ids={data?.items.map((item) => item.id) ?? []}
      options={bulk}
    >
      <div aria-busy={loading}>
        {loading && !data ? <LoadingRows /> : null}
        {data?.items.length ? (
          <DataTable<API.DocumentResponse>
            data={data.items}
            getRowId={(document) => document.id}
            getRowLabel={(document) => document.title}
            caption="剧本文档列表"
            columns={DocumentRowColumns(onDelete, pendingDeleteId)}
          />
        ) : null}
        {data && !data.items.length ? (
          <PageEmptyNotice
            action={<ScreenplayUploadDialog label="上传第一份剧本" />}
            description="上传一份剧本文档后，可在这里核对解析状态与正文。"
            icon={<FileText aria-hidden />}
            title="还没有剧本文档"
          />
        ) : null}
      </div>
    </BulkDeleteSelection>
  );
}

function DocumentRowColumns(
  onDelete: (document: API.DocumentResponse) => Promise<void>,
  pendingDeleteId: string | null,
): DataColumn<API.DocumentResponse>[] {
  return [
    {
      id: '文档',
      header: '文档',
      className: 'text-left whitespace-normal',
      cell: (document) => {
        const detailHref = `/documents/detail?documentId=${encodeURIComponent(document.id)}`;
        return (
          <div className="flex min-w-0 flex-col gap-1">
            <Link
              className="focus-ring line-clamp-2 rounded-sm text-sm font-medium leading-snug hover:text-muted-foreground"
              href={detailHref}
            >
              {document.title}
            </Link>
            <span className="line-clamp-2 break-all text-xs text-muted-foreground">
              {document.original_filename}
            </span>
            <div className="flex flex-col gap-1 text-xs text-muted-foreground sm:hidden">
              <span>
                {documentFormatLabels[document.source_format]} ·{' '}
                {languageLabel(document.detected_language)}
              </span>
              <span>
                {document.scene_count ?? '-'} 个场景 ·{' '}
                {document.character_count?.toLocaleString('zh-CN') ?? '-'}{' '}
                个字符
              </span>
              <time dateTime={document.updated_at}>
                更新于 {formatDocumentDate(document.updated_at)}
              </time>
            </div>
            <Badge
              className="mt-0.5 sm:hidden"
              variant={documentStatusVariant(document.status)}
            >
              {documentStatusLabels[document.status]}
            </Badge>
          </div>
        );
      },
    },
    {
      id: '格式与更新时间',
      header: '格式与更新时间',
      className: 'hidden whitespace-normal sm:table-cell',
      cell: (document) => {
        return (
          <div className="flex flex-col gap-1">
            <span>{documentFormatLabels[document.source_format]}</span>
            <time dateTime={document.updated_at}>
              {formatDocumentDate(document.updated_at)}
            </time>
          </div>
        );
      },
    },
    {
      id: '内容统计',
      header: '内容统计',
      className: 'hidden whitespace-normal sm:table-cell',
      cell: (document) => {
        return (
          <div className="flex flex-col gap-1">
            <span>
              {document.scene_count ?? '-'} 个场景 ·{' '}
              {document.character_count?.toLocaleString('zh-CN') ?? '-'} 个字符
            </span>
            <span className="text-xs text-muted-foreground">
              {languageLabel(document.detected_language)}
            </span>
          </div>
        );
      },
    },
    {
      id: '状态',
      header: '状态',
      // Shown inside the document cell on narrow screens.
      className: 'hidden whitespace-normal sm:table-cell',
      cell: (document) => {
        return (
          <Badge variant={documentStatusVariant(document.status)}>
            {documentStatusLabels[document.status]}
          </Badge>
        );
      },
    },
    {
      id: '操作',
      header: '操作',
      className: 'text-right',
      cell: (document) => {
        const pending = pendingDeleteId === document.id;
        return (
          <ScreenplayDocumentDeleteDialog
            busy={pending}
            compact
            onDelete={() => onDelete(document)}
          />
        );
      },
    },
  ];
}

function LoadingRows() {
  return (
    <>
      <span className="sr-only" role="status">
        正在加载剧本文档
      </span>
      <div aria-hidden className="flex flex-col gap-2">
        {['first', 'second', 'third'].map((key) => (
          <div
            className="grid grid-cols-[minmax(0,1fr)_auto] gap-5 py-6"
            key={key}
          >
            <div className="flex flex-col gap-2">
              <Skeleton className="h-5 w-2/5" />
              <Skeleton className="h-4 w-3/5" />
              <Skeleton className="h-4 w-1/2" />
            </div>
            <Skeleton className="h-6 w-20" />
          </div>
        ))}
      </div>
    </>
  );
}
