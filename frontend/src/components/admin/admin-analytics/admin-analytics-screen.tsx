import { ArrowClockwiseIcon } from '@phosphor-icons/react';
import type { ReactNode } from 'react';
import { AnalyticsKpis } from '@/components/admin/admin-analytics/analytics-kpis';
import { AnalyticsLoading } from '@/components/admin/admin-analytics/analytics-states';
import { CompletionRateChart } from '@/components/admin/admin-analytics/completion-rate-chart';
import { DailyTrendChart } from '@/components/admin/admin-analytics/daily-trend-chart';
import { SourceBreakdown } from '@/components/admin/admin-analytics/source-breakdown';
import { SourcePerformance } from '@/components/admin/admin-analytics/source-performance';
import { StatusDistributionChart } from '@/components/admin/admin-analytics/status-distribution-chart';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { Button } from '@/components/ui/button';
import { Item, ItemContent, ItemDescription } from '@/components/ui/item';
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
      aria-busy={loading}
      className="gap-8"
      onValueChange={(value) => {
        if (value === 'downloads' || value === 'analysis') onTabChange(value);
      }}
      value={tab}
    >
      <div>
        <PageNavigation fallbackHref="/account" />
        <PageHeader
          action={
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
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
                className="w-full shrink-0 sm:w-auto"
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
          description="查看下载表现与 AI 分析执行情况。"
          title="使用统计"
        />
      </div>
      <TabsList aria-label="统计内容">
        <TabsTrigger value="downloads">下载</TabsTrigger>
        <TabsTrigger value="analysis">AI 分析</TabsTrigger>
      </TabsList>
      <Item variant="muted">
        <ItemContent>
          <ItemDescription className="line-clamp-none">
            图表聚焦后可用左右方向键读取数据；精确数值可在图表明细中查看。AI
            统计按分析执行记录计数，不代表模型请求次数、Token 或费用。
          </ItemDescription>
        </ItemContent>
      </Item>
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
      {data && data.summary.total > 0 ? (
        <DailyTrendChart daily={data.daily} />
      ) : null}
      {data && data.summary.total === 0 ? (
        <PageEmptyNotice
          title="当前周期还没有下载数据"
          description="切换统计周期，或创建下载任务后再查看。"
        />
      ) : null}
      {data && data.summary.total > 0 ? (
        <div className="flex flex-col gap-8">
          <AnalyticsKpis summary={data.summary} />
          <div className="flex flex-col gap-8">
            <StatusDistributionChart summary={data.summary} />
            <CompletionRateChart daily={data.daily} />
            <SourceBreakdown
              sources={data.sources}
              total={data.summary.total}
            />
          </div>
          <SourcePerformance sources={data.sources} />
        </div>
      ) : null}
    </>
  );
}
