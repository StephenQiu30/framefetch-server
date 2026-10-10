import { ArrowClockwiseIcon } from '@phosphor-icons/react';
import dynamic from 'next/dynamic';
import type { ReactNode } from 'react';
import { AnalyticsKpis } from '@/components/admin/admin-analytics/analytics-kpis';
import { AnalyticsLoading } from '@/components/admin/admin-analytics/analytics-states';
import { DailyTrendChart } from '@/components/admin/admin-analytics/daily-trend-chart';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { Button } from '@/components/ui/button';
import { ItemDescription } from '@/components/ui/item';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Spinner } from '@/components/ui/spinner';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { formatDateRange } from './analytics-format';
import { AnalyticsHelp } from './analytics-help';
import { ChartLoading, DeferredChart } from './deferred-chart';

const CompletionRateChart = dynamic(
  () =>
    import('./completion-rate-chart').then(
      (module) => module.CompletionRateChart,
    ),
  { loading: () => <ChartLoading /> },
);
const SourceBreakdown = dynamic(
  () => import('./source-breakdown').then((module) => module.SourceBreakdown),
  { loading: () => <ChartLoading /> },
);
const StatusDistributionChart = dynamic(
  () =>
    import('./status-distribution-chart').then(
      (module) => module.StatusDistributionChart,
    ),
  { loading: () => <ChartLoading /> },
);

const periodLabels = {
  7: '最近 7 天',
  30: '最近 30 天',
  90: '最近 3 个月',
} as const;

export type AnalyticsTab = 'downloads' | 'analysis';

type AdminAnalyticsScreenProps = {
  analysisContent: ReactNode;
  dateRange: { start: string; end: string } | null;
  days: 7 | 30 | 90;
  downloadContent: ReactNode;
  loading: boolean;
  onDaysChange: (days: 7 | 30 | 90) => void;
  onRetry: () => void;
  onTabChange: (tab: AnalyticsTab) => void;
  tab: AnalyticsTab;
};

export function AdminAnalyticsScreen({
  analysisContent,
  dateRange,
  days,
  downloadContent,
  loading,
  onDaysChange,
  onRetry,
  onTabChange,
  tab,
}: AdminAnalyticsScreenProps) {
  return (
    <Tabs
      data-usage-analytics
      aria-busy={loading}
      className="gap-6"
      onValueChange={(value) => {
        if (value === 'downloads' || value === 'analysis') onTabChange(value);
      }}
      value={tab}
    >
      <div>
        <PageNavigation fallbackHref="/account" />
        <PageHeader
          action={
            <div className="flex items-end gap-2 sm:items-center">
              <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center">
                {dateRange ? (
                  <ItemDescription className="line-clamp-none tabular-nums">
                    {formatDateRange(dateRange.start, dateRange.end)}
                  </ItemDescription>
                ) : null}
                <Select
                  value={String(days)}
                  onValueChange={(value) => {
                    if (value) onDaysChange(Number(value) as 7 | 30 | 90);
                  }}
                >
                  <SelectTrigger
                    aria-label="统计周期"
                    className="w-full sm:w-40"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {Object.entries(periodLabels).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>
              <Button
                aria-label="刷新使用统计"
                className="shrink-0"
                disabled={loading}
                onClick={onRetry}
                type="button"
                variant="outline"
              >
                {loading ? (
                  <Spinner aria-hidden data-icon="inline-start" />
                ) : (
                  <ArrowClockwiseIcon aria-hidden data-icon="inline-start" />
                )}
                刷新
              </Button>
            </div>
          }
          title="使用统计"
        />
      </div>
      <div className="flex items-center justify-between gap-3">
        <TabsList aria-label="统计内容">
          <TabsTrigger value="downloads">下载</TabsTrigger>
          <TabsTrigger value="analysis">AI 分析</TabsTrigger>
        </TabsList>
        <AnalyticsHelp kind={tab} />
      </div>
      <TabsContent className="flex flex-col gap-8" value="downloads">
        {downloadContent}
      </TabsContent>
      <TabsContent className="flex flex-col gap-8" value="analysis">
        {analysisContent}
      </TabsContent>
    </Tabs>
  );
}

export function DownloadAnalyticsContent({
  data,
  error,
  loading,
  onRetry,
}: {
  data: API.DownloadAnalyticsResponse | null;
  error: string | null;
  loading: boolean;
  onRetry: () => void;
}) {
  return (
    <>
      {error && !data ? (
        <PageErrorNotice
          message={error}
          onRetry={onRetry}
          title="无法加载下载分析"
        />
      ) : null}
      {error && data ? (
        <FeedbackNotice
          action={
            <Button onClick={onRetry} size="default" variant="outline">
              重新加载
            </Button>
          }
          description={error}
          title="下载分析刷新失败"
          tone="error"
        />
      ) : null}
      {loading && !data ? <AnalyticsLoading /> : null}
      {data && data.summary.total === 0 ? (
        <PageEmptyNotice
          title="当前周期还没有下载数据"
          description="切换统计周期，或创建下载任务后再查看。"
        />
      ) : null}
      {data && data.summary.total > 0 ? (
        <>
          <AnalyticsKpis summary={data.summary} />
          <DailyTrendChart daily={data.daily} />
          <div className="grid min-w-0 gap-6 lg:grid-cols-3">
            <DeferredChart>
              <StatusDistributionChart summary={data.summary} />
            </DeferredChart>
            <DeferredChart>
              <SourceBreakdown
                sources={data.sources}
                total={data.summary.total}
              />
            </DeferredChart>
            <DeferredChart>
              <CompletionRateChart daily={data.daily} />
            </DeferredChart>
          </div>
        </>
      ) : null}
    </>
  );
}
