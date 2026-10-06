'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { listContentVersions } from '@/api/analyses';
import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Button } from '@/components/ui/button';
import { ItemDescription } from '@/components/ui/item';
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
  const [expandedVersions, setExpandedVersions] = useState<string[]>([]);
  const query = useQuery({
    queryKey: privateQueryKey('content-versions', analysisId, currentReportId),
    enabled: open,
    queryFn: ({ signal }) =>
      listContentVersions({ analysis_id: analysisId }, { signal }),
  });
  return (
    <Accordion
      type="single"
      collapsible
      value={open ? 'history' : ''}
      onValueChange={(value) => setOpen(value === 'history')}
    >
      <AccordionItem value="history">
        <AccordionTrigger>报告历史</AccordionTrigger>
        <AccordionContent>
          {query.isFetching ? (
            <ItemDescription className="line-clamp-none" role="status">
              正在读取报告历史…
            </ItemDescription>
          ) : null}
          {query.error ? (
            <FeedbackNotice
              title="报告历史读取失败"
              description={displayError(query.error)}
              tone="error"
              action={
                <Button onClick={() => void query.refetch()}>重试</Button>
              }
            />
          ) : null}
          <Accordion
            type="multiple"
            value={expandedVersions}
            onValueChange={setExpandedVersions}
            className="mt-4 gap-5"
          >
            {query.data?.map((version) => (
              <AccordionItem key={version.id} value={version.id}>
                <AccordionTrigger>
                  第 {version.run_no} 份报告
                  {version.id === currentReportId ? ' · 当前报告' : ''} ·{' '}
                  {new Date(version.created_at).toLocaleString('zh-CN', {
                    hour12: false,
                  })}
                </AccordionTrigger>
                <AccordionContent>
                  <AnalysisReportPreview markdown={version.markdown} />
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
