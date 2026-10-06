'use client';

import { CheckCircleIcon } from '@phosphor-icons/react';
import { Label, Pie, PieChart } from 'recharts';

import { SplitLayout } from '@/components/layout/split-layout';
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from '@/components/ui/item';

import { formatInteger, formatPercent } from './analytics-format';

enum DownloadAnalyticsStatusCode {
  Succeeded = 'succeeded',
  Active = 'active',
  Failed = 'failed',
  Cancelled = 'cancelled',
}

const statusConfig = {
  [DownloadAnalyticsStatusCode.Succeeded]: {
    color: 'var(--chart-1)',
    label: '成功',
  },
  [DownloadAnalyticsStatusCode.Active]: {
    color: 'var(--chart-2)',
    label: '进行中',
  },
  [DownloadAnalyticsStatusCode.Failed]: {
    color: 'var(--chart-3)',
    label: '失败',
  },
  [DownloadAnalyticsStatusCode.Cancelled]: {
    color: 'var(--chart-4)',
    label: '取消',
  },
} satisfies ChartConfig;

export function StatusDistributionChart({
  summary,
}: {
  summary: API.DownloadAnalyticsResponse['summary'];
}) {
  const data: Array<{
    fill: string;
    status: DownloadAnalyticsStatusCode;
    value: number;
  }> = [
    {
      fill: `var(--color-${DownloadAnalyticsStatusCode.Succeeded})`,
      status: DownloadAnalyticsStatusCode.Succeeded,
      value: summary.succeeded,
    },
    {
      fill: `var(--color-${DownloadAnalyticsStatusCode.Active})`,
      status: DownloadAnalyticsStatusCode.Active,
      value: summary.active,
    },
    {
      fill: `var(--color-${DownloadAnalyticsStatusCode.Failed})`,
      status: DownloadAnalyticsStatusCode.Failed,
      value: summary.failed,
    },
    {
      fill: `var(--color-${DownloadAnalyticsStatusCode.Cancelled})`,
      status: DownloadAnalyticsStatusCode.Cancelled,
      value: summary.cancelled,
    },
  ];

  return (
    <div className="w-full">
      <ItemTitle className="line-clamp-none">
        <h2 className="flex items-center gap-2" id="status-distribution-title">
          <CheckCircleIcon aria-hidden />
          任务状态
        </h2>
      </ItemTitle>
      <ItemDescription className="line-clamp-none mt-2 max-w-2xl">
        当前周期的完成结构与异常占比。
      </ItemDescription>
      <SplitLayout className="mt-6 items-center" columns="sidebar-start">
        <ChartContainer
          aria-label="下载任务状态环形图"
          className="mx-auto w-full max-w-xs aspect-square lg:mx-0"
          config={statusConfig}
          role="img"
        >
          <PieChart accessibilityLayer>
            <ChartTooltip
              content={<ChartTooltipContent hideLabel nameKey="status" />}
              cursor={false}
            />
            <Pie
              data={data}
              dataKey="value"
              innerRadius="60%"
              isAnimationActive={false}
              nameKey="status"
              outerRadius="85%"
              stroke="var(--background)"
              strokeWidth={3}
            >
              <Label
                content={({ viewBox }) => {
                  if (!viewBox || !('cx' in viewBox) || !('cy' in viewBox)) {
                    return null;
                  }
                  return (
                    <text
                      dominantBaseline="middle"
                      textAnchor="middle"
                      x={viewBox.cx}
                      y={viewBox.cy}
                    >
                      <tspan
                        className="fill-foreground tabular-nums"
                        x={viewBox.cx}
                        y={viewBox.cy}
                        dy="-0.25em"
                      >
                        {formatInteger(summary.total)}
                      </tspan>
                      <tspan
                        className="fill-muted-foreground"
                        x={viewBox.cx}
                        dy="1.75em"
                      >
                        全部任务
                      </tspan>
                    </text>
                  );
                }}
              />
            </Pie>
            <ChartLegend content={<ChartLegendContent nameKey="status" />} />
          </PieChart>
        </ChartContainer>
        <ItemGroup className="grid grid-cols-2 gap-x-8 gap-y-8 sm:grid-cols-4 sm:gap-x-10">
          {data.map((item) => (
            <Item
              className="min-w-0 items-start"
              key={item.status}
              role="listitem"
            >
              <ItemContent className="gap-0">
                <ItemTitle className="flex items-center gap-2">
                  {statusConfig[item.status].label}
                </ItemTitle>
                <ItemActions className="mt-2 items-baseline gap-2 tabular-nums">
                  <span>{formatInteger(item.value)}</span>
                  <span>
                    {formatPercent(
                      summary.total > 0
                        ? (item.value / summary.total) * 100
                        : 0,
                    )}
                  </span>
                </ItemActions>
              </ItemContent>
            </Item>
          ))}
        </ItemGroup>
      </SplitLayout>
    </div>
  );
}
