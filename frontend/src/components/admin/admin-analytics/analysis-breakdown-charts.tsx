'use client';
import type { ChartConfig } from '@/components/ui/chart';
import {
  AnalyticsDistributionChart,
  analyticsStatusConfig,
} from './analytics-distribution-chart';

const inputConfig = {
  video: { color: 'var(--chart-1)', label: '视频' },
  screenplay: { color: 'var(--chart-2)', label: '剧本' },
} satisfies ChartConfig;

export function AnalysisStatusChart({
  summary,
}: Pick<API.AnalysisAnalyticsResponse, 'summary'>) {
  const statuses = (
    ['succeeded', 'active', 'failed', 'cancelled'] as const
  ).map((category) => ({
    category,
    value: summary[category],
    fill: `var(--color-${category})`,
  }));
  return (
    <AnalyticsDistributionChart
      chartLabel="AI 分析执行状态环形图"
      config={analyticsStatusConfig}
      data={statuses}
      id="analysis-status"
      summaryLabel="AI 分析状态精确数据"
      title="执行状态"
      total={summary.total}
    />
  );
}

export function AnalysisInputChart({
  inputs,
  total,
}: Pick<API.AnalysisAnalyticsResponse, 'inputs'> & { total: number }) {
  const data = inputs.map((input) => ({
    category: input.input_kind,
    value: input.total,
    fill: `var(--color-${input.input_kind})`,
  }));
  return (
    <AnalyticsDistributionChart
      chartLabel="AI 分析输入类型环形图"
      config={inputConfig}
      data={data}
      id="analysis-input"
      summaryLabel="AI 分析输入类型精确数据"
      title="输入类型"
      total={total}
    />
  );
}
