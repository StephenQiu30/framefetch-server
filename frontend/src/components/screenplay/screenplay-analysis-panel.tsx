'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import AnalysisConfigurator from '@/components/analysis/analysis-configurator';
import { AnalysisStatusCode } from '@/components/analysis/analysis-panel-model';
import { isVideoAnalysisResult } from '@/components/analysis/analysis-video-result';
import { useAnalysisJob } from '@/components/analysis/use-analysis-job';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { ScreenplayAnalysisJobState } from '@/components/screenplay/screenplay-analysis-job-state';
import { ScreenplayCompletedAnalysis } from '@/components/screenplay/screenplay-completed-analysis';
import { Button } from '@/components/ui/button';
import { ItemDescription, ItemTitle } from '@/components/ui/item';
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
  const router = useRouter();
  const state = useAnalysisJob(
    documentId,
    pollIntervalMs,
    'screenplay',
    analysisId,
  );
  const [newAnalysisForJobId, setNewAnalysisForJobId] = useState<string | null>(
    null,
  );
  function beginNewAnalysis() {
    if (analysisId) {
      router.push(
        `/documents/detail?documentId=${encodeURIComponent(documentId)}`,
      );
      return;
    }
    setNewAnalysisForJobId(state.job?.id ?? null);
  }

  if (state.loading && state.action !== 'start') {
    return (
      <div role="status">
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
  const succeeded =
    state.job?.status === AnalysisStatusCode.Succeeded &&
    state.job.result &&
    !isVideoAnalysisResult(state.job.result, state.job.input_kind);

  return (
    <div className="mt-14 sm:mt-16">
      {succeeded && state.job ? (
        <>
          {state.error ? (
            <FeedbackNotice
              action={
                state.errorKind === 'sync' ? (
                  <Button
                    variant="outline"
                    size="default"
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
          <ScreenplayCompletedAnalysis
            action={state.action}
            job={state.job}
            onDelete={state.remove}
            onRetry={state.retry}
            onNewAnalysis={beginNewAnalysis}
          />
        </>
      ) : (
        <>
          <div className="max-w-3xl">
            <ItemTitle className="line-clamp-none">
              <h2 id="screenplay-analysis-title">文档分析</h2>
            </ItemTitle>
            <ItemDescription className="line-clamp-none mt-4 max-w-2xl">
              审阅故事结构、人物和对白，或整理已有文章、公众号和小红书文档。任务使用这份文档，原文保留。
            </ItemDescription>
          </div>
          {state.error ? (
            <FeedbackNotice
              action={
                state.errorKind === 'sync' ? (
                  <Button
                    variant="outline"
                    size="default"
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
          {!state.job && !analysisId ? (
            <AnalysisConfigurator
              inputId={documentId}
              busy={state.action === 'start'}
              inputKind="screenplay"
              onStart={state.start}
            />
          ) : state.job ? (
            <ScreenplayAnalysisJobState
              job={state.job}
              state={state}
              onNewAnalysis={beginNewAnalysis}
            />
          ) : null}
        </>
      )}
      {state.job && newAnalysisForJobId === state.job.id ? (
        <div className="mt-10 max-w-3xl" id="new-screenplay-analysis">
          <ItemTitle className="line-clamp-none">
            <h3 className="mb-4">使用最新 Skill 新建任务</h3>
          </ItemTitle>
          <AnalysisConfigurator
            inputId={documentId}
            busy={state.action === 'start'}
            inputKind="screenplay"
            onStart={state.start}
          />
        </div>
      ) : null}
    </div>
  );
}
