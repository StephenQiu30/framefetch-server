import dynamic from 'next/dynamic';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { SplitLayout } from '@/components/layout/split-layout';
import { Button } from '@/components/ui/button';
import { AnalysisKpis } from './analysis-kpis';
import { AnalyticsLoading } from './analytics-states';
import { ChartLoading, DeferredChart } from './deferred-chart';

const AnalysisTrendChart = dynamic(
  () =>
    import('./analysis-trend-chart').then(
      (module) => module.AnalysisTrendChart,
    ),
  { loading: () => <ChartLoading trend /> },
);
const AnalysisStatusChart = dynamic(
  () =>
    import('./analysis-breakdown-charts').then(
      (module) => module.AnalysisStatusChart,
    ),
  { loading: () => <ChartLoading /> },
);

const AnalysisInputChart = dynamic(
  () =>
    import('./analysis-breakdown-charts').then(
      (module) => module.AnalysisInputChart,
    ),
  { loading: () => <ChartLoading /> },
);

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
      {loading && !data ? (
        <AnalyticsLoading analysis label="正在加载 AI 分析统计" />
      ) : null}
      {data && data.summary.total === 0 ? (
        <PageEmptyNotice
          title="当前周期还没有 AI 分析记录"
          description="切换统计周期，或发起分析后再查看。"
        />
      ) : null}
      {data && data.summary.total > 0 ? (
        <>
          <AnalysisKpis summary={data.summary} />
          <DeferredChart trend>
            <AnalysisTrendChart daily={data.daily} />
          </DeferredChart>
          <SplitLayout className="gap-6 lg:gap-6">
            <DeferredChart>
              <AnalysisStatusChart summary={data.summary} />
            </DeferredChart>
            <DeferredChart>
              <AnalysisInputChart
                inputs={data.inputs}
                total={data.summary.total}
              />
            </DeferredChart>
          </SplitLayout>
        </>
      ) : null}
    </>
  );
}
