'use client';

import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  ANALYTICS_CHART_ASPECT,
  AnalyticsChartPanel,
} from './analytics-chart-panel';
import {
  ANALYTICS_CHART_COLOR,
  formatPercent,
  formatShortDate,
} from './analytics-format';

type DailyPoint = API.DownloadAnalyticsResponse['daily'][number];
const completionConfig = {
  rate: { color: ANALYTICS_CHART_COLOR, label: '成功率' },
} satisfies ChartConfig;

export function CompletionRateChart({ daily }: { daily: DailyPoint[] }) {
  const points = [...daily]
    .sort((left, right) => left.date.localeCompare(right.date))
    .map((point) => ({
      date: point.date,
      rate: point.total > 0 ? (point.succeeded / point.total) * 100 : null,
    }));
  const latest = points.findLast((point) => point.rate !== null);
  return (
    <AnalyticsChartPanel
      id="completion-rate"
      title="完成率走势"
      detailsLabel="查看每日成功率明细"
      details={
        <Table className="table-borderless">
          <TableCaption className="sr-only">
            每日下载成功率精确数据
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">日期</TableHead>
              <TableHead className="text-right" scope="col">
                成功率
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {points.map((point) => (
              <TableRow key={point.date}>
                <TableHead scope="row">{point.date}</TableHead>
                <TableCell className="text-right tabular-nums">
                  {point.rate === null
                    ? '—（无任务）'
                    : formatPercent(point.rate)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    >
      <ChartContainer
        aria-label="每日下载成功率面积图"
        className={ANALYTICS_CHART_ASPECT}
        config={completionConfig}
        role="img"
      >
        <AreaChart
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
            domain={[0, 100]}
            ticks={[0, 50, 100]}
            tickFormatter={(value) => `${value}%`}
            tickLine={false}
            width="auto"
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                formatter={(value) => (
                  <div className="flex items-center gap-4">
                    <span>成功率</span>
                    <span className="tabular-nums">
                      {formatPercent(Number(value))}
                    </span>
                  </div>
                )}
                labelFormatter={(label) => formatShortDate(String(label))}
              />
            }
            cursor={false}
          />
          <Area
            connectNulls={false}
            dataKey="rate"
            dot={{ r: 3 }}
            fill="var(--color-rate)"
            fillOpacity={0.12}
            isAnimationActive={false}
            stroke="var(--color-rate)"
            strokeWidth={2}
            type="linear"
          />
        </AreaChart>
      </ChartContainer>
      <p className="sr-only">
        {latest?.rate != null
          ? `最近有任务日 ${formatShortDate(latest.date)} · ${formatPercent(latest.rate)}`
          : '暂无成功率样本'}
      </p>
    </AnalyticsChartPanel>
  );
}
