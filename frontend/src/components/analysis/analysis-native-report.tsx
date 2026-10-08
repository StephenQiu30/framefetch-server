'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { exportAnalysisNativeReport } from '@/api/analyses';
import AnalysisReportDownloadLink from '@/components/analysis/analysis-report-download-link';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Button } from '@/components/ui/button';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

export default function AnalysisNativeReport({
  analysisId,
  artifacts,
}: {
  analysisId: string;
  artifacts: readonly { format: string }[];
}) {
  const hasHtml = artifacts.some((item) => item.format === 'html');
  const hasBundle = artifacts.some((item) => item.format === 'zip');
  const [copyState, setCopyState] = useState<string>();
  const html = useQuery({
    queryKey: privateQueryKey('analysis-native-html', analysisId),
    enabled: hasHtml,
    queryFn: async ({ signal }) => {
      const blob = await exportAnalysisNativeReport(
        { analysis_id: analysisId, report_format: 'html' },
        { signal, responseType: 'blob' },
      );
      return blob.text();
    },
  });
  if (!hasHtml && !hasBundle) return null;
  return (
    <section className="mt-8 space-y-4" aria-label="文件与排版">
      <div className="flex flex-wrap items-center gap-3">
        {hasBundle ? (
          <Button asChild variant="outline">
            <AnalysisReportDownloadLink analysisId={analysisId} format="zip">
              下载原生拉片包
            </AnalysisReportDownloadLink>
          </Button>
        ) : null}
        {hasHtml ? (
          <>
            <Button asChild variant="outline">
              <AnalysisReportDownloadLink analysisId={analysisId} format="html">
                导出公众号 HTML
              </AnalysisReportDownloadLink>
            </Button>
            <Button
              disabled={!html.data}
              variant="outline"
              onClick={async () => {
                if (!html.data) return;
                try {
                  const doc = new DOMParser().parseFromString(
                    html.data,
                    'text/html',
                  );
                  const body = doc.querySelector('#output') ?? doc.body;
                  await navigator.clipboard.write([
                    new ClipboardItem({
                      'text/html': new Blob([body.innerHTML], {
                        type: 'text/html',
                      }),
                      'text/plain': new Blob([body.textContent ?? ''], {
                        type: 'text/plain',
                      }),
                    }),
                  ]);
                  setCopyState('已复制排版正文，可粘贴到公众号编辑器。');
                } catch (error) {
                  setCopyState(displayError(error));
                }
              }}
            >
              复制公众号正文
            </Button>
          </>
        ) : null}
      </div>
      {hasBundle ? (
        <p className="text-sm text-muted-foreground">
          包含原生 HTML、Markdown、镜头
          JSON、运动曲线、逐镜关键帧和联系表。解压后打开
          report.html，可用本地视频查看；原视频不包含在包内。
        </p>
      ) : null}
      {copyState ? (
        <p role="status" className="text-sm text-muted-foreground">
          {copyState}
        </p>
      ) : null}
      {html.error ? (
        <FeedbackNotice
          title="排版预览加载失败"
          description={displayError(html.error)}
          tone="error"
        />
      ) : null}
      {html.data ? (
        <Accordion type="single" collapsible>
          <AccordionItem value="wechat-preview">
            <AccordionTrigger>查看公众号排版预览</AccordionTrigger>
            <AccordionContent>
              <iframe
                title="公众号原生排版预览"
                className="h-[640px] w-full bg-white"
                sandbox=""
                referrerPolicy="no-referrer"
                srcDoc={`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:;">${html.data}`}
              />
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      ) : null}
    </section>
  );
}
