'use client';

import { TrendUpIcon } from '@phosphor-icons/react';
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
      rate: point.total > 0 ? (point.succeeded / point.total) * 100 : 0,
    }));
  const latest = points.at(-1)?.rate ?? 0;

  return (
    <div className="w-full">
      <h2
        className="flex items-center gap-2 text-xl font-medium tracking-tight"
        id="completion-rate-title"
      >
        <TrendUpIcon aria-hidden className="size-4 text-muted-foreground" />
        完成率走势
      </h2>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
        按天观察成功完成任务的比例变化。
      </p>
      <ChartContainer
        aria-label="每日下载成功率面积图"
        className="mt-8 w-full md:aspect-[3/1]"
        config={completionConfig}
        role="img"
      >
        <AreaChart accessibilityLayer data={points}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis
            axisLine={false}
            dataKey="date"
            tickFormatter={formatShortDate}
            tickLine={false}
          />
          <YAxis
            axisLine={false}
            domain={[0, 100]}
            tickFormatter={(value) => `${value}%`}
            tickLine={false}
            width="auto"
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                formatter={(value, name) => (
                  <div className="flex min-w-32 items-center justify-between gap-5">
                    <span className="text-muted-foreground">
                      {String(name) === 'rate' ? '成功率' : String(name)}
                    </span>
                    <span className="font-mono font-medium tabular-nums">
                      {formatPercent(Number(value))}
                    </span>
                  </div>
                )}
                indicator="dot"
                labelFormatter={(label) => formatShortDate(String(label))}
              />
            }
            cursor={false}
          />
          <Area
            dataKey="rate"
            fill="var(--color-rate)"
            fillOpacity={0.28}
            isAnimationActive={false}
            stroke="var(--color-rate)"
            strokeWidth={2}
            type="monotone"
          />
        </AreaChart>
      </ChartContainer>
      <p className="mt-5 text-sm font-medium tabular-nums">
        最近一天 {formatPercent(latest)}
      </p>
      <Table className="sr-only">
        <TableCaption>每日下载成功率精确数据</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">日期</TableHead>
            <TableHead scope="col">成功率</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {points.map((point) => (
            <TableRow key={point.date}>
              <TableHead scope="row">{point.date}</TableHead>
              <TableCell>{formatPercent(point.rate)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
