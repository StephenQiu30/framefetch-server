'use client';

import { useMemo } from 'react';
import { markdownToEditorDocument, Viewer } from '@/components/editor';

export default function AnalysisReportPreview({
  markdown,
}: {
  markdown: string;
}) {
  const document = useMemo(
    () => markdownToEditorDocument(markdown),
    [markdown],
  );
  return (
    <Viewer
      value={document}
      headingOffset={2}
      aria-label="Markdown 分析报告预览"
    />
  );
}
