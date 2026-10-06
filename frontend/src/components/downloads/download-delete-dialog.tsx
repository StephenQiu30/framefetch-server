'use client';

import { Trash, Warning } from '@phosphor-icons/react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';

export function DownloadDeleteDialog({
  active,
  busy,
  disabled = false,
  compact = false,
  count,
  onDelete,
  showTrigger = true,
  open,
  onOpenChange,
  onCloseAutoFocus,
}: {
  active: boolean;
  busy: boolean;
  disabled?: boolean;
  compact?: boolean;
  count?: number;
  onDelete: () => Promise<void>;
  showTrigger?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      {showTrigger ? (
        <AlertDialogTrigger asChild>
          <Button
            aria-label={compact ? '删除下载记录' : undefined}
            disabled={disabled || busy}
            aria-busy={busy}
            size={compact ? 'icon' : 'default'}
            variant={compact ? 'ghost' : 'outline'}
          >
            {busy ? (
              <Spinner
                aria-hidden
                data-icon={compact ? undefined : 'inline-start'}
              />
            ) : (
              <Trash
                aria-hidden
                data-icon={compact ? undefined : 'inline-start'}
              />
            )}
            {compact ? (
              <span className="sr-only">删除</span>
            ) : count !== undefined ? (
              `批量删除（${count}）`
            ) : (
              '删除任务'
            )}
          </Button>
        </AlertDialogTrigger>
      ) : null}
      <AlertDialogContent size="sm" onCloseAutoFocus={onCloseAutoFocus}>
        <AlertDialogHeader>
          <AlertDialogMedia>
            <Warning aria-hidden />
          </AlertDialogMedia>
          <AlertDialogTitle>
            {count !== undefined
              ? `删除选中的 ${count} 项任务与文件？`
              : '删除任务与文件？'}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {active ? '当前任务会先被取消。' : ''}
            下载记录、视频文件、本地上传源文件和私有封面将永久删除。此操作不可撤销。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>保留任务</AlertDialogCancel>
          <AlertDialogAction
            disabled={busy}
            variant="destructive"
            onClick={onDelete}
          >
            确认删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
