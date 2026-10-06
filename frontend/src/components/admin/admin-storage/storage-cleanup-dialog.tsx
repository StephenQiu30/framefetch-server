import { Trash } from '@phosphor-icons/react';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ItemDescription } from '@/components/ui/item';
import { Label } from '@/components/ui/label';
import { Spinner } from '@/components/ui/spinner';

type StorageCleanupDialogProps = {
  days: number;
  error: string;
  open: boolean;
  cleaning: boolean;
  onDaysChange: (days: number) => void;
  onClose: () => void;
  onConfirm: () => void;
};

export function StorageCleanupDialog({
  days,
  error,
  open,
  cleaning,
  onDaysChange,
  onClose,
  onConfirm,
}: StorageCleanupDialogProps) {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !cleaning) onClose();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogMedia>
            <Trash aria-hidden />
          </AlertDialogMedia>
          <AlertDialogTitle>清理历史文件？</AlertDialogTitle>
          <AlertDialogDescription>
            将永久删除指定天数前的视频、剧本文档和分析报告。正在执行分析的源文件会被跳过。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="cleanup-days">清理多少天前的文件</Label>
          <Input
            id="cleanup-days"
            min={1}
            max={3650}
            onChange={(event) => onDaysChange(Number(event.target.value))}
            type="number"
            value={days}
          />
          <ItemDescription className="line-clamp-none">
            默认 30 天，范围 1–3650 天。
          </ItemDescription>
        </div>
        {error ? (
          <FeedbackNotice
            presentation="toast"
            title="操作未完成"
            description={error}
            tone="error"
          />
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={cleaning}>取消</AlertDialogCancel>
          <Button
            disabled={
              cleaning || !Number.isInteger(days) || days < 1 || days > 3650
            }
            onClick={onConfirm}
            variant="destructive"
          >
            {cleaning ? (
              <Spinner aria-hidden data-icon="inline-start" />
            ) : (
              <Trash aria-hidden data-icon="inline-start" />
            )}
            {cleaning ? '正在清理' : '确认清理'}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
