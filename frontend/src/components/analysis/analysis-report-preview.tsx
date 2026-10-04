'use client';

import { Viewer } from '@/components/editor';

export default function AnalysisReportPreview({
  markdown,
}: {
  markdown: string;
}) {
  return (
    <Viewer
      value={markdown}
      headingOffset={2}
      aria-label="Markdown 分析报告预览"
    />
  );
}
