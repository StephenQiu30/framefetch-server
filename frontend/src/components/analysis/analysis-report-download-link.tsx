'use client';

import { type ComponentProps, useState } from 'react';
import { exportAnalysisMarkdown, exportAnalysisReport } from '@/api/analyses';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { displayError } from '@/lib/request-error';

export default function AnalysisReportDownloadLink({
  analysisId,
  format,
  onClick,
  download,
  ...props
}: Omit<ComponentProps<'a'>, 'href'> & {
  analysisId: string;
  format: 'md' | 'docx';
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  return (
    <>
      <a
        {...props}
        href={`#report-${format}`}
        download={download}
        aria-busy={pending}
        aria-disabled={pending}
        onClick={async (event) => {
          onClick?.(event);
          if (event.defaultPrevented) return;
          event.preventDefault();
          if (pending) return;
          setPending(true);
          setError(undefined);
          try {
            const params = { analysis_id: encodeURIComponent(analysisId) };
            const options = { responseType: 'blob' as const };
            const blob: Blob =
              format === 'md'
                ? await exportAnalysisMarkdown(params, options)
                : await exportAnalysisReport(params, options);
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download =
              typeof download === 'string'
                ? download
                : `analysis-report-${analysisId}.${format}`;
            document.body.append(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
          } catch (reason) {
            setError(displayError(reason));
          } finally {
            setPending(false);
          }
        }}
      />
      {error ? (
        <FeedbackNotice
          presentation="toast"
          className="mt-2"
          description={error}
          title="报告下载失败"
          tone="error"
        />
      ) : null}
    </>
  );
}
