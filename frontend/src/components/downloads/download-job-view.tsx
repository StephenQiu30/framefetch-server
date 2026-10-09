'use client';

import { DotsThreeIcon, Robot, TrashIcon } from '@phosphor-icons/react';
import type { MediaPlayerInstance } from '@vidstack/react';
import { cn } from 'cn';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';
import { DownloadDeleteDialog } from '@/components/downloads/download-delete-dialog';
import DownloadState, {
  DownloadCancelAction,
  DownloadTaskActions,
} from '@/components/downloads/download-state';
import {
  DownloadStatusCode,
  downloadStatusLabels,
  isTerminalDownloadStatus,
  statusVariant,
} from '@/components/downloads/download-state-model';
import { useDownloadJob } from '@/components/downloads/use-download-job';
import { DeferredContent } from '@/components/layout/deferred-content';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { markNavigationPush } from '@/components/layout/navigation-state';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { SplitLayout } from '@/components/layout/split-layout';
import MediaCover from '@/components/media/media-cover';
import { AspectRatio } from '@/components/ui/aspect-ratio';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { FieldDescription } from '@/components/ui/field';
import { Item, ItemContent, ItemTitle } from '@/components/ui/item';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDuration } from '@/lib/format';
import { audioCodecLabel } from '@/lib/media-format';
import { TaskSocketStatusCode } from '@/lib/task-socket';

const DownloadVideoPreview = dynamic(
  () => import('@/components/downloads/download-video-preview'),
  {
    ssr: false,
    loading: () => (
      <AspectRatio ratio={16 / 9}>
        <Skeleton
          aria-label="正在准备视频预览"
          role="status"
          className="size-full"
        />
      </AspectRatio>
    ),
  },
);
const AnalysisPanel = dynamic(
  () => import('@/components/analysis/analysis-panel'),
  {
    loading: () => (
      <Skeleton
        aria-label="正在准备分析面板"
        role="status"
        className="aspect-video w-full"
      />
    ),
  },
);

export default function DownloadJobView({
  jobId,
  analysisId,
  pollIntervalMs = 1500,
}: {
  jobId: string;
  analysisId?: string;
  pollIntervalMs?: number;
}) {
  const router = useRouter();
  const playerRef = useRef<MediaPlayerInstance>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const [previewReady, setPreviewReady] = useState(false);
  const state = useDownloadJob(jobId, pollIntervalMs);
  const active = state.job && !isTerminalDownloadStatus(state.job.status);
  const format = state.job?.format ?? undefined;
  const gallery = state.job?.media_kind === 'image_gallery';
  const collection = state.job?.media_kind === 'video_collection';
  const platform =
    state.job?.execution_context?.provider_key === 'wechat_channels'
      ? '微信视频号'
      : null;
  const sourceLabel = platform ?? state.job?.source_label ?? null;
  const title = state.job?.title ?? sourceLabel ?? '媒体下载任务';
  const thumbnail = state.job?.thumbnail_url ?? null;
  const extractor = platform ?? state.job?.extractor_key ?? null;
  const duration = state.job?.duration_seconds ?? undefined;

  function selectTime(milliseconds: number) {
    const player = playerRef.current;
    if (!player?.state.canPlay || !Number.isFinite(milliseconds)) return;
    const seconds = Math.max(0, milliseconds / 1000);
    player.currentTime = Number.isFinite(player.state.duration)
      ? Math.min(seconds, Math.max(0, player.state.duration - 0.01))
      : seconds;
    player.el?.scrollIntoView({ block: 'center', behavior: 'instant' });
    player.el?.focus({ preventScroll: true });
  }

  async function retry() {
    const retried = await state.retry();
    if (!retried) return;
    const target = `/downloads/detail?jobId=${encodeURIComponent(retried.id)}`;
    markNavigationPush(target);
    router.push(target);
  }

  async function remove() {
    if (!(await state.remove())) return;
    router.replace('/history');
  }

  if (state.removed) {
    return (
      <div className="inner-page">
        <PageNavigation fallbackHref="/history" />
        <PageEmptyNotice
          title="下载任务已删除"
          titleAs="h1"
          description="请返回下载记录查看其他任务。"
          action={
            <Button asChild variant="outline">
              <Link href="/history">返回下载记录</Link>
            </Button>
          }
        />
      </div>
    );
  }

  if (state.loading && !state.job) return <DownloadJobSkeleton />;

  return (
    <div className="inner-page">
      <PageNavigation fallbackHref="/history" />
      {state.error && !state.job ? (
        <PageErrorNotice
          message={state.error}
          onRetry={state.errorKind === 'load' ? state.refresh : undefined}
          retryLabel="重新加载"
          title={errorTitle(state.errorKind)}
        />
      ) : null}
      {state.job ? (
        <>
          <SplitLayout columns="primary" data-slot="download-job-layout">
            <section aria-label="媒体信息" className="flex flex-col gap-6">
              <div className="relative" data-slot="media-result-frame">
                {state.job.status === DownloadStatusCode.Succeeded &&
                state.job.file_available &&
                !gallery &&
                !collection ? (
                  <DownloadVideoPreview
                    key={state.job.id}
                    playerRef={playerRef}
                    onReadyChange={setPreviewReady}
                    onFilenameChange={setFilename}
                    container={
                      format?.container_preference === 'mp4' ||
                      format?.container_preference === 'webm'
                        ? format.container_preference
                        : undefined
                    }
                    downloadId={state.job.id}
                    poster={thumbnail}
                    title={title}
                  />
                ) : (
                  <>
                    <MediaCover
                      alt={`${title}媒体封面`}
                      fallback={{
                        detail: formatLabel(
                          format,
                          duration,
                          state.job.media_kind,
                          state.job.asset_count,
                        ),
                        eyebrow: sourceLabel ?? extractor,
                        title,
                      }}
                      pending={!isTerminalDownloadStatus(state.job.status)}
                      priority
                      src={thumbnail}
                    />
                    <Badge
                      className="absolute left-3 top-3"
                      variant={
                        state.job.status === DownloadStatusCode.Failed
                          ? 'secondary'
                          : statusVariant(state.job.status)
                      }
                    >
                      {downloadStatusLabels[state.job.status]}
                      {!isTerminalDownloadStatus(state.job.status)
                        ? ` ${state.job.progress}%`
                        : ''}
                    </Badge>
                    {!isTerminalDownloadStatus(state.job.status) ? (
                      <Progress
                        className="absolute inset-x-0 bottom-0"
                        aria-label="封面下载进度"
                        value={state.job.progress}
                      />
                    ) : null}
                  </>
                )}
              </div>
              {!isTerminalDownloadStatus(state.job.status) &&
              !gallery &&
              !collection ? (
                <FieldDescription>下载完成后可在这里播放</FieldDescription>
              ) : null}
              <div className="flex flex-wrap items-center gap-3">
                {sourceLabel || extractor ? (
                  <Badge variant="secondary">{sourceLabel ?? extractor}</Badge>
                ) : null}
                <FieldDescription>
                  {state.job.source_kind === 'browser_import'
                    ? '用户提供的文件'
                    : '内容范围以解析结果为准'}
                </FieldDescription>
              </div>
              <PageHeader title={title} />
              <dl
                aria-label="媒体规格"
                className="grid grid-cols-2 gap-4 sm:grid-cols-4"
              >
                {duration && duration > 0 ? (
                  <FileMetadata
                    label={platform ? '文件时长' : '时长'}
                    value={formatDuration(duration)}
                  />
                ) : null}
                {format ? (
                  <FileMetadata label="画质" value={`${format.height}P`} />
                ) : null}
                {gallery || collection || format ? (
                  <FileMetadata
                    label="格式"
                    value={
                      gallery || collection
                        ? 'ZIP'
                        : (format?.container_preference.toUpperCase() ?? '')
                    }
                  />
                ) : null}
                {sourceLabel || extractor ? (
                  <FileMetadata
                    label="来源"
                    value={sourceLabel ?? extractor ?? ''}
                  />
                ) : null}
              </dl>
            </section>
            <aside
              aria-label="文件信息与操作"
              className={cn(
                'flex min-h-0 flex-col',
                !active && 'lg:contain-size',
              )}
            >
              <Item
                variant="muted"
                className="min-h-0 flex-1 flex-nowrap items-stretch"
              >
                <ItemContent
                  className={cn(
                    'min-h-0 gap-6',
                    !active && 'lg:overflow-y-auto',
                  )}
                  data-slot="download-status-panel"
                >
                  {state.retryTarget && state.retryTarget !== jobId ? (
                    <FeedbackNotice
                      title="已创建新的下载任务"
                      description="重新下载的进度和结果会保存在新任务中。"
                      tone="info"
                      action={
                        <Button asChild variant="outline">
                          <Link
                            href={`/downloads/detail?jobId=${encodeURIComponent(state.retryTarget)}`}
                          >
                            查看新任务
                          </Link>
                        </Button>
                      }
                    />
                  ) : null}
                  {state.error ? (
                    <FeedbackNotice
                      action={
                        state.errorKind === 'sync' ? (
                          <Button variant="outline" onClick={state.refresh}>
                            恢复下载状态
                          </Button>
                        ) : undefined
                      }
                      presentation={
                        state.errorKind === 'action' ? 'toast' : 'inline'
                      }
                      description={state.error}
                      title={errorTitle(state.errorKind)}
                      tone="error"
                    />
                  ) : null}
                  <DownloadState
                    job={state.job}
                    recoveryAction={
                      state.job.status === DownloadStatusCode.Failed ? (
                        <DownloadTaskActions
                          action={state.action}
                          job={state.job}
                          onDownload={state.download}
                          onRetry={() => void retry()}
                        />
                      ) : undefined
                    }
                  />
                  {state.job.status === DownloadStatusCode.Succeeded &&
                  state.job.file_available ? (
                    <dl
                      aria-label="文件规格"
                      className="grid grid-cols-2 gap-4"
                    >
                      {filename ? (
                        <FileMetadata label="文件名" value={filename} />
                      ) : null}
                      {format ? (
                        <>
                          <FileMetadata
                            label="分辨率"
                            value={`${format.width}×${format.height}`}
                          />
                          <FileMetadata
                            label="编码"
                            value={`${format.video_codec_family.toUpperCase()} + ${audioCodecLabel(format.audio_codec_family)}`}
                          />
                        </>
                      ) : null}
                      {state.job.finished_at ? (
                        <FileMetadata
                          label="完成时间"
                          value={formatDate(state.job.finished_at)}
                        />
                      ) : null}
                      <FileMetadata
                        label="执行次数"
                        value={`第 ${state.job.attempt} 次执行`}
                      />
                    </dl>
                  ) : null}
                  {!isTerminalDownloadStatus(state.job.status) ? (
                    <FieldDescription aria-live="polite">
                      {state.socketStatus === TaskSocketStatusCode.Connected
                        ? '实时状态已连接'
                        : state.socketStatus === TaskSocketStatusCode.Degraded
                          ? '实时连接中断，正在低频恢复'
                          : '正在连接实时状态'}
                    </FieldDescription>
                  ) : null}
                  <div className="mt-auto flex flex-col gap-3">
                    {state.job.status !== DownloadStatusCode.Failed ? (
                      <DownloadTaskActions
                        action={state.action}
                        job={state.job}
                        onDownload={state.download}
                        onRetry={() => void retry()}
                      />
                    ) : null}
                    {!gallery && !collection ? (
                      state.job.status === DownloadStatusCode.Succeeded &&
                      state.job.file_available ? (
                        <Button asChild variant="outline">
                          <a href="#download-analysis">
                            <Robot aria-hidden data-icon="inline-start" />
                            AI 拉片分析
                          </a>
                        </Button>
                      ) : (
                        <Button disabled variant="outline">
                          <Robot aria-hidden data-icon="inline-start" />
                          AI 拉片分析
                        </Button>
                      )
                    ) : null}
                    <div className="flex flex-wrap items-center gap-3">
                      <DownloadCancelAction
                        action={state.action}
                        job={state.job}
                        onCancel={state.cancel}
                      />
                      {!isTerminalDownloadStatus(state.job.status) ? (
                        <>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                ref={menuTriggerRef}
                                aria-label="更多任务操作"
                                disabled={state.action !== null}
                                variant="ghost"
                                size="icon"
                              >
                                <DotsThreeIcon aria-hidden />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuGroup>
                                <DropdownMenuItem
                                  onSelect={() => {
                                    // Let the menu release its focus scope before opening the dialog.
                                    window.setTimeout(
                                      () => setDeleteOpen(true),
                                      0,
                                    );
                                  }}
                                >
                                  <TrashIcon aria-hidden />
                                  删除任务
                                </DropdownMenuItem>
                              </DropdownMenuGroup>
                            </DropdownMenuContent>
                          </DropdownMenu>
                          <DownloadDeleteDialog
                            active
                            busy={state.action === 'delete'}
                            disabled={state.action !== null}
                            onDelete={remove}
                            showTrigger={false}
                            open={deleteOpen}
                            onOpenChange={setDeleteOpen}
                            onCloseAutoFocus={(event) => {
                              event.preventDefault();
                              menuTriggerRef.current?.focus();
                            }}
                          />
                        </>
                      ) : (
                        <DownloadDeleteDialog
                          active={false}
                          busy={state.action === 'delete'}
                          disabled={state.action !== null}
                          onDelete={remove}
                        />
                      )}
                    </div>
                    <FieldDescription>
                      {state.job.status === DownloadStatusCode.Succeeded &&
                      state.job.file_available
                        ? '可获取文件保存到本机，并继续查看分析结果。'
                        : !isTerminalDownloadStatus(state.job.status)
                          ? '下载并校验完成后可获取文件；单视频可继续进行 AI 分析。'
                          : '文件暂不可获取，请按任务提示恢复。'}
                    </FieldDescription>
                  </div>
                </ItemContent>
              </Item>
            </aside>
          </SplitLayout>
          {state.job.status === DownloadStatusCode.Succeeded ? (
            !gallery && !collection ? (
              <section
                className="mt-8"
                id="download-analysis"
                aria-label="AI 分析"
              >
                <DeferredContent
                  eager={Boolean(analysisId)}
                  placeholder={
                    <Skeleton
                      aria-label="分析面板占位"
                      className="aspect-video w-full"
                    />
                  }
                >
                  <AnalysisPanel
                    downloadId={state.job.id}
                    analysisId={analysisId}
                    onSelectTime={
                      state.job.file_available && previewReady
                        ? selectTime
                        : undefined
                    }
                    playbackUnavailableReason={
                      state.job.file_available
                        ? undefined
                        : '原视频文件已清理，分析结果仍可阅读；重新获取视频后才能回看时间证据。'
                    }
                  />
                </DeferredContent>
              </section>
            ) : null
          ) : isTerminalDownloadStatus(state.job.status) ? null : (
            <FieldDescription className="mt-8">
              下载并验证完成后，可继续生成视觉分镜、高光与资产目录。
            </FieldDescription>
          )}
        </>
      ) : null}
    </div>
  );
}

function errorTitle(kind: 'load' | 'sync' | 'action' | null) {
  if (kind === 'load') return '无法读取下载任务';
  if (kind === 'sync') return '状态同步暂时中断';
  if (kind === 'action') return '操作未完成';
  return '请求未完成';
}

function DownloadJobSkeleton() {
  return (
    <div className="inner-page">
      <PageNavigation fallbackHref="/history" />
      <SplitLayout
        aria-label="正在读取下载任务"
        columns="primary"
        role="status"
      >
        <div aria-hidden className="flex flex-col gap-4">
          <AspectRatio ratio={16 / 9}>
            <Skeleton className="size-full" />
          </AspectRatio>
          <Skeleton className="aspect-[8/1] w-full" />
        </div>
        <div aria-hidden className="flex flex-col gap-4">
          <Skeleton className="aspect-square w-full" />
          <Skeleton className="aspect-[8/1] w-full" />
        </div>
      </SplitLayout>
    </div>
  );
}

function formatLabel(
  format: API.SemanticPlanResponse | null | undefined,
  duration: number | undefined,
  mediaKind: API.MediaKind | undefined,
  assetCount: number | undefined,
) {
  if (mediaKind === 'image_gallery') {
    return `${assetCount ?? 0} 张原图 · ZIP`;
  }
  if (mediaKind === 'video_collection') {
    return `${assetCount ?? 0} 个视频 · ZIP`;
  }
  if (!format) return duration ? formatDuration(duration) : '正在读取媒体信息';
  return `${format.width}×${format.height} · ${format.video_codec_family.toUpperCase()} + ${audioCodecLabel(format.audio_codec_family)}${duration ? ` · ${formatDuration(duration)}` : ''}`;
}

function FileMetadata({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt>
        <FieldDescription>{label}</FieldDescription>
      </dt>
      <dd>
        <ItemTitle className="line-clamp-none [overflow-wrap:anywhere]">
          {value}
        </ItemTitle>
      </dd>
    </div>
  );
}

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'short',
  timeStyle: 'medium',
});
function formatDate(value: string) {
  return dateFormatter.format(new Date(value));
}
