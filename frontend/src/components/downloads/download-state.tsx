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
import { Button } from '@/components/ui/button';
import { CardTitle } from '@/components/ui/card';
import { FieldDescription } from '@/components/ui/field';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from '@/components/ui/item';
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
} from './download-state-model';

type Props = {
  action: 'cancel' | 'delete' | 'download' | 'retry' | null;
  job: API.DownloadResponse;
  onCancel: () => void;
  onDownload: () => void;
  onRetry: () => void;
};

export default function DownloadState({ job }: { job: API.DownloadResponse }) {
  const active = isActiveDownloadStatus(job.status);
  const complete = job.status === DownloadStatusCode.Succeeded;
  const recovery = downloadRecovery(job);

  return (
    <section aria-label="下载进度与执行" className="flex flex-col gap-6">
      <Item variant="muted" className="items-start">
        <ItemContent className="gap-4">
          <ItemTitle>
            <h2 id="download-status-title">{statusHeading(job)}</h2>
          </ItemTitle>
          <ItemDescription className="line-clamp-none">
            {statusDescription(job)}
          </ItemDescription>
          {active || complete ? (
            <>
              <div className="flex items-center justify-between gap-4">
                <CardTitle>{job.progress}%</CardTitle>
                <FieldDescription>{displayStage(job)}</FieldDescription>
              </div>
              <Progress
                aria-label={`下载进度 ${job.progress}%`}
                value={job.progress}
              />
            </>
          ) : null}
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <div>
              <dt>
                <FieldDescription>执行次数</FieldDescription>
              </dt>
              <dd>
                <ItemTitle>第 {job.attempt} 次执行</ItemTitle>
              </dd>
            </div>
            <div>
              <dt>
                <FieldDescription>当前阶段</FieldDescription>
              </dt>
              <dd>
                <ItemTitle>{displayStage(job)}</ItemTitle>
              </dd>
            </div>
            <div>
              <dt>
                <FieldDescription>平台身份</FieldDescription>
              </dt>
              <dd>
                <ItemTitle>
                  {job.source_kind === 'browser_import'
                    ? '本地导入'
                    : job.execution_context
                      ? job.execution_context.identity_used
                        ? '使用 Chrome 身份'
                        : '未使用平台身份'
                      : '未提供'}
                </ItemTitle>
              </dd>
            </div>
          </dl>
        </ItemContent>
      </Item>
      {job.status === DownloadStatusCode.Failed ? (
        <PageErrorNotice
          compact
          message={failureDescription(job)}
          title={failureTitle(job.error_code)}
        />
      ) : null}
      {complete && !job.file_available ? (
        <Alert>
          <AlertTitle>文件已经不在存储中</AlertTitle>
          <AlertDescription>
            {recovery === 'reimport'
              ? '记录仍会保留。请返回首页重新选择本地文件导入。'
              : '下载记录仍会保留。管理员清理文件后，你可以重新创建下载任务。'}
          </AlertDescription>
        </Alert>
      ) : null}
      <DownloadExecutionSummary job={job} />
    </section>
  );
}

export function DownloadTaskActions({
  action,
  job,
  onDownload,
  onRetry,
}: Omit<Props, 'onCancel'>) {
  const complete = job.status === DownloadStatusCode.Succeeded;
  const recovery = downloadRecovery(job);
  return (
    <div className="grid gap-3">
      {!complete || job.file_available ? (
        <Button
          className="w-full"
          disabled={!complete || !job.file_available || action !== null}
          onClick={onDownload}
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
        <Button asChild className="w-full">
          <Link href="/">返回首页重新导入</Link>
        </Button>
      ) : null}
      {recovery === 'reparse' ? (
        <Button asChild className="w-full">
          <Link href="/">重新解析</Link>
        </Button>
      ) : null}
      {recovery === 'retry' ? (
        <Button className="w-full" disabled={action !== null} onClick={onRetry}>
          {action === 'retry' ? (
            <Spinner aria-hidden data-icon="inline-start" />
          ) : (
            <ArrowClockwise data-icon="inline-start" />
          )}
          {retryActionLabel(job.error_code)}
        </Button>
      ) : null}
    </div>
  );
}

export function DownloadCancelAction({
  action,
  job,
  onCancel,
}: Pick<Props, 'action' | 'job' | 'onCancel'>) {
  if (!isActiveDownloadStatus(job.status)) return null;
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button disabled={action !== null} variant="outline">
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
  );
}
