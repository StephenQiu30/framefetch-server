import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { SplitLayout } from '@/components/layout/split-layout';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';

import { AnalysisBreakdownCharts } from './analysis-breakdown-charts';
import { AnalysisKpis } from './analysis-kpis';
import { AnalysisTrendChart } from './analysis-trend-chart';

export function AnalysisAnalyticsContent({
  data,
  error,
  loading,
  onRetry,
}: {
  data: API.AnalysisAnalyticsResponse | null;
  error: string | null;
  loading: boolean;
  onRetry: () => void;
}) {
  return (
    <>
      {error && !data ? (
        <PageErrorNotice
          message={error}
          onRetry={onRetry}
          title="无法加载 AI 分析统计"
        />
      ) : null}
      {error && data ? (
        <FeedbackNotice
          action={<Button onClick={onRetry}>重新加载</Button>}
          description={error}
          title="AI 分析统计刷新失败"
          tone="error"
        />
      ) : null}
      {loading && !data ? <AnalysisAnalyticsLoading /> : null}
      {data && data.summary.total === 0 ? (
        <PageEmptyNotice
          title="当前周期还没有 AI 分析记录"
          description="切换统计周期，或发起分析后再查看。"
        />
      ) : null}
      {data && data.summary.total > 0 ? (
        <>
          <AnalysisTrendChart daily={data.daily} />
          <AnalysisKpis summary={data.summary} />
          <AnalysisBreakdownCharts
            inputs={data.inputs}
            summary={data.summary}
          />
        </>
      ) : null}
    </>
  );
}

function AnalysisAnalyticsLoading() {
  return (
    <div
      aria-label="正在加载 AI 分析统计"
      className="flex flex-col gap-8"
      role="status"
    >
      <span className="sr-only">正在加载 AI 分析统计</span>
      <div aria-hidden>
        <Skeleton className="h-7 w-32" />
        <Skeleton className="mt-2 h-6 w-44" />
        <Skeleton className="mt-6 aspect-video w-full md:aspect-[3/1]" />
      </div>
      <div aria-hidden className="grid grid-cols-2 gap-6 sm:grid-cols-4">
        {['total', 'rate', 'duration', 'active'].map((key) => (
          <Skeleton className="h-24 w-full" key={key} />
        ))}
      </div>
      <SplitLayout aria-hidden>
        {['status', 'input'].map((key) => (
          <div key={key}>
            <Skeleton className="h-7 w-24" />
            <div className="mt-6 grid items-center gap-6 sm:grid-cols-2">
              <Skeleton className="mx-auto aspect-square w-full max-w-xs rounded-full" />
              <div className="flex flex-col gap-4">
                {['first', 'second', 'third', 'fourth'].map((row) => (
                  <Skeleton className="h-5 w-full" key={row} />
                ))}
              </div>
            </div>
          </div>
        ))}
      </SplitLayout>
    </div>
  );
}
