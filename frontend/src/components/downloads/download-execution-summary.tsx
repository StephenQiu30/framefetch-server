import { CheckIcon, ClockIcon } from '@phosphor-icons/react';
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
      className="flex flex-col gap-3"
    >
      <ItemTitle>
        <h3 id="download-stages-title">处理阶段</h3>
      </ItemTitle>
      <ItemGroup>
        {stages.map((stage, index) => {
          const done =
            job.status === DownloadStatusCode.Succeeded ||
            (current >= 0 && index < current);
          const isCurrent = index === current;
          return (
            <Item
              key={stage.code}
              role="listitem"
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
              <ItemContent>
                <ItemTitle>{stage.label}</ItemTitle>
                <ItemDescription>
                  {done ? '已完成' : isCurrent ? '当前阶段' : '等待处理'}
                </ItemDescription>
              </ItemContent>
            </Item>
          );
        })}
      </ItemGroup>
      <FieldDescription>
        阶段按处理顺序展示，当前阶段随任务状态更新。
      </FieldDescription>
    </section>
  );
}
