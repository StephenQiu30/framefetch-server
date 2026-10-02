'use client';

import type { MediaPlayerInstance } from '@vidstack/react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';
import AnalysisPanel from '@/components/analysis/analysis-panel';
import { DownloadDeleteDialog } from '@/components/downloads/download-delete-dialog';
import DownloadState from '@/components/downloads/download-state';
import {
  DownloadStatusCode,
  isTerminalDownloadStatus,
} from '@/components/downloads/download-state-model';
import DownloadVideoPreview from '@/components/downloads/download-video-preview';
import { useDownloadJob } from '@/components/downloads/use-download-job';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { markNavigationPush } from '@/components/layout/navigation-state';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageNavigation } from '@/components/layout/page-navigation';
import MediaCover from '@/components/media/media-cover';
import {
  MediaResult,
  MediaResultSkeleton,
} from '@/components/media/media-result';
import { Button } from '@/components/ui/button';
import { formatDuration } from '@/lib/format';
import { audioCodecLabel } from '@/lib/media-format';
import { TaskSocketStatusCode } from '@/lib/task-socket';

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
  const [previewReady, setPreviewReady] = useState(false);
  const state = useDownloadJob(jobId, pollIntervalMs);
  const format = state.job?.format ?? undefined;
  const gallery = state.job?.media_kind === 'image_gallery';
  const collection = state.job?.media_kind === 'video_collection';
  const title = state.job?.title ?? state.job?.source_label ?? '媒体下载任务';
  const thumbnail = state.job?.thumbnail_url ?? null;
  const extractor = state.job?.extractor_key ?? null;
  const sourceLabel = state.job?.source_label ?? null;
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
      <PageNavigation
        fallbackHref="/history"
        action={
          state.job ? (
            <DownloadDeleteDialog
              active={!isTerminalDownloadStatus(state.job.status)}
              busy={state.action === 'delete'}
              disabled={state.action !== null}
              onDelete={remove}
            />
          ) : null
        }
      />
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
          <MediaResult
            headingLevel={1}
            title={title}
            metadata={
              <p className="mt-2 text-sm text-muted-foreground">
                {sourceLabel ? `${sourceLabel} · ` : ''}
                {extractor && extractor !== sourceLabel
                  ? `${extractor} · `
                  : ''}
                {formatLabel(
                  format,
                  duration,
                  state.job?.media_kind,
                  state.job?.asset_count,
                )}
              </p>
            }
            media={
              state.job.status === DownloadStatusCode.Succeeded &&
              state.job.file_available &&
              !gallery &&
              !collection ? (
                <DownloadVideoPreview
                  key={state.job.id}
                  playerRef={playerRef}
                  onReadyChange={setPreviewReady}
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
                <MediaCover
                  alt={`${title}媒体封面`}
                  className="rounded-none ring-0"
                  fallback={{
                    detail: formatLabel(
                      format,
                      duration,
                      state.job?.media_kind,
                      state.job?.asset_count,
                    ),
                    eyebrow: sourceLabel ?? extractor,
                    title,
                  }}
                  pending={!isTerminalDownloadStatus(state.job.status)}
                  priority
                  src={thumbnail}
                />
              )
            }
            actions={
              <div className="flex flex-1 flex-col gap-6">
                {state.retryTarget && state.retryTarget !== jobId ? (
                  <FeedbackNotice
                    title="已创建新的下载任务"
                    description="重新下载的进度和结果会保存在新任务中。"
                    tone="info"
                    action={
                      <Button asChild size="sm" variant="outline">
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
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={state.refresh}
                        >
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
                  action={state.action}
                  job={state.job}
                  onCancel={state.cancel}
                  onDownload={state.download}
                  onRetry={() => void retry()}
                />
                {!isTerminalDownloadStatus(state.job.status) ? (
                  <p
                    aria-live="polite"
                    className="mt-4 text-xs text-muted-foreground"
                  >
                    {state.socketStatus === TaskSocketStatusCode.Connected
                      ? '实时状态已连接'
                      : state.socketStatus === TaskSocketStatusCode.Degraded
                        ? '实时连接中断，正在低频恢复'
                        : '正在连接实时状态'}
                  </p>
                ) : null}
              </div>
            }
          />
          {state.job.status === DownloadStatusCode.Succeeded ? (
            !gallery && !collection ? (
              <div className="mt-14 sm:mt-20">
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
              </div>
            ) : null
          ) : isTerminalDownloadStatus(state.job.status) ? null : (
            <p className="mt-14 py-8 text-sm text-muted-foreground sm:mt-20">
              下载并验证完成后，可继续生成视觉分镜、高光与资产目录。
            </p>
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
      <MediaResultSkeleton label="正在读取下载任务" />
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
