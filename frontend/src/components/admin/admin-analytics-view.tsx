'use client';

import { useState } from 'react';

import {
  AdminAnalyticsScreen,
  type AnalyticsTab,
  DownloadAnalyticsContent,
} from '@/components/admin/admin-analytics/admin-analytics-screen';
import { AnalysisAnalyticsContent } from '@/components/admin/admin-analytics/analysis-analytics-content';
import { useAdminAnalysisAnalytics } from '@/components/admin/admin-analytics/use-analysis-analytics';
import { useAdminDownloadAnalytics } from '@/components/admin/admin-analytics/use-download-analytics';

export function AdminAnalyticsView() {
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [tab, setTab] = useState<AnalyticsTab>('downloads');
  const downloads = useAdminDownloadAnalytics(days, tab === 'downloads');
  const analyses = useAdminAnalysisAnalytics(days, tab === 'analysis');
  const active = tab === 'downloads' ? downloads : analyses;

  return (
    <AdminAnalyticsScreen
      analysisContent={
        <AnalysisAnalyticsContent {...analyses} onRetry={analyses.retry} />
      }
      dateRange={active.data}
      days={days}
      downloadContent={
        <DownloadAnalyticsContent {...downloads} onRetry={downloads.retry} />
      }
      loading={active.loading}
      onDaysChange={setDays}
      onRetry={active.retry}
      onTabChange={setTab}
      tab={tab}
    />
  );
}
