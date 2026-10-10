'use client';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { AnalyticsChartPanel } from './analytics-chart-panel';
import { DailyTrendPlot } from './daily-trend-plot';

type DailyPoint = API.AnalysisAnalyticsResponse['daily'][number];

export function AnalysisTrendChart({ daily }: { daily: DailyPoint[] }) {
  const points = [...daily].sort((left, right) =>
    left.date.localeCompare(right.date),
  );
  return (
    <AnalyticsChartPanel
      id="analysis-trend"
      title="每日分析趋势"
      detailsLabel="查看每日明细"
      details={
        <Table className="table-borderless">
          <TableCaption className="sr-only">
            每日 AI 分析执行精确数据
          </TableCaption>
          <TableHeader>
            <TableRow>
              {['日期', '全部', '成功', '失败', '取消', '进行中'].map(
                (label) => (
                  <TableHead
                    key={label}
                    scope="col"
                    className={
                      label === '日期' ? undefined : 'text-right tabular-nums'
                    }
                  >
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
                <TableCell className="text-right tabular-nums">
                  {point.total}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {point.succeeded}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {point.failed}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {point.cancelled}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {point.active}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    >
      <DailyTrendPlot points={points} kind="analysis" />
    </AnalyticsChartPanel>
  );
}
