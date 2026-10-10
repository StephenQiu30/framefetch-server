import { ItemDescription, ItemTitle } from '@/components/ui/item';
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
    <div>
      <Table className="table-borderless">
        <TableCaption className="sr-only">各视频源下载表现</TableCaption>
        <TableHeader>
          <TableRow>
            <SourceHead>视频源</SourceHead>
            <SourceHead numeric>任务</SourceHead>
            <SourceHead numeric>成功率</SourceHead>
            <SourceHead numeric>用户</SourceHead>
            <SourceHead numeric>数据量</SourceHead>
            <TableHead className="hidden lg:table-cell" scope="col">
              状态分布
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sources.map((source) => (
            <TableRow key={source.source_key}>
              <TableHead
                className="whitespace-normal [overflow-wrap:anywhere] lg:w-1/4"
                scope="row"
              >
                <ItemTitle className="line-clamp-none">
                  {sourceLabel(source)}
                </ItemTitle>
                <ItemDescription className="line-clamp-none mt-1">
                  {source.source_key}
                </ItemDescription>
                <div className="mt-2 flex flex-col gap-1 lg:hidden">
                  <ItemDescription className="line-clamp-none">
                    任务 {formatInteger(source.total)} · 成功率{' '}
                    {formatPercent(source.success_rate)} · 用户{' '}
                    {formatInteger(source.unique_users)}
                  </ItemDescription>
                  <ItemDescription className="line-clamp-none">
                    数据量 {formatBytes(source.downloaded_bytes)}
                  </ItemDescription>
                  <StatusSummary source={source} />
                </div>
              </TableHead>
              <MetricCell value={formatInteger(source.total)} />
              <MetricCell value={formatPercent(source.success_rate)} />
              <MetricCell value={formatInteger(source.unique_users)} />
              <MetricCell value={formatBytes(source.downloaded_bytes)} />
              <TableCell className="hidden whitespace-normal lg:table-cell">
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
      className={
        numeric
          ? 'hidden text-right whitespace-nowrap tabular-nums lg:table-cell'
          : undefined
      }
      scope="col"
    >
      {children}
    </TableHead>
  );
}

function MetricCell({ value }: { value: string }) {
  return (
    <TableCell className="hidden text-right whitespace-nowrap tabular-nums lg:table-cell">
      {value}
    </TableCell>
  );
}

function StatusSummary({ source }: { source: Source }) {
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1 tabular-nums">
      <span className="whitespace-nowrap">成功 {source.succeeded}</span>
      <span className="whitespace-nowrap">失败 {source.failed}</span>
      <span className="whitespace-nowrap">取消 {source.cancelled}</span>
      <span className="whitespace-nowrap">进行中 {source.active}</span>
    </span>
  );
}

function sourceLabel(source: Source): string {
  return source.source_name || source.source_key;
}
