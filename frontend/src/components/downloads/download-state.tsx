'use client';

import { ArrowClockwise, DownloadSimple, X } from '@phosphor-icons/react';
import Link from 'next/link';

import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Spinner } from '@/components/ui/spinner';

import { DownloadExecutionSummary } from './download-execution-summary';
import {
  DownloadStatusCode,
  displayStage,
  downloadRecovery,
  failureDescription,
  failureTitle,
  isActiveDownloadStatus,
  retryActionLabel,
  statusDescription,
  statusHeading,
  statusLabels,
  statusVariant,
} from './download-state-model';

type Props = {
  action: 'cancel' | 'delete' | 'download' | 'retry' | null;
  job: API.DownloadResponse;
  onCancel: () => void;
  onDownload: () => void;
  onRetry: () => void;
};

export default function DownloadState({
  action,
  job,
  onCancel,
  onDownload,
  onRetry,
}: Props) {
  const active = isActiveDownloadStatus(job.status);
  const complete = job.status === DownloadStatusCode.Succeeded;
  const recovery = downloadRecovery(job);
  const showProgress = active;

  return (
    <div className="flex flex-1 flex-col">
      <Badge variant={statusVariant(job.status)}>
        {statusLabels[job.status]}
      </Badge>
      <h2
        className="mt-4 text-2xl font-medium leading-tight tracking-[-0.035em] sm:text-[32px]"
        id="download-status-title"
      >
        {statusHeading(job)}
      </h2>
      <p className="mt-3 max-w-md text-sm leading-6 text-muted-foreground">
        {statusDescription(job)}
      </p>

      {showProgress ? (
        <>
          <div className="mt-7 flex items-end justify-between gap-5">
            <span className="text-3xl font-medium leading-none tracking-[-0.045em] tabular-nums">
              {job.progress}%
            </span>
            <span className="text-sm text-muted-foreground">
              {displayStage(job)}
            </span>
          </div>
          <Progress
            aria-label={`下载进度 ${job.progress}%`}
            className="mt-3"
            value={job.progress}
          />
        </>
      ) : null}

      {job.status === DownloadStatusCode.Failed ? (
        <PageErrorNotice
          className="mt-6"
          compact
          message={failureDescription(job)}
          title={failureTitle(job.error_code)}
        />
      ) : null}

      {complete && !job.file_available ? (
        <Alert className="mt-6" variant="default">
          <AlertTitle>文件已经不在存储中</AlertTitle>
          <AlertDescription>
            {recovery === 'reimport'
              ? '记录仍会保留。请返回首页重新选择本地文件导入。'
              : '下载记录仍会保留。管理员清理文件后，你可以重新创建下载任务。'}
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="mt-auto grid gap-3 pt-7">
        {complete && job.file_available ? (
          <Button
            className="w-full"
            disabled={action !== null}
            onClick={onDownload}
            size="lg"
          >
            {action === 'download' ? (
              <Spinner aria-hidden data-icon="inline-start" />
            ) : (
              <DownloadSimple data-icon="inline-start" />
            )}
            {job.media_kind === 'image_gallery'
              ? '获取图集 ZIP'
              : job.media_kind === 'video_collection'
                ? '获取视频合集 ZIP'
                : '获取视频文件'}
          </Button>
        ) : null}
        {recovery === 'reimport' ? (
          <Button asChild className="w-full" size="lg">
            <Link href="/">返回首页重新导入</Link>
          </Button>
        ) : null}
        {recovery === 'retry' ? (
          <Button
            className="w-full"
            disabled={action !== null}
            onClick={onRetry}
            size="lg"
          >
            {action === 'retry' ? (
              <Spinner aria-hidden data-icon="inline-start" />
            ) : (
              <ArrowClockwise data-icon="inline-start" />
            )}
            {retryActionLabel(job.error_code)}
          </Button>
        ) : null}
        {active ? (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                className="w-full"
                disabled={action !== null}
                size="lg"
                variant="outline"
              >
                {action === 'cancel' ? (
                  <Spinner aria-hidden data-icon="inline-start" />
                ) : (
                  <X data-icon="inline-start" />
                )}
                取消任务
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent size="sm">
              <AlertDialogHeader>
                <AlertDialogMedia>
                  <X aria-hidden />
                </AlertDialogMedia>
                <AlertDialogTitle>取消当前下载任务？</AlertDialogTitle>
                <AlertDialogDescription>
                  {job.source_kind === 'browser_import'
                    ? '确认后将停止当前导入。再次导入需要重新选择本地文件。'
                    : '确认后将停止当前下载。取消后可在当前页面重新下载。'}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>继续下载</AlertDialogCancel>
                <AlertDialogAction
                  disabled={action !== null}
                  variant="destructive"
                  onClick={onCancel}
                >
                  确认取消下载
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : null}
      </div>

      <DownloadExecutionSummary job={job} />
    </div>
  );
}
