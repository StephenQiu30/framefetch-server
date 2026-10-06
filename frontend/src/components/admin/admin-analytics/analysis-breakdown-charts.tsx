'use client';

import type { ReactNode } from 'react';
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
import { ItemTitle } from '@/components/ui/item';

import { formatInteger, formatPercent } from './analytics-format';

const statusConfig = {
  succeeded: { color: 'var(--chart-1)', label: '成功' },
  active: { color: 'var(--chart-2)', label: '进行中' },
  failed: { color: 'var(--chart-3)', label: '失败' },
  cancelled: { color: 'var(--chart-4)', label: '取消' },
} satisfies ChartConfig;

const inputConfig = {
  video: { color: 'var(--chart-1)', label: '视频' },
  screenplay: { color: 'var(--chart-2)', label: '剧本' },
} satisfies ChartConfig;

type DistributionPoint = { category: string; value: number; fill: string };

export function AnalysisBreakdownCharts({
  inputs,
  summary,
}: Pick<API.AnalysisAnalyticsResponse, 'inputs' | 'summary'>) {
  const statuses = (
    ['succeeded', 'active', 'failed', 'cancelled'] as const
  ).map((category) => ({
    category,
    value: summary[category],
    fill: `var(--color-${category})`,
  }));
  const inputPoints = inputs.map((input) => ({
    category: input.input_kind,
    value: input.total,
    fill: `var(--color-${input.input_kind})`,
  }));

  return (
    <SplitLayout>
      <DistributionChart
        chartLabel="AI 分析执行状态环形图"
        config={statusConfig}
        data={statuses}
        id="analysis-status"
        summaryLabel="AI 分析状态精确数据"
        title="执行状态"
        total={summary.total}
      />
      <DistributionChart
        chartLabel="AI 分析输入类型环形图"
        config={inputConfig}
        data={inputPoints}
        id="analysis-input"
        summaryLabel="AI 分析输入类型精确数据"
        title="输入类型"
        total={summary.total}
      />
    </SplitLayout>
  );
}

function DistributionChart({
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
    <section aria-labelledby={`${id}-title`} className="min-w-0">
      <ItemTitle className="line-clamp-none">
        <h2 id={`${id}-title`}>{title}</h2>
      </ItemTitle>
      <div className="mt-6 grid items-center gap-6 sm:grid-cols-2">
        <ChartContainer
          aria-label={chartLabel}
          className="mx-auto aspect-square w-full max-w-xs"
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
              innerRadius="60%"
              isAnimationActive={false}
              nameKey="category"
              outerRadius="85%"
              stroke="var(--background)"
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
                        className="fill-foreground tabular-nums"
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
                        全部执行
                      </tspan>
                    </text>
                  );
                }}
              />
            </Pie>
            <ChartLegend
              content={
                <ChartLegendContent className="flex-wrap" nameKey="category" />
              }
            />
          </PieChart>
        </ChartContainer>
        <dl
          aria-label={summaryLabel}
          className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-4 tabular-nums"
        >
          {data.map((point) => (
            <DistributionEntry
              key={point.category}
              label={config[point.category]?.label ?? point.category}
              total={total}
              value={point.value}
            />
          ))}
        </dl>
      </div>
    </section>
  );
}

function DistributionEntry({
  label,
  total,
  value,
}: {
  label: ReactNode;
  total: number;
  value: number;
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd className="flex flex-wrap justify-end gap-x-2">
        <span>{formatInteger(value)}</span>
        <span>{formatPercent(total > 0 ? (value / total) * 100 : 0)}</span>
      </dd>
    </>
  );
}
