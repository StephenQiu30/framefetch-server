import { Robot } from '@phosphor-icons/react';
import AnalysisDeleteDialog from '@/components/analysis/analysis-delete-dialog';
import {
  AnalysisStatusCode,
  isActiveAnalysisStatus,
  screenplayAnalysisErrorMessage,
  stageLabels,
  statusLabels,
} from '@/components/analysis/analysis-panel-model';
import AnalysisStorageNotice from '@/components/analysis/analysis-storage-notice';
import { isVideoAnalysisResult } from '@/components/analysis/analysis-video-result';
import type { useAnalysisJob } from '@/components/analysis/use-analysis-job';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { ScreenplayResultView } from '@/components/screenplay/screenplay-result-view';
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
import { ItemDescription } from '@/components/ui/item';
import { Progress } from '@/components/ui/progress';
import { Spinner } from '@/components/ui/spinner';
import { localizedErrorMessage } from '@/lib/error-messages';
import { TaskSocketStatusCode } from '@/lib/task-socket';

export function ScreenplayAnalysisJobState({
  job,
  state,
  onNewAnalysis,
}: {
  job: API.AnalysisResponse;
  state: ReturnType<typeof useAnalysisJob>;
  onNewAnalysis: () => void;
}) {
  const cancellable = isActiveAnalysisStatus(job.status);
  return (
    <div className="mt-10 w-full">
      <div className="flex justify-between gap-4">
        <span>{statusLabels[job.status]}</span>
        <span className="tabular-nums">{job.progress}%</span>
      </div>
      <Progress
        aria-label={`剧本任务进度 ${job.progress}%`}
        className="mt-3"
        value={job.progress}
      />
      <ItemDescription className="line-clamp-none mt-3">
        第 {job.run_no} 次执行 · 当前阶段：
        {job.stage ? stageLabels[job.stage] : '等待调度'} ·{' '}
        {job.attempt > 0
          ? `本次第 ${job.attempt} 个技术尝试`
          : '尚未开始技术尝试'}
      </ItemDescription>
      <div className="mt-2">
        <AnalysisStorageNotice />
      </div>
      {job.status === AnalysisStatusCode.Failed ? (
        <PageErrorNotice
          className="mt-6"
          compact
          message={
            screenplayAnalysisErrorMessage(job.error_code) ??
            localizedErrorMessage(job.error_code) ??
            '剧本分析或改写未能完成，请稍后重试。'
          }
          title="剧本任务失败"
        />
      ) : null}
      <ItemDescription aria-live="polite" className="line-clamp-none mt-2">
        {state.socketStatus === TaskSocketStatusCode.Connected
          ? '实时状态已连接'
          : state.socketStatus === TaskSocketStatusCode.Degraded
            ? '实时连接中断，正在低频恢复'
            : '正在连接实时状态'}
      </ItemDescription>
      <div className="mt-7 flex flex-wrap gap-3">
        {cancellable ? <CancelControl state={state} /> : null}
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
            {state.action === 'retry' ? '正在重试' : '重试任务'}
          </Button>
        ) : null}
        {job.status === AnalysisStatusCode.Failed ||
        job.status === AnalysisStatusCode.Cancelled ? (
          <Button
            disabled={Boolean(state.action)}
            onClick={onNewAnalysis}
            variant="outline"
          >
            使用最新 Skill 新建任务
          </Button>
        ) : null}
        <AnalysisDeleteDialog
          disabled={Boolean(state.action)}
          busy={state.action === 'delete'}
          onDelete={state.remove}
        />
      </div>
      {job.result && !isVideoAnalysisResult(job.result, job.input_kind) ? (
        <div className="mt-10">
          <Badge variant="secondary">上一版本结果</Badge>
          <ScreenplayResultView
            reportMarkdown={job.report_markdown}
            result={job.result}
          />
        </div>
      ) : null}
    </div>
  );
}

function CancelControl({
  state,
}: {
  state: ReturnType<typeof useAnalysisJob>;
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button disabled={Boolean(state.action)} variant="outline">
          {state.action === 'cancel' ? (
            <Spinner aria-hidden data-icon="inline-start" />
          ) : null}
          取消任务
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent size="sm">
        <AlertDialogHeader>
          <AlertDialogMedia>
            <Robot aria-hidden />
          </AlertDialogMedia>
          <AlertDialogTitle>取消当前剧本任务？</AlertDialogTitle>
          <AlertDialogDescription>
            确认后将停止当前分析或改写。规范化剧本文档不会被删除。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>继续执行</AlertDialogCancel>
          <AlertDialogAction
            disabled={Boolean(state.action)}
            variant="destructive"
            onClick={state.cancel}
          >
            确认取消任务
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
