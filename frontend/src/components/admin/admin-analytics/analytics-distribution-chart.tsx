'use client';
import type { ReactNode } from 'react';
import { Label, Pie, PieChart } from 'recharts';
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import {
  ANALYTICS_CHART_ASPECT,
  AnalyticsChartPanel,
} from './analytics-chart-panel';
import { formatInteger, formatPercent } from './analytics-format';

export const analyticsStatusConfig = {
  succeeded: { color: 'var(--chart-1)', label: '成功' },
  active: { color: 'var(--chart-2)', label: '进行中' },
  failed: { color: 'var(--chart-3)', label: '失败' },
  cancelled: { color: 'var(--chart-4)', label: '取消' },
} satisfies ChartConfig;

type DistributionPoint = { category: string; value: number; fill: string };

export function AnalyticsDistributionChart({
  chartLabel,
  config,
  data,
  id,
  summaryLabel,
  title,
  total,
}: {
  chartLabel: string;
  config: ChartConfig;
  data: DistributionPoint[];
  id: string;
  summaryLabel: string;
  title: string;
  total: number;
}) {
  return (
    <AnalyticsChartPanel
      id={id}
      title={title}
      detailsLabel={`查看${title}明细`}
      details={
        <dl
          aria-label={summaryLabel}
          className="grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-3 tabular-nums"
        >
          {data.map((point) => (
            <DistributionEntry
              key={point.category}
              color={config[point.category]?.color}
              label={config[point.category]?.label ?? point.category}
              total={total}
              value={point.value}
            />
          ))}
        </dl>
      }
    >
      <ChartContainer
        aria-label={chartLabel}
        className={ANALYTICS_CHART_ASPECT}
        config={config}
        role="img"
      >
        <PieChart accessibilityLayer>
          <ChartTooltip
            content={<ChartTooltipContent hideLabel nameKey="category" />}
            cursor={false}
          />
          <Pie
            data={data}
            dataKey="value"
            innerRadius="72%"
            isAnimationActive={false}
            nameKey="category"
            outerRadius="95%"
            stroke="var(--card)"
            strokeWidth={3}
          >
            <Label
              content={({ viewBox }) => {
                if (!viewBox || !('cx' in viewBox) || !('cy' in viewBox))
                  return null;
                return (
                  <text
                    dominantBaseline="middle"
                    textAnchor="middle"
                    x={viewBox.cx}
                    y={viewBox.cy}
                  >
                    <tspan
                      className="fill-foreground text-3xl font-medium tabular-nums"
                      x={viewBox.cx}
                      y={viewBox.cy}
                      dy="-0.25em"
                    >
                      {formatInteger(total)}
                    </tspan>
                    <tspan
                      className="fill-muted-foreground"
                      x={viewBox.cx}
                      y={viewBox.cy}
                      dy="1.75em"
                    >
                      合计
                    </tspan>
                  </text>
                );
              }}
            />
          </Pie>
          <ChartLegend
            itemSorter={null}
            content={
              <ChartLegendContent className="flex-wrap" nameKey="category" />
            }
          />
        </PieChart>
      </ChartContainer>
    </AnalyticsChartPanel>
  );
}
function DistributionEntry({
  color,
  label,
  total,
  value,
}: {
  color?: string;
  label: ReactNode;
  total: number;
  value: number;
}) {
  return (
    <>
      <dt className="flex items-center gap-2">
        <span
          aria-hidden
          className="size-2 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
        />
        {label}
      </dt>
      <dd className="flex flex-wrap justify-end gap-x-2">
        <span>{formatInteger(value)}</span>
        <span className="text-muted-foreground">
          {formatPercent(total > 0 ? (value / total) * 100 : 0)}
        </span>
      </dd>
    </>
  );
}
