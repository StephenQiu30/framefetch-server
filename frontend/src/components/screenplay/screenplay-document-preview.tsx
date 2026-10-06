'use client';

import { Info } from '@phosphor-icons/react';
import { useMemo } from 'react';
import { markdownToEditorDocument, Viewer } from '@/components/editor';
import { documentPreviewStatusMessage } from '@/components/screenplay/screenplay-document-format';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { ItemTitle } from '@/components/ui/item';
import { ImportStatusCode } from '@/lib/import-status';

import type { MarkdownHeading } from './screenplay-document-toc';

export function ScreenplayDocumentPreview({
  document,
  headings,
}: {
  document: API.DocumentDetailResponse;
  headings: MarkdownHeading[];
}) {
  const content = useMemo(
    () => markdownToEditorDocument(document.preview ?? '', 'text'),
    [document.preview],
  );
  return (
    <div
      className="min-w-0 lg:grid lg:h-full lg:grid-rows-[auto_minmax(0,1fr)_auto]"
      data-testid="screenplay-preview-column"
    >
      <div className="flex items-baseline justify-between gap-4">
        <ItemTitle className="line-clamp-none">
          <h2 id="screenplay-preview-title">规范化剧本</h2>
        </ItemTitle>
        {document.preview ? <span>Markdown 预览</span> : null}
      </div>
      {document.status === ImportStatusCode.Ready && document.preview ? (
        <>
          <Viewer
            value={content}
            headingOffset={1}
            headingIds={headings.map((heading) => heading.id)}
            links={false}
            aria-label="规范化剧本 Markdown 预览"
            className="mt-4 max-h-dvh overflow-y-auto overscroll-contain scrollbar-thin"
            data-testid="screenplay-markdown-reader"
          />
          {document.preview_truncated ? (
            <Alert className="mt-4" variant="default">
              <Info aria-hidden />
              <div className="min-w-0">
                <AlertTitle>预览已截断</AlertTitle>
                <AlertDescription>
                  当前内容仍受接口读取上限约束，只显示了文件开头的一段。
                </AlertDescription>
              </div>
            </Alert>
          ) : null}
        </>
      ) : (
        <div className="mt-4">
          {documentPreviewStatusMessage(document.status)}
        </div>
      )}
    </div>
  );
}
