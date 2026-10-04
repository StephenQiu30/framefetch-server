'use client';

import { ArrowClockwise, DownloadSimple, Robot } from '@phosphor-icons/react';
import { useState } from 'react';
import AnalysisConfigurator from '@/components/analysis/analysis-configurator';
import AnalysisDeleteDialog from '@/components/analysis/analysis-delete-dialog';
import {
  AnalysisReportStatusCode,
  AnalysisStatusCode,
  analysisReportStatusLabel,
  isActiveAnalysisStatus,
  stageLabels,
  statusLabels,
} from '@/components/analysis/analysis-panel-model';
import AnalysisReportDownloadLink from '@/components/analysis/analysis-report-download-link';
import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import AnalysisStorageNotice from '@/components/analysis/analysis-storage-notice';
import AnalysisVideoResult, {
  isVideoAnalysisResult,
} from '@/components/analysis/analysis-video-result';
import { useAnalysisJob } from '@/components/analysis/use-analysis-job';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
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
import { localizedErrorMessage } from '@/lib/error-messages';
import { TaskSocketStatusCode } from '@/lib/task-socket';

export default function AnalysisPanel({
  downloadId,
  analysisId,
  onSelectTime,
  playbackUnavailableReason = '视频预览尚未就绪，请在上方播放器检查或重新加载。',
  pollIntervalMs = 1500,
}: {
  downloadId: string;
  analysisId?: string;
  onSelectTime?: (milliseconds: number) => void;
  playbackUnavailableReason?: string;
  pollIntervalMs?: number;
}) {
  const state = useAnalysisJob(downloadId, pollIntervalMs, 'video', analysisId);
  const [creating, setCreating] = useState(false);

  if (state.loading && state.action !== 'start') {
    return (
      <div className="py-12" role="status">
        <Spinner aria-hidden className="mr-2 inline" />
        正在读取分析记录
      </div>
    );
  }
  if (state.errorKind === 'load' && state.error) {
    return (
      <PageErrorNotice
        compact
        title="暂时无法读取分析记录"
        message={state.error}
        onRetry={() => void state.retryPoll()}
      />
    );
  }

  const completedResult = state.job?.result;
  if (
    state.job?.status === AnalysisStatusCode.Succeeded &&
    completedResult &&
    (isVideoAnalysisResult(completedResult, state.job.input_kind) ||
      completedResult.kind === 'skill_report')
  ) {
    const formats = new Set(
      state.job.report?.status === AnalysisReportStatusCode.Available
        ? state.job.report.artifacts.map((artifact) => artifact.format)
        : [],
    );
    const reportAvailable = formats.has('markdown') && formats.has('docx');
    return (
      <div className="py-12 sm:py-16">
        {state.error ? (
          <FeedbackNotice
            action={
              state.errorKind === 'sync' ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void state.retryPoll()}
                >
                  恢复同步
                </Button>
              ) : undefined
            }
            className="mb-8"
            presentation={state.errorKind === 'action' ? 'toast' : 'inline'}
            description={state.error}
            title="操作未完成"
            tone="error"
          />
        ) : null}
        <div className="flex flex-col gap-6">
          {completedResult.kind !== 'video_article' ? (
            <div className="min-w-0 w-full">
              <h2 className="w-full text-xl font-semibold tracking-tight">
                {completedResult.title}
              </h2>
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="default">已完成</Badge>
            <span className="text-sm text-muted-foreground tabular-nums">
              第 {state.job.run_no} 次执行
            </span>
            {reportAvailable ? (
              <>
                <Button asChild variant="outline">
                  <AnalysisReportDownloadLink
                    download={`analysis-report-${state.job.id}.md`}
                    analysisId={state.job.id}
                    format="md"
                  >
                    <DownloadSimple data-icon="inline-start" />
                    导出 Markdown
                  </AnalysisReportDownloadLink>
                </Button>
                <Button asChild>
                  <AnalysisReportDownloadLink
                    download={`analysis-report-${state.job.id}.docx`}
                    analysisId={state.job.id}
                    format="docx"
                  >
                    <DownloadSimple data-icon="inline-start" />
                    导出 DOCX
                  </AnalysisReportDownloadLink>
                </Button>
              </>
            ) : null}
            <Button
              disabled={
                Boolean(state.action) ||
                completedResult.kind === 'skill_report' ||
                state.job.error_code === 'analysis_outcome_unknown'
              }
              onClick={() => void state.retry()}
              variant="outline"
            >
              {state.action === 'retry' ? (
                <Spinner aria-hidden data-icon="inline-start" />
              ) : (
                <ArrowClockwise data-icon="inline-start" />
              )}
              {state.action === 'retry' ? '正在重新分析' : '重新分析'}
            </Button>
            <Button
              disabled={Boolean(state.action)}
              onClick={() => setCreating(!creating)}
              variant="outline"
            >
              {creating ? '收起新建任务' : '新建分析'}
            </Button>
            <AnalysisDeleteDialog
              disabled={Boolean(state.action)}
              busy={state.action === 'delete'}
              onDelete={state.remove}
            />
          </div>
        </div>
        {!reportAvailable ? (
          <FeedbackNotice
            className="mt-8"
            description={
              completedResult.kind === 'skill_report'
                ? '历史报告仅保留已保存的正文；请使用最新 Skill 新建任务以分析这份视频。'
                : '分析结果仍可查看，但报告文件已被清理或暂时不可读取。你可以重新分析以生成新报告。'
            }
            title="报告已清理或暂时不可用"
            tone="error"
          />
        ) : null}
        <div className="mt-5">
          <AnalysisStorageNotice />
        </div>
        {!onSelectTime ? (
          <p className="mt-3 text-sm text-muted-foreground">
            {playbackUnavailableReason}
          </p>
        ) : null}
        {creating ? (
          <AnalysisConfigurator
            inputId={downloadId}
            busy={state.action === 'start'}
            onStart={(input) => {
              setCreating(false);
              void state.start(input);
            }}
          />
        ) : null}
        {completedResult.kind === 'skill_report' ? (
          <div className="mt-10">
            <AnalysisReportPreview markdown={state.job.report_markdown ?? ''} />
          </div>
        ) : (
          <AnalysisVideoResult
            onSelectTime={onSelectTime}
            reportMarkdown={state.job.report_markdown}
            result={completedResult}
            skillId={state.job.skill_id}
          />
        )}
      </div>
    );
  }

  return (
    <div className="py-12 sm:py-16">
      <div className="flex items-start justify-between gap-6">
        <div className="max-w-3xl">
          <h2
            className="text-xl font-semibold tracking-tight"
            id="analysis-title"
          >
            AI 智能分析
          </h2>
          <p className="mt-4 max-w-2xl leading-7 text-muted-foreground">
            根据视频材料撰写文章、审阅成片、拆解素材，或制定传播方案。
          </p>
        </div>
      </div>

      {state.error ? (
        <FeedbackNotice
          action={
            state.errorKind === 'sync' ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => void state.retryPoll()}
              >
                恢复同步
              </Button>
            ) : undefined
          }
          className="mt-6"
          presentation={state.errorKind === 'action' ? 'toast' : 'inline'}
          description={state.error}
          title="操作未完成"
          tone="error"
        />
      ) : null}

      {!state.job ? (
        <AnalysisConfigurator
          inputId={downloadId}
          busy={state.action === 'start'}
          onStart={state.start}
        />
      ) : (
        <AnalysisJobState
          job={state.job}
          state={state}
          onSelectTime={onSelectTime}
          playbackUnavailableReason={playbackUnavailableReason}
        />
      )}
      {state.job && !isActiveAnalysisStatus(state.job.status) ? (
        <div className="mt-6">
          <Button
            disabled={Boolean(state.action)}
            onClick={() => setCreating(!creating)}
            variant="outline"
          >
            {creating ? '收起新建任务' : '新建分析'}
          </Button>
          {creating ? (
            <AnalysisConfigurator
              inputId={downloadId}
              busy={state.action === 'start'}
              onStart={(input) => {
                setCreating(false);
                void state.start(input);
              }}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function AnalysisJobState({
  job,
  state,
  onSelectTime,
  playbackUnavailableReason,
}: {
  job: API.AnalysisResponse;
  state: ReturnType<typeof useAnalysisJob>;
  onSelectTime?: (milliseconds: number) => void;
  playbackUnavailableReason: string;
}) {
  const cancellable = isActiveAnalysisStatus(job.status);
  return (
    <div className="mt-10 w-full">
      <div className="flex justify-between gap-4 text-sm font-medium">
        <span>{statusLabels[job.status]}</span>
        <span className="tabular-nums">{job.progress}%</span>
      </div>
      <Progress
        aria-label={`分析进度 ${job.progress}%`}
        className="mt-3"
        value={job.progress}
      />
      <p className="mt-3 text-sm text-muted-foreground">
        第 {job.run_no} 次执行 · 当前阶段：
        {job.stage ? stageLabels[job.stage] : '等待调度'} ·{' '}
        {job.attempt > 0
          ? `本次第 ${job.attempt} 个技术尝试`
          : '尚未开始技术尝试'}
      </p>
      <div className="mt-2">
        <AnalysisStorageNotice />
      </div>
      {job.status === AnalysisStatusCode.Failed ? (
        <PageErrorNotice
          className="mt-6"
          compact
          message={
            localizedErrorMessage(job.error_code) ??
            'AI 分析未能完成，请稍后重试。'
          }
          title="分析失败"
        />
      ) : null}
      <p aria-live="polite" className="mt-2 text-xs text-muted-foreground">
        {state.socketStatus === TaskSocketStatusCode.Connected
          ? '实时状态已连接'
          : state.socketStatus === TaskSocketStatusCode.Degraded
            ? '实时连接中断，正在低频恢复'
            : '正在连接实时状态'}
      </p>
      <div className="mt-7 flex flex-wrap gap-3">
        {cancellable ? (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button disabled={Boolean(state.action)} variant="outline">
                {state.action === 'cancel' ? (
                  <Spinner aria-hidden data-icon="inline-start" />
                ) : null}
                取消分析
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent size="sm">
              <AlertDialogHeader>
                <AlertDialogMedia>
                  <Robot aria-hidden />
                </AlertDialogMedia>
                <AlertDialogTitle>取消当前分析任务？</AlertDialogTitle>
                <AlertDialogDescription>
                  确认后将停止当前分析。你之后仍可重新发起分析任务。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>继续分析</AlertDialogCancel>
                <AlertDialogAction
                  disabled={Boolean(state.action)}
                  variant="destructive"
                  onClick={state.cancel}
                >
                  确认取消分析
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : null}
        {job.status === AnalysisStatusCode.Failed ||
        job.status === AnalysisStatusCode.Cancelled ? (
          <Button
            disabled={
              Boolean(state.action) ||
              job.error_code === 'analysis_outcome_unknown'
            }
            onClick={() => void state.retry()}
          >
            {state.action === 'retry' ? (
              <Spinner aria-hidden data-icon="inline-start" />
            ) : null}
            {state.action === 'retry' ? '正在重试' : '重试分析'}
          </Button>
        ) : null}
        <AnalysisDeleteDialog
          disabled={Boolean(state.action)}
          busy={state.action === 'delete'}
          onDelete={state.remove}
        />
      </div>
      <p className="mt-8 text-sm text-muted-foreground">
        结果会按所选任务检查结构、材料引用与事实范围。
      </p>
      {isVideoAnalysisResult(job.result, job.input_kind) ? (
        <div className="mt-10">
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="secondary">
              {analysisReportStatusLabel(job.report?.status)}
            </Badge>
            {job.current_report_id ? (
              <>
                <Button asChild size="sm" variant="outline">
                  <AnalysisReportDownloadLink analysisId={job.id} format="md">
                    下载上一版 Markdown
                  </AnalysisReportDownloadLink>
                </Button>
                <Button asChild size="sm" variant="outline">
                  <AnalysisReportDownloadLink analysisId={job.id} format="docx">
                    下载上一版 DOCX
                  </AnalysisReportDownloadLink>
                </Button>
              </>
            ) : null}
          </div>
          {!onSelectTime ? (
            <p className="mt-3 text-sm text-muted-foreground">
              {playbackUnavailableReason}
            </p>
          ) : null}
          <AnalysisVideoResult
            onSelectTime={onSelectTime}
            reportMarkdown={job.report_markdown}
            result={job.result}
            skillId={job.skill_id}
          />
        </div>
      ) : null}
    </div>
  );
}
