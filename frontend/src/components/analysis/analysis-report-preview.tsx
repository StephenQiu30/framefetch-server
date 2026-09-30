'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

const allowedElements = [
  'blockquote',
  'code',
  'em',
  'h1',
  'h2',
  'h3',
  'hr',
  'li',
  'ol',
  'p',
  'strong',
  'table',
  'tbody',
  'td',
  'th',
  'thead',
  'tr',
  'ul',
];

export default function AnalysisReportPreview({
  markdown,
}: {
  markdown: string;
}) {
  return (
    <article
      aria-label="Markdown 分析报告预览"
      className="w-full text-base leading-7"
    >
      <ReactMarkdown
        allowedElements={allowedElements}
        components={{
          blockquote: ({ children }) => (
            <blockquote className="my-5 rounded-md bg-muted/60 px-4 py-2 text-muted-foreground">
              {children}
            </blockquote>
          ),
          h1: ({ children }) => (
            <h3 className="mb-5 text-2xl font-medium tracking-tight">
              {children}
            </h3>
          ),
          h2: ({ children }) => (
            <h4 className="mt-10 pb-3 text-lg font-medium tracking-tight">
              {children}
            </h4>
          ),
          h3: ({ children }) => (
            <h5 className="mt-7 font-medium">{children}</h5>
          ),
          li: ({ children }) => <li className="pl-1">{children}</li>,
          ol: ({ children }) => (
            <ol className="my-4 flex flex-col gap-1 list-decimal pl-5">
              {children}
            </ol>
          ),
          p: ({ children }) => (
            <p className="my-3 text-muted-foreground">{children}</p>
          ),
          table: ({ children }) => (
            <Table className="table-borderless my-6 w-full text-left">
              {children}
            </Table>
          ),
          thead: ({ children }) => <TableHeader>{children}</TableHeader>,
          tbody: ({ children }) => <TableBody>{children}</TableBody>,
          tr: ({ children }) => <TableRow>{children}</TableRow>,
          td: ({ children }) => (
            <TableCell className="whitespace-normal">{children}</TableCell>
          ),
          th: ({ children }) => (
            <TableHead className="whitespace-normal">{children}</TableHead>
          ),
          ul: ({ children }) => (
            <ul className="my-4 flex flex-col gap-1 list-disc pl-5">
              {children}
            </ul>
          ),
        }}
        remarkPlugins={[remarkGfm]}
        skipHtml
        unwrapDisallowed
        urlTransform={() => ''}
      >
        {markdown}
      </ReactMarkdown>
    </article>
  );
}
