'use client';

import { CaretDownIcon } from '@phosphor-icons/react';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { Button } from '@/components/ui/button';
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import { formatShortDate } from './analytics-format';

type DailyPoint = API.AnalysisAnalyticsResponse['daily'][number];

const trendConfig = {
  total: { color: 'var(--chart-2)', label: '全部执行' },
  succeeded: { color: 'var(--chart-1)', label: '成功执行' },
} satisfies ChartConfig;

export function AnalysisTrendChart({ daily }: { daily: DailyPoint[] }) {
  const points = [...daily].sort((left, right) =>
    left.date.localeCompare(right.date),
  );
  return (
    <section aria-labelledby="analysis-trend-title" className="min-w-0">
      <h2
        className="text-xl font-medium tracking-tight"
        id="analysis-trend-title"
      >
        每日分析趋势
      </h2>
      <p
        className="mt-2 text-sm leading-6 text-muted-foreground"
        id="analysis-trend-description"
      >
        按创建日期（UTC）统计分析执行记录，重试和重新执行分别计数。
      </p>
      <ChartContainer
        aria-describedby="analysis-trend-description"
        aria-label="每日 AI 分析执行趋势图"
        className="mt-6 w-full md:aspect-[3/1]"
        config={trendConfig}
        role="img"
      >
        <AreaChart accessibilityLayer data={points}>
          <CartesianGrid vertical={false} />
          <XAxis
            axisLine={false}
            dataKey="date"
            tickFormatter={formatShortDate}
            tickLine={false}
          />
          <YAxis
            allowDecimals={false}
            axisLine={false}
            tickLine={false}
            width="auto"
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={(label) => formatShortDate(String(label))}
              />
            }
            cursor={false}
          />
          <Area
            dataKey="total"
            fill="var(--color-total)"
            fillOpacity={0.2}
            isAnimationActive={false}
            stroke="var(--color-total)"
            strokeWidth={2}
            type="linear"
          />
          <Area
            dataKey="succeeded"
            fill="var(--color-succeeded)"
            fillOpacity={0.3}
            isAnimationActive={false}
            stroke="var(--color-succeeded)"
            strokeWidth={2}
            type="linear"
          />
          <ChartLegend content={<ChartLegendContent className="flex-wrap" />} />
        </AreaChart>
      </ChartContainer>
      <Collapsible className="mt-4">
        <CollapsibleTrigger asChild>
          <Button className="group" type="button" variant="ghost">
            查看每日明细
            <CaretDownIcon
              aria-hidden
              className="transition-transform group-data-[state=open]:rotate-180"
              data-icon="inline-end"
            />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Table className="table-borderless mt-4">
            <TableCaption className="sr-only">
              每日 AI 分析执行精确数据
            </TableCaption>
            <TableHeader>
              <TableRow>
                {['日期', '全部', '成功', '失败', '取消', '进行中'].map(
                  (label) => (
                    <TableHead key={label} scope="col">
                      {label}
                    </TableHead>
                  ),
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {points.map((point) => (
                <TableRow key={point.date}>
                  <TableHead scope="row">{point.date}</TableHead>
                  <TableCell>{point.total}</TableCell>
                  <TableCell>{point.succeeded}</TableCell>
                  <TableCell>{point.failed}</TableCell>
                  <TableCell>{point.cancelled}</TableCell>
                  <TableCell>{point.active}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
