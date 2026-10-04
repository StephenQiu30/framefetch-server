'use client';

import { DownloadSimple } from '@phosphor-icons/react';
import Link from 'next/link';
import AnalysisDeleteDialog from '@/components/analysis/analysis-delete-dialog';
import {
  isActiveAnalysisStatus,
  stageLabels,
  statusLabels,
} from '@/components/analysis/analysis-panel-model';
import AnalysisReportDownloadLink from '@/components/analysis/analysis-report-download-link';
import AnalysisStorageNotice from '@/components/analysis/analysis-storage-notice';
import AnalysisVideoResult, {
  isVideoAnalysisResult,
} from '@/components/analysis/analysis-video-result';
import { useAnalysisJob } from '@/components/analysis/use-analysis-job';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Spinner } from '@/components/ui/spinner';
import { localizedErrorMessage } from '@/lib/error-messages';

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
  if (state.loading)
    return (
      <div className="py-12" role="status">
        <Spinner aria-hidden className="mr-2 inline" />
        正在读取分析记录
      </div>
    );
  if (state.errorKind === 'load' && state.error)
    return (
      <PageErrorNotice
        compact
        title="暂时无法读取分析记录"
        message={state.error}
        onRetry={() => void state.retryPoll()}
      />
    );
  const job = state.job;
  const active = Boolean(job && isActiveAnalysisStatus(job.status));
  return (
    <section
      className="grid min-w-0 gap-6 py-12 sm:py-16"
      aria-label="历史视频分析"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold tracking-tight">
          {job && isVideoAnalysisResult(job.result)
            ? job.result.title
            : '历史视频分析'}
        </h2>
        <Button asChild variant="outline">
          <Link href="/content">到内容工作台新建任务</Link>
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        此处保留已有分析和报告。新任务请在内容工作台选择已完成的视频、核对材料并确认处理范围。
      </p>
      {state.error ? (
        <FeedbackNotice
          title="操作未完成"
          description={state.error}
          tone="error"
          action={
            <Button variant="outline" onClick={() => void state.retryPoll()}>
              恢复同步
            </Button>
          }
        />
      ) : null}
      {!job ? (
        <PageEmptyNotice
          compact
          title="暂无旧分析记录"
          description="打开内容工作台，选择本视频并确认后开始影视分析。"
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="secondary">
              {job.status === 'succeeded' ? '已完成' : statusLabels[job.status]}
            </Badge>
            <span className="text-sm text-muted-foreground">
              第 {job.run_no} 次执行
              {active
                ? ` · ${job.stage ? stageLabels[job.stage] : '等待调度'}`
                : ''}
            </span>
            {active ? (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="outline" disabled={Boolean(state.action)}>
                    取消分析
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent size="sm">
                  <AlertDialogHeader>
                    <AlertDialogTitle>取消当前分析任务？</AlertDialogTitle>
                    <AlertDialogDescription>
                      停止这条旧分析任务，保留已有报告。新任务在内容工作台创建。
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>继续分析</AlertDialogCancel>
                    <AlertDialogAction
                      variant="destructive"
                      disabled={Boolean(state.action)}
                      onClick={() => void state.cancel()}
                    >
                      确认取消分析
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            ) : null}
            <AnalysisDeleteDialog
              disabled={Boolean(state.action)}
              busy={state.action === 'delete'}
              onDelete={state.remove}
            />
            {job.report?.status === 'available'
              ? job.report.artifacts.map((artifact) => (
                  <Button key={artifact.format} asChild variant="outline">
                    <AnalysisReportDownloadLink
                      analysisId={job.id}
                      format={artifact.format === 'markdown' ? 'md' : 'docx'}
                      download={`analysis-report-${job.id}.${artifact.format === 'markdown' ? 'md' : 'docx'}`}
                    >
                      <DownloadSimple aria-hidden data-icon="inline-start" />
                      导出{' '}
                      {artifact.format === 'markdown' ? 'Markdown' : 'DOCX'}
                    </AnalysisReportDownloadLink>
                  </Button>
                ))
              : null}
          </div>
          {active ? (
            <Progress
              value={job.progress}
              aria-label={`分析进度 ${job.progress}%`}
            />
          ) : null}
          <AnalysisStorageNotice />
          {job.status === 'failed' ? (
            <PageErrorNotice
              compact
              title="分析失败"
              message={
                localizedErrorMessage(job.error_code) ??
                '这条历史分析未能完成。新任务请在内容工作台创建。'
              }
            />
          ) : null}
          {job.result &&
          (job.report?.status !== 'available' ||
            job.report.artifacts.length === 0) ? (
            <FeedbackNotice
              title="报告已清理或暂时不可用"
              description="分析结果仍可查看，但报告文件已被清理或暂时不可读取。新任务请在内容工作台创建。"
              tone="info"
            />
          ) : null}
          {isVideoAnalysisResult(job.result) ? (
            <>
              {!onSelectTime ? (
                <p className="text-sm text-muted-foreground">
                  {playbackUnavailableReason}
                </p>
              ) : null}
              <AnalysisVideoResult
                onSelectTime={onSelectTime}
                reportMarkdown={job.report_markdown}
                result={job.result}
                skillId={job.skill_id}
              />
            </>
          ) : null}
        </>
      )}
    </section>
  );
}
