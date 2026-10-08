import dynamic from 'next/dynamic';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { ItemDescription, ItemTitle } from '@/components/ui/item';
import { DailyTrendDataTable } from './daily-trend-data-table';
import { ChartLoading, DeferredChart } from './deferred-chart';

const DailyTrendPlot = dynamic(
  () => import('./daily-trend-plot').then((module) => module.DailyTrendPlot),
  { loading: ChartLoading },
);

type DailyPoint = API.DownloadAnalyticsResponse['daily'][number];

export function DailyTrendChart({ daily }: { daily: DailyPoint[] }) {
  const points = [...daily].sort((left, right) =>
    left.date.localeCompare(right.date),
  );

  return (
    <div className="w-full">
      <div className="flex flex-col gap-2">
        <ItemTitle className="line-clamp-none">
          <h2 id="daily-trend-title">每日下载趋势</h2>
        </ItemTitle>
        <ItemDescription className="line-clamp-none max-w-2xl">
          使用面积对比每日创建任务与成功完成任务。
        </ItemDescription>
      </div>
      <div className="mt-8">
        <p className="sr-only" id="daily-trend-description">
          两层面积分别表示全部任务与成功任务，可悬浮或使用键盘读取单日数据，失败与取消的精确数值见图表后的数据表。
        </p>
        {points.length > 0 ? (
          <DeferredChart>
            <DailyTrendPlot points={points} />
          </DeferredChart>
        ) : (
          <PageEmptyNotice
            compact
            title="当前周期还没有下载数据"
            description="切换统计周期，或创建下载任务后再查看。"
          />
        )}
        <DailyTrendDataTable points={points} />
      </div>
    </div>
  );
}
