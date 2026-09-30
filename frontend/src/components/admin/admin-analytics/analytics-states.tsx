import { ChartLineUp } from '@phosphor-icons/react';

import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { Skeleton } from '@/components/ui/skeleton';

export function AnalyticsLoading() {
  return (
    <div
      aria-label="正在加载下载分析"
      className="flex flex-col gap-12"
      role="status"
    >
      <span className="sr-only">正在加载下载分析</span>
      <div>
        <Skeleton className="h-5 w-20" />
        <Skeleton className="mt-2 h-4 w-48" />
      </div>
      <div className="grid grid-cols-2 gap-8 lg:grid-cols-4">
        {['total', 'rate', 'users', 'bytes'].map((key) => (
          <div className="flex flex-col gap-3" key={key}>
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-12 w-32" />
            <Skeleton className="h-3 w-full max-w-40" />
          </div>
        ))}
      </div>
      <Skeleton className="w-full aspect-video md:aspect-[3/1]" />
      <div className="flex flex-col gap-20 sm:gap-28">
        {['status', 'completion', 'sources'].map((key) => (
          <div key={key}>
            <Skeleton className="h-6 w-32" />
            <Skeleton className="mt-2 h-4 w-56 max-w-full" />
            <Skeleton className="mt-8 w-full aspect-video md:aspect-[3/1]" />
          </div>
        ))}
      </div>
      <Skeleton className="h-80" />
    </div>
  );
}

export function AnalyticsEmpty() {
  return (
    <PageEmptyNotice
      description="切换统计周期，或等待用户创建下载任务后再查看。"
      icon={<ChartLineUp aria-hidden />}
      title="当前周期还没有下载数据"
    />
  );
}
