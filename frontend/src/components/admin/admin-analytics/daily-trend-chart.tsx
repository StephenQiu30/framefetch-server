import dynamic from 'next/dynamic';
import { AnalyticsChartPanel } from './analytics-chart-panel';
import { DailyTrendDataTable } from './daily-trend-data-table';
import { ChartLoading, DeferredChart } from './deferred-chart';

const DailyTrendPlot = dynamic(
  () => import('./daily-trend-plot').then((module) => module.DailyTrendPlot),
  { loading: () => <ChartLoading trend /> },
);
type DailyPoint = API.DownloadAnalyticsResponse['daily'][number];

export function DailyTrendChart({ daily }: { daily: DailyPoint[] }) {
  const points = [...daily].sort((left, right) =>
    left.date.localeCompare(right.date),
  );
  return (
    <AnalyticsChartPanel
      id="daily-trend"
      title="每日下载趋势"
      detailsLabel="查看每日下载明细"
      details={<DailyTrendDataTable points={points} />}
    >
      <DeferredChart trend>
        <DailyTrendPlot points={points} />
      </DeferredChart>
    </AnalyticsChartPanel>
  );
}
