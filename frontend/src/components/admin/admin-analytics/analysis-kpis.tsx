import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from '@/components/ui/item';

import {
  formatDuration,
  formatInteger,
  formatPercent,
} from './analytics-format';

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

  return (
    <ItemGroup className="grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4">
      {metrics.map((metric) => (
        <Item
          className="min-w-0 items-start"
          key={metric.label}
          role="listitem"
        >
          <ItemContent className="gap-0">
            <ItemTitle>{metric.label}</ItemTitle>
            <p className="mt-3 text-2xl font-medium leading-none tracking-tight tabular-nums sm:text-3xl">
              {metric.value}
            </p>
            <ItemDescription className="mt-3 line-clamp-none">
              {metric.detail}
            </ItemDescription>
          </ItemContent>
        </Item>
      ))}
    </ItemGroup>
  );
}
