'use client';
import {
  AnalyticsDistributionChart,
  analyticsStatusConfig,
} from './analytics-distribution-chart';

export function StatusDistributionChart({
  summary,
}: {
  summary: API.DownloadAnalyticsResponse['summary'];
}) {
  const data = (['succeeded', 'active', 'failed', 'cancelled'] as const).map(
    (category) => ({
      category,
      value: summary[category],
      fill: `var(--color-${category})`,
    }),
  );
  return (
    <AnalyticsDistributionChart
      chartLabel="下载任务状态环形图"
      config={analyticsStatusConfig}
      data={data}
      id="status-distribution"
      summaryLabel="下载任务状态精确数据"
      title="任务状态"
      total={summary.total}
    />
  );
}
