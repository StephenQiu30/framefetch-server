'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { listContentVersions } from '@/api/analyses';
import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { Button } from '@/components/ui/button';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

export default function ContentReportHistory({
  analysisId,
  currentReportId,
}: {
  analysisId: string;
  currentReportId: string | null;
}) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: privateQueryKey('content-versions', analysisId, currentReportId),
    enabled: open,
    queryFn: ({ signal }) =>
      listContentVersions({ analysis_id: analysisId }, { signal }),
  });
  return (
    <details
      className="text-sm"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer py-2 font-medium">报告历史</summary>
      {query.isFetching ? <p role="status">正在读取报告历史…</p> : null}
      {query.error ? (
        <FeedbackNotice
          title="报告历史读取失败"
          description={displayError(query.error)}
          tone="error"
          action={<Button onClick={() => void query.refetch()}>重试</Button>}
        />
      ) : null}
      <div className="mt-4 grid gap-5">
        {query.data?.map((version) => (
          <details key={version.id}>
            <summary className="cursor-pointer">
              第 {version.run_no} 份报告
              {version.id === currentReportId ? ' · 当前报告' : ''} ·{' '}
              {new Date(version.created_at).toLocaleString('zh-CN', {
                hour12: false,
              })}
            </summary>
            <div className="mt-4">
              <AnalysisReportPreview markdown={version.markdown} />
            </div>
          </details>
        ))}
      </div>
    </details>
  );
}
