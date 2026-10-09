import { CheckIcon, ClockIcon } from '@phosphor-icons/react';
import { ItemDescription, ItemMedia, ItemTitle } from '@/components/ui/item';
import { Spinner } from '@/components/ui/spinner';
import {
  DownloadStatusCode,
  downloadStageLabels,
} from './download-state-model';

const stages = Object.entries(downloadStageLabels).map(([code, label]) => ({
  code,
  label,
}));

export function DownloadExecutionSummary({
  job,
}: {
  job: API.DownloadResponse;
}) {
  const current = job.stage
    ? stages.findIndex((stage) => stage.code === job.stage)
    : -1;
  return (
    <section
      aria-labelledby="download-stages-title"
      className="@container flex flex-col gap-3"
    >
      <ItemTitle>
        <h3 id="download-stages-title">处理阶段</h3>
      </ItemTitle>
      <ol className="grid grid-cols-3 gap-x-3 gap-y-4 @sm:grid-cols-5">
        {stages.map((stage, index) => {
          const done =
            job.status === DownloadStatusCode.Succeeded ||
            (current >= 0 && index < current);
          const isCurrent = index === current;
          return (
            <li
              key={stage.code}
              className="flex min-w-0 flex-col items-start gap-1"
              aria-current={isCurrent ? 'step' : undefined}
            >
              <ItemMedia variant="icon">
                {done ? (
                  <CheckIcon aria-hidden />
                ) : isCurrent && job.status === DownloadStatusCode.Running ? (
                  <Spinner aria-hidden />
                ) : (
                  <ClockIcon aria-hidden />
                )}
              </ItemMedia>
              <ItemTitle className="line-clamp-none">{stage.label}</ItemTitle>
              <ItemDescription>
                {done ? '已完成' : isCurrent ? '当前阶段' : '等待处理'}
              </ItemDescription>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
