import {
  Clock,
  ShieldCheck,
  WarningCircle,
  XCircle,
} from '@phosphor-icons/react';
import { FieldDescription } from '@/components/ui/field';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from '@/components/ui/item';
import { Spinner } from '@/components/ui/spinner';
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
  DownloadStatusCode,
  displayStage,
  executionTitle,
  statusLabels,
} from './download-state-model';

export function DownloadExecutionSummary({
  job,
}: {
  job: API.DownloadResponse;
}) {
  const complete = job.status === DownloadStatusCode.Succeeded;
  const failed = job.status === DownloadStatusCode.Failed;
  const cancelled = job.status === DownloadStatusCode.Cancelled;

  return (
    <>
      <section
        aria-labelledby="download-stages-title"
        className="flex flex-col gap-3"
      >
        <ItemTitle>
          <h2 id="download-stages-title">处理阶段</h2>
        </ItemTitle>
        <ItemGroup>
          <Item className="items-start" role="listitem">
            <ItemMedia variant="icon">
              {complete ? (
                <ShieldCheck aria-hidden />
              ) : failed ? (
                <WarningCircle aria-hidden />
              ) : cancelled ? (
                <XCircle aria-hidden />
              ) : job.status === DownloadStatusCode.Running ? (
                <Spinner aria-hidden />
              ) : (
                <Clock aria-hidden />
              )}
            </ItemMedia>
            <ItemContent>
              <ItemTitle>{displayStage(job)}</ItemTitle>
              <ItemDescription className="line-clamp-none">
                {complete ? (
                  <span>{job.file_available ? '持久保存' : '文件已清理'}</span>
                ) : (
                  <span>{statusLabels[job.status]}</span>
                )}{' '}
                · {complete ? executionTitle(job) : `第 ${job.attempt} 次执行`}
              </ItemDescription>
            </ItemContent>
          </Item>
        </ItemGroup>
        <FieldDescription>当前阶段随任务状态更新。</FieldDescription>
      </section>
      <section
        aria-labelledby="download-records-title"
        className="flex flex-col gap-3"
      >
        <ItemTitle>
          <h2 id="download-records-title">执行记录</h2>
        </ItemTitle>
        <Table
          className="table-borderless [&_td]:whitespace-normal [&_td]:[overflow-wrap:anywhere]"
          tabIndex={0}
        >
          <TableCaption className="sr-only">任务时间记录</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>时间</TableHead>
              <TableHead>阶段</TableHead>
              <TableHead>说明</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>
                <time dateTime={job.created_at}>
                  {formatDate(job.created_at)}
                </time>
              </TableCell>
              <TableCell>创建</TableCell>
              <TableCell>任务已创建</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>
                <time dateTime={job.updated_at}>
                  {formatDate(job.updated_at)}
                </time>
              </TableCell>
              <TableCell>{displayStage(job)}</TableCell>
              <TableCell>最新状态：{statusLabels[job.status]}</TableCell>
            </TableRow>
            {job.finished_at ? (
              <TableRow>
                <TableCell>
                  <time dateTime={job.finished_at}>
                    {formatDate(job.finished_at)}
                  </time>
                </TableCell>
                <TableCell>结束</TableCell>
                <TableCell>{statusLabels[job.status]}</TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </section>
    </>
  );
}

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'short',
  timeStyle: 'medium',
});
function formatDate(value: string) {
  return dateFormatter.format(new Date(value));
}
