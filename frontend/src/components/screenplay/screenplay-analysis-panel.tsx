'use client';

import Link from 'next/link';
import { AnalysisStatusCode } from '@/components/analysis/analysis-panel-model';
import { isVideoAnalysisResult } from '@/components/analysis/analysis-video-result';
import { useAnalysisJob } from '@/components/analysis/use-analysis-job';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { ScreenplayAnalysisJobState } from '@/components/screenplay/screenplay-analysis-job-state';
import { ScreenplayCompletedAnalysis } from '@/components/screenplay/screenplay-completed-analysis';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';

export default function ScreenplayAnalysisPanel({
  documentId,
  analysisId,
  pollIntervalMs = 1500,
}: {
  documentId: string;
  analysisId?: string;
  pollIntervalMs?: number;
}) {
  const state = useAnalysisJob(
    documentId,
    pollIntervalMs,
    'screenplay',
    analysisId,
  );
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
  const succeeded =
    state.job?.status === AnalysisStatusCode.Succeeded &&
    state.job.result &&
    !isVideoAnalysisResult(state.job.result);
  return (
    <section className="grid gap-6 py-12 sm:py-16" aria-label="历史剧本分析">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold tracking-tight">历史剧本分析</h2>
        <Button asChild variant="outline">
          <Link href="/content">到内容工作台新建任务</Link>
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        保留原有剧本分析与报告。新任务请在内容工作台导入或选择剧本文档，核对版本后开始分析。
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
      {succeeded && state.job ? (
        <ScreenplayCompletedAnalysis
          action={state.action}
          job={state.job}
          onDelete={state.remove}
        />
      ) : state.job ? (
        <ScreenplayAnalysisJobState job={state.job} state={state} />
      ) : (
        <PageEmptyNotice
          compact
          title="暂无旧剧本分析"
          description="新任务在内容工作台中开始。"
        />
      )}
    </section>
  );
}
