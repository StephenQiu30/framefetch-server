import { Info } from '@phosphor-icons/react';
import { createElement, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { documentPreviewStatusMessage } from '@/components/screenplay/screenplay-document-format';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Separator } from '@/components/ui/separator';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ImportStatusCode } from '@/lib/import-status';

import type { MarkdownHeading } from './screenplay-document-toc';

function renderHeading(
  cursor: { current: number },
  headings: MarkdownHeading[],
  as: 'h2' | 'h3' | 'h4',
  className: string,
  children: ReactNode,
) {
  const heading = headings[cursor.current];
  cursor.current += 1;

  return createElement(as, { className, id: heading?.id }, children);
}

function escapeHtmlTagsForDisplay(markdown: string) {
  return markdown.replace(/<\/?[a-z][^>]*>/gi, (tag) =>
    tag.replace('<', '&lt;').replace('>', '&gt;'),
  );
}

export function ScreenplayDocumentPreview({
  document,
  headings,
}: {
  document: API.DocumentDetailResponse;
  headings: MarkdownHeading[];
}) {
  const headingCursor = { current: 0 };

  return (
    <div
      className="min-w-0 lg:grid lg:h-full lg:min-h-0 lg:grid-rows-[auto_minmax(0,1fr)_auto]"
      data-testid="screenplay-preview-column"
    >
      <div className="flex items-baseline justify-between gap-4">
        <h2
          className="text-lg font-medium tracking-tight"
          id="screenplay-preview-title"
        >
          规范化剧本
        </h2>
        {document.preview ? (
          <span className="text-xs text-muted-foreground">Markdown 预览</span>
        ) : null}
      </div>
      {document.status === ImportStatusCode.Ready && document.preview ? (
        <>
          <article
            aria-label="规范化剧本 Markdown 预览"
            className="mt-4 max-h-dvh overflow-y-auto overscroll-contain bg-surface px-5 py-6 text-base leading-7 text-foreground scrollbar-thin sm:px-8 sm:py-8 lg:min-h-0"
            data-testid="screenplay-markdown-reader"
          >
            <ReactMarkdown
              allowedElements={[
                'blockquote',
                'br',
                'code',
                'del',
                'em',
                'h1',
                'h2',
                'h3',
                'h4',
                'h5',
                'h6',
                'hr',
                'li',
                'ol',
                'p',
                'pre',
                'strong',
                'table',
                'tbody',
                'td',
                'th',
                'thead',
                'tr',
                'ul',
              ]}
              components={{
                blockquote: ({ children }) => (
                  <blockquote className="my-5 rounded-md bg-muted/60 px-4 py-2 text-muted-foreground">
                    {children}
                  </blockquote>
                ),
                code: ({ children }) => (
                  <code className="font-mono text-sm text-foreground">
                    {children}
                  </code>
                ),
                h1: ({ children }) =>
                  renderHeading(
                    headingCursor,
                    headings,
                    'h2',
                    'mb-6 mt-2 scroll-mt-8 text-2xl font-medium tracking-tight sm:text-3xl',
                    children,
                  ),
                h2: ({ children }) =>
                  renderHeading(
                    headingCursor,
                    headings,
                    'h3',
                    'mb-4 mt-10 scroll-mt-8 text-xl font-medium tracking-tight sm:text-2xl',
                    children,
                  ),
                h3: ({ children }) =>
                  renderHeading(
                    headingCursor,
                    headings,
                    'h4',
                    'mb-3 mt-8 scroll-mt-8 text-base font-semibold uppercase tracking-wider sm:text-lg',
                    children,
                  ),
                h4: ({ children }) => (
                  <h5 className="mb-2 mt-6 scroll-mt-8 text-sm font-semibold uppercase tracking-wide">
                    {children}
                  </h5>
                ),
                h5: ({ children }) => (
                  <h6 className="mb-2 mt-5 scroll-mt-8 text-sm font-medium">
                    {children}
                  </h6>
                ),
                h6: ({ children }) => (
                  <p className="mb-2 mt-5 scroll-mt-8 text-sm font-medium">
                    {children}
                  </p>
                ),
                hr: () => <Separator className="my-8" />,
                li: ({ children }) => <li className="pl-1">{children}</li>,
                ol: ({ children }) => (
                  <ol className="my-4 flex list-decimal flex-col gap-1 pl-6">
                    {children}
                  </ol>
                ),
                p: ({ children }) => (
                  <p className="my-4 whitespace-pre-wrap">{children}</p>
                ),
                pre: ({ children }) => (
                  <pre className="my-5 overflow-x-auto rounded-md bg-muted/60 px-4 py-3 font-mono text-xs leading-6">
                    {children}
                  </pre>
                ),
                strong: ({ children }) => (
                  <strong className="font-semibold">{children}</strong>
                ),
                table: ({ children }) => (
                  <Table className="table-borderless my-5 min-w-full text-left">
                    {children}
                  </Table>
                ),
                thead: ({ children }) => <TableHeader>{children}</TableHeader>,
                tbody: ({ children }) => <TableBody>{children}</TableBody>,
                tr: ({ children }) => <TableRow>{children}</TableRow>,
                th: ({ children }) => (
                  <TableHead className="whitespace-normal">
                    {children}
                  </TableHead>
                ),
                td: ({ children }) => (
                  <TableCell className="whitespace-normal">
                    {children}
                  </TableCell>
                ),
                ul: ({ children }) => (
                  <ul className="my-4 flex list-disc flex-col gap-1 pl-6">
                    {children}
                  </ul>
                ),
              }}
              remarkPlugins={[remarkGfm]}
              skipHtml
              unwrapDisallowed
              urlTransform={() => ''}
            >
              {escapeHtmlTagsForDisplay(document.preview)}
            </ReactMarkdown>
          </article>
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
        <div className="mt-4 py-16 text-sm text-muted-foreground">
          {documentPreviewStatusMessage(document.status)}
        </div>
      )}
    </div>
  );
}
