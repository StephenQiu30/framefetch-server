'use client';

import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  XAxis,
  YAxis,
} from 'recharts';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';

import {
  ANALYTICS_CHART_ASPECT,
  AnalyticsChartPanel,
} from './analytics-chart-panel';
import {
  ANALYTICS_CHART_COLOR,
  formatInteger,
  formatPercent,
} from './analytics-format';
import { SourcePerformanceDetails } from './source-performance-details';

type Source = API.DownloadAnalyticsResponse['sources'][number];

const sourceConfig = {
  total: { color: ANALYTICS_CHART_COLOR, label: '任务数' },
} satisfies ChartConfig;

export function SourceBreakdown({
  sources,
  total,
}: {
  sources: Source[];
  total: number;
}) {
  const sorted = [...sources].sort((left, right) => right.total - left.total);
  const visible = sorted.slice(0, 5).map((source) => {
    const share = total > 0 ? (source.total / total) * 100 : 0;
    return {
      ...source,
      name: source.source_name || source.source_key,
      share,
    };
  });

  return (
    <AnalyticsChartPanel
      id="source-breakdown"
      title="来源贡献"
      detailsLabel={`查看 ${formatInteger(sorted.length)} 个来源`}
      details={
        sorted.length > 0 ? (
          <SourcePerformanceDetails sources={sorted} />
        ) : undefined
      }
    >
      {sorted.length === 0 ? (
        <PageEmptyNotice
          compact
          title="暂无来源数据"
          description="有下载记录后，可在这里比较各来源的任务量。"
        />
      ) : (
        <>
          <ChartContainer
            aria-describedby="source-breakdown-description"
            aria-label="视频来源任务贡献条形图"
            className={ANALYTICS_CHART_ASPECT}
            config={sourceConfig}
            role="img"
          >
            <BarChart
              accessibilityLayer
              data={visible}
              layout="vertical"
              margin={{ right: 32, top: 12, bottom: 0, left: 0 }}
            >
              <CartesianGrid horizontal={false} />
              <XAxis
                tick={{ fill: 'var(--muted-foreground)' }}
                axisLine={false}
                allowDecimals={false}
                tickLine={false}
                type="number"
              />
              <YAxis
                tick={{ fill: 'var(--muted-foreground)' }}
                axisLine={false}
                dataKey="name"
                tickLine={false}
                type="category"
                width="auto"
                tickFormatter={(value) => {
                  const label = String(value);
                  return label.length > 14 ? `${label.slice(0, 13)}…` : label;
                }}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    formatter={(value, _name, item) => (
                      <div className="grid min-w-36 grid-cols-[1fr_auto] items-center gap-x-5 gap-y-1">
                        <span className="col-span-2">
                          {String(item.payload.name)}
                        </span>
                        <span>任务数</span>
                        <span className="text-right tabular-nums">
                          {formatInteger(Number(value))}
                        </span>
                        <span>占比</span>
                        <span className="text-right tabular-nums">
                          {formatPercent(Number(item.payload.share))}
                        </span>
                      </div>
                    )}
                    hideIndicator
                    hideLabel
                  />
                }
                cursor={{ fill: 'var(--muted)', opacity: 0.7 }}
              />
              <Bar
                maxBarSize={24}
                dataKey="total"
                fill="var(--color-total)"
                isAnimationActive={false}
                radius={[0, 3, 3, 0]}
              >
                <LabelList
                  dataKey="total"
                  position="right"
                  fill="var(--muted-foreground)"
                  formatter={(value) => formatInteger(Number(value))}
                />
              </Bar>
            </BarChart>
          </ChartContainer>
          <p className="sr-only" id="source-breakdown-description">
            条形图按任务数从高到低展示最多五个视频来源，精确数据见下方来源明细。
          </p>
          <ol className="sr-only">
            {visible.map((source) => (
              <li key={source.source_key}>
                {source.name}：{formatPercent(source.share)}
              </li>
            ))}
          </ol>
        </>
      )}
    </AnalyticsChartPanel>
  );
}
