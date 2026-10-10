import {
  formatBytes,
  formatDuration,
  formatInteger,
  formatPercent,
} from './analytics-format';
import { AnalyticsMetrics } from './analytics-metrics';

export function AnalyticsKpis({
  summary,
}: {
  summary: API.DownloadAnalyticsResponse['summary'];
}) {
  const metrics = [
    {
      label: '下载总数',
      value: formatInteger(summary.total),
      detail: `成功 ${formatInteger(summary.succeeded)} · 进行中 ${formatInteger(summary.active)}`,
    },
    {
      label: '成功率',
      value: formatPercent(summary.success_rate),
      detail: `失败 ${formatInteger(summary.failed)} · 取消 ${formatInteger(summary.cancelled)}`,
    },
    {
      label: '独立用户',
      value: formatInteger(summary.unique_users),
      detail: '周期内创建下载的用户',
    },
    {
      label: '下载数据量',
      value: formatBytes(summary.downloaded_bytes),
      detail: `平均视频时长 ${formatDuration(summary.average_duration_seconds)}`,
    },
  ];

  return <AnalyticsMetrics label="周期概览" metrics={metrics} />;
}
