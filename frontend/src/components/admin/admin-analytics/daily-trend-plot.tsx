'use client';

import { Area, AreaChart, CartesianGrid, XAxis } from 'recharts';

import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';

import { formatShortDate } from './analytics-format';

type DailyPoint = API.DownloadAnalyticsResponse['daily'][number];

const trendConfig = {
  total: { color: 'var(--chart-2)', label: '全部任务' },
  succeeded: { color: 'var(--chart-1)', label: '成功任务' },
} satisfies ChartConfig;

export function DailyTrendPlot({ points }: { points: DailyPoint[] }) {
  return (
    <ChartContainer
      aria-describedby="daily-trend-description"
      aria-label="每日下载任务交互趋势图"
      className="w-full md:aspect-[3/1]"
      config={trendConfig}
      role="img"
    >
      <AreaChart accessibilityLayer data={points}>
        <defs>
          <linearGradient id="fillTotal" x1="0" y1="0" x2="0" y2="1">
            <stop
              offset="5%"
              stopColor="var(--color-total)"
              stopOpacity={0.8}
            />
            <stop
              offset="95%"
              stopColor="var(--color-total)"
              stopOpacity={0.1}
            />
          </linearGradient>
          <linearGradient id="fillSucceeded" x1="0" y1="0" x2="0" y2="1">
            <stop
              offset="5%"
              stopColor="var(--color-succeeded)"
              stopOpacity={0.8}
            />
            <stop
              offset="95%"
              stopColor="var(--color-succeeded)"
              stopOpacity={0.1}
            />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis
          axisLine={false}
          dataKey="date"
          tickFormatter={formatShortDate}
          tickLine={false}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(label) => formatShortDate(String(label))}
            />
          }
          cursor={false}
        />
        {/* Linear segments keep succeeded <= total between daily points;
            spline smoothing could draw impossible values. */}
        <Area
          dataKey="total"
          fill="url(#fillTotal)"
          isAnimationActive={false}
          stroke="var(--color-total)"
          strokeWidth={2}
          type="linear"
        />
        <Area
          dataKey="succeeded"
          fill="url(#fillSucceeded)"
          isAnimationActive={false}
          stroke="var(--color-succeeded)"
          strokeWidth={2}
          type="linear"
        />
        <ChartLegend content={<ChartLegendContent />} />
      </AreaChart>
    </ChartContainer>
  );
}
