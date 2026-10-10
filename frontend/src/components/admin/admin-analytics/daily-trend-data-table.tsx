import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

type DailyPoint = API.DownloadAnalyticsResponse['daily'][number];

export function DailyTrendDataTable({ points }: { points: DailyPoint[] }) {
  return (
    <Table className="table-borderless">
      <TableCaption className="sr-only">每日下载趋势精确数据</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">日期</TableHead>
          <TableHead className="text-right" scope="col">
            全部
          </TableHead>
          <TableHead className="text-right" scope="col">
            成功
          </TableHead>
          <TableHead className="text-right" scope="col">
            失败
          </TableHead>
          <TableHead className="text-right" scope="col">
            取消
          </TableHead>
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
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
