import {
  formatDuration,
  formatInteger,
  formatPercent,
} from './analytics-format';
import { AnalyticsMetrics } from './analytics-metrics';

export function AnalysisKpis({
  summary,
}: {
  summary: API.AnalysisAnalyticsResponse['summary'];
}) {
  const decided = summary.succeeded + summary.failed;
  const metrics = [
    {
      label: '执行次数',
      value: formatInteger(summary.total),
      detail: `成功 ${formatInteger(summary.succeeded)} · 失败 ${formatInteger(summary.failed)}`,
    },
    {
      label: '成功率',
      value:
        decided > 0 ? formatPercent((summary.succeeded / decided) * 100) : '—',
      detail: '成功 ÷（成功 + 失败）',
    },
    {
      label: '平均完成耗时',
      value:
        summary.average_duration_seconds === null
          ? '—'
          : formatDuration(summary.average_duration_seconds),
      detail:
        summary.completed_duration_count > 0
          ? `${formatInteger(summary.completed_duration_count)} 次有效完成记录`
          : '暂无完成耗时',
    },
    {
      label: '进行中',
      value: formatInteger(summary.active),
      detail: '等待与执行中的记录',
    },
  ];

  return <AnalyticsMetrics label="AI 分析周期概览" metrics={metrics} />;
}
