'use client';

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
} from 'recharts';
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import { ANALYTICS_TREND_ASPECT } from './analytics-chart-panel';
import { formatShortDate } from './analytics-format';

type DailyPoint = { date: string; total: number; succeeded: number };

export function DailyTrendPlot({
  points,
  kind = 'downloads',
}: {
  points: DailyPoint[];
  kind?: 'downloads' | 'analysis';
}) {
  const trendConfig = {
    total: {
      color: 'var(--chart-2)',
      label: kind === 'downloads' ? '全部任务' : '全部执行',
    },
    succeeded: {
      color: 'var(--chart-1)',
      label: kind === 'downloads' ? '成功任务' : '成功执行',
    },
  } satisfies ChartConfig;
  return (
    <ChartContainer
      aria-label={
        kind === 'downloads'
          ? '每日下载任务交互趋势图'
          : '每日 AI 分析执行趋势图'
      }
      className={ANALYTICS_TREND_ASPECT}
      config={trendConfig}
      role="img"
    >
      <ComposedChart
        accessibilityLayer
        data={points}
        margin={{ top: 12, right: 12, left: 0, bottom: 0 }}
      >
        <CartesianGrid vertical={false} />
        <XAxis
          tick={{ fill: 'var(--muted-foreground)' }}
          axisLine={false}
          dataKey="date"
          tickFormatter={formatShortDate}
          tickLine={false}
          minTickGap={32}
        />
        <YAxis
          tick={{ fill: 'var(--muted-foreground)' }}
          axisLine={false}
          allowDecimals={false}
          tickLine={false}
          width="auto"
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(label) => formatShortDate(String(label))}
            />
          }
          cursor={{ fill: 'var(--muted)' }}
        />
        <Bar
          maxBarSize={24}
          dataKey="total"
          fill="var(--color-total)"
          fillOpacity={0.5}
          isAnimationActive={false}
          radius={[3, 3, 0, 0]}
        />
        <Line
          dataKey="succeeded"
          isAnimationActive={false}
          stroke="var(--color-succeeded)"
          strokeWidth={2}
          type="linear"
          dot={points.length === 1}
        />
        <ChartLegend itemSorter={null} content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  );
}
