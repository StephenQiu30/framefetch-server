import { ItemDescription } from '@/components/ui/item';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import { formatBytes, formatInteger, formatPercent } from './analytics-format';

type Source = API.DownloadAnalyticsResponse['sources'][number];

export function SourcePerformanceDetails({ sources }: { sources: Source[] }) {
  return (
    <div className="mt-7">
      <Table className="table-borderless">
        <TableCaption className="sr-only">各视频源下载表现</TableCaption>
        <TableHeader>
          <TableRow>
            <SourceHead>视频源</SourceHead>
            <SourceHead numeric>任务</SourceHead>
            <SourceHead numeric>成功率</SourceHead>
            <SourceHead numeric>用户</SourceHead>
            <SourceHead numeric>数据量</SourceHead>
            <SourceHead>状态分布</SourceHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sources.map((source) => (
            <TableRow key={source.source_key}>
              <TableHead className="text-left whitespace-normal" scope="row">
                <ItemDescription className="line-clamp-none truncate">
                  {sourceLabel(source)}
                </ItemDescription>
                <ItemDescription className="line-clamp-none mt-1 truncate">
                  {source.source_key}
                </ItemDescription>
              </TableHead>
              <MetricCell value={formatInteger(source.total)} />
              <MetricCell value={formatPercent(source.success_rate)} />
              <MetricCell value={formatInteger(source.unique_users)} />
              <MetricCell value={formatBytes(source.downloaded_bytes)} />
              <TableCell className="whitespace-normal">
                <StatusSummary source={source} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function SourceHead({
  children,
  numeric = false,
}: {
  children: React.ReactNode;
  numeric?: boolean;
}) {
  return (
    <TableHead
      className={numeric ? 'text-right tabular-nums' : undefined}
      scope="col"
    >
      {children}
    </TableHead>
  );
}

function MetricCell({ value }: { value: string }) {
  return (
    <TableCell className="text-right tabular-nums whitespace-normal">
      {value}
    </TableCell>
  );
}

function StatusSummary({ source }: { source: Source }) {
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1 tabular-nums">
      <span>成功 {source.succeeded}</span>
      <span>失败 {source.failed}</span>
      <span>取消 {source.cancelled}</span>
      <span>进行中 {source.active}</span>
    </span>
  );
}

function sourceLabel(source: Source): string {
  return source.source_name || source.source_key;
}
