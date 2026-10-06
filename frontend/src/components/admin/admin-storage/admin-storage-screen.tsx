import { ArrowClockwise, FolderOpen, Trash } from '@phosphor-icons/react';
import type { BulkDeleteOptions } from '@/components/layout/bulk-delete-selection';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { PagePagination } from '@/components/layout/page-pagination';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';

import { StorageCleanupDialog } from './storage-cleanup-dialog';
import { StorageFileDeleteDialog } from './storage-file-delete-dialog';
import { StorageFileList } from './storage-file-list';

type AdminStorageScreenProps = {
  bulk?: BulkDeleteOptions;
  items: API.StoredFileResponse[];
  total: number;
  page: number;
  pageSize: number;
  onPageSizeChange: (size: number) => void;
  loading: boolean;
  error: string;
  cleanup: {
    open: boolean;
    days: number;
    cleaning: boolean;
    error: string;
  };
  deletion: {
    item: API.StoredFileResponse | null;
    deleting: boolean;
    error: string;
  };
  onPageChange: (page: number) => void;
  onRetry: () => void;
  onOpenCleanup: () => void;
  onCloseCleanup: () => void;
  onCleanupDaysChange: (days: number) => void;
  onConfirmCleanup: () => void;
  onOpenDelete: (item: API.StoredFileResponse) => void;
  onCloseDelete: () => void;
  onConfirmDelete: () => void;
};

export function AdminStorageScreen({
  bulk,
  items,
  total,
  page,
  pageSize,
  onPageSizeChange,
  loading,
  error,
  cleanup,
  deletion,
  onPageChange,
  onRetry,
  onOpenCleanup,
  onCloseCleanup,
  onCleanupDaysChange,
  onConfirmCleanup,
  onOpenDelete,
  onCloseDelete,
  onConfirmDelete,
}: AdminStorageScreenProps) {
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div aria-busy={loading} className="flex flex-col gap-6">
      <div>
        <PageNavigation fallbackHref="/account" />
        <PageHeader
          action={
            <Button onClick={onOpenCleanup} variant="destructive">
              <Trash aria-hidden data-icon="inline-start" />
              清理历史文件
            </Button>
          }
          description="文件默认持久保存，不会自动过期。管理员可在确认后手动清理指定天数前的文件。"
          title="文件管理"
        />
      </div>

      {error && items.length > 0 ? (
        <FeedbackNotice
          action={
            <Button onClick={onRetry} size="default" variant="outline">
              <ArrowClockwise aria-hidden data-icon="inline-start" />
              重新加载
            </Button>
          }
          description={error}
          title="文件列表刷新失败"
          tone="error"
        />
      ) : null}

      {loading && items.length === 0 ? (
        <div className="flex flex-col gap-4">
          {['one', 'two', 'three', 'four', 'five'].map((key) => (
            <Skeleton className="h-14 w-full" key={key} />
          ))}
        </div>
      ) : items.length === 0 ? (
        error ? (
          <PageErrorNotice
            message={error}
            onRetry={onRetry}
            retryLabel="重新加载"
            title="暂时无法读取文件列表"
          />
        ) : (
          <PageEmptyNotice
            description="完成下载、剧本解析或报告生成后，文件会显示在这里。"
            icon={<FolderOpen aria-hidden />}
            title="暂无持久文件"
          />
        )
      ) : (
        <StorageFileList bulk={bulk} items={items} onDelete={onOpenDelete} />
      )}

      {total > 0 ? (
        <PagePagination
          pageSize={pageSize}
          busy={loading}
          onPageSizeChange={onPageSizeChange}
          ariaLabel="文件列表分页"
          onPageChange={onPageChange}
          page={page}
          pages={pages}
        />
      ) : null}

      <StorageCleanupDialog
        cleaning={cleanup.cleaning}
        days={cleanup.days}
        error={cleanup.error}
        onClose={onCloseCleanup}
        onConfirm={onConfirmCleanup}
        onDaysChange={onCleanupDaysChange}
        open={cleanup.open}
      />
      <StorageFileDeleteDialog
        deleting={deletion.deleting}
        error={deletion.error}
        item={deletion.item}
        onClose={onCloseDelete}
        onConfirm={onConfirmDelete}
      />
    </div>
  );
}
