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
    <div className="sr-only [&>[data-slot=table-container]]:overflow-visible">
      <Table className="table-borderless">
        <TableCaption>每日下载趋势精确数据</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">日期</TableHead>
            <TableHead scope="col">全部</TableHead>
            <TableHead scope="col">成功</TableHead>
            <TableHead scope="col">失败</TableHead>
            <TableHead scope="col">取消</TableHead>
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
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
