'use client';

import { ChartBarIcon } from '@phosphor-icons/react';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import { ItemDescription, ItemTitle } from '@/components/ui/item';

import {
  ANALYTICS_CHART_COLOR,
  formatInteger,
  formatPercent,
} from './analytics-format';

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
  const hiddenCount = Math.max(0, sorted.length - visible.length);

  return (
    <div className="w-full">
      <ItemTitle className="line-clamp-none">
        <h2 className="flex items-center gap-2" id="source-breakdown-title">
          <ChartBarIcon aria-hidden />
          来源贡献
        </h2>
      </ItemTitle>
      <ItemDescription className="line-clamp-none mt-2 max-w-2xl">
        对比主要视频源的任务量与占比。
      </ItemDescription>
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
            className="mt-8 w-full md:aspect-[3/1]"
            config={sourceConfig}
            role="img"
          >
            <BarChart accessibilityLayer data={visible}>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis
                axisLine={false}
                dataKey="name"
                tickLine={false}
                tickFormatter={(value) => {
                  const label = String(value);
                  return label.length > 10 ? `${label.slice(0, 9)}…` : label;
                }}
              />
              <YAxis
                axisLine={false}
                allowDecimals={false}
                tickLine={false}
                width="auto"
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
                dataKey="total"
                fill="var(--color-total)"
                isAnimationActive={false}
                radius={[3, 3, 0, 0]}
              />
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
      <ItemDescription className="line-clamp-none mt-5 tabular-nums">
        {formatInteger(sorted.length)} 个来源
        {hiddenCount > 0
          ? ` · 其余 ${formatInteger(hiddenCount)} 个可在明细中查看`
          : ' · 已全部展示'}
      </ItemDescription>
    </div>
  );
}
