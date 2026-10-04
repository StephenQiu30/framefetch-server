'use client';

import { cn } from 'cn';
import { type ComponentProps, createElement, useMemo } from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  type EditorContent,
  type HtmlPolicy,
  type ListItem,
  toEditorDocument,
} from './document';
import { RichText } from './rich-text';

export type ViewerProps = Omit<ComponentProps<'article'>, 'children'> & {
  value: EditorContent;
  headingOffset?: number;
  headingIds?: string[];
  links?: boolean;
  htmlPolicy?: HtmlPolicy;
};

function ContentList({
  items,
  style,
  start,
  links,
}: {
  items: ListItem[];
  style: string;
  start?: number;
  links: boolean;
}) {
  const children = items.map((item, index) => (
    // The official list format has no per-item identity; position is stable in a read-only document.
    // biome-ignore lint/suspicious/noArrayIndexKey: Editor.js list items have no IDs.
    <li key={index} className="pl-1">
      {style === 'checklist' ? (
        <input
          type="checkbox"
          checked={Boolean(item.meta?.checked)}
          disabled
          aria-label="任务完成状态"
          className="mr-2"
        />
      ) : null}
      <RichText text={item.content} links={links} />
      {item.items?.length ? (
        <ContentList items={item.items} style={style} links={links} />
      ) : null}
    </li>
  ));
  return style === 'ordered' ? (
    <ol start={start} className="my-4 flex list-decimal flex-col gap-1 pl-6">
      {children}
    </ol>
  ) : (
    <ul
      className={cn(
        'my-4 flex flex-col gap-1 pl-6',
        style !== 'checklist' && 'list-disc',
      )}
    >
      {children}
    </ul>
  );
}

export function Viewer({
  value,
  headingOffset = 0,
  headingIds = [],
  links = true,
  htmlPolicy = 'omit',
  className,
  ...props
}: ViewerProps) {
  const document = useMemo(
    () => toEditorDocument(value, htmlPolicy),
    [value, htmlPolicy],
  );
  let headingIndex = 0;
  return (
    <article
      {...props}
      data-slot="viewer"
      className={cn(
        'min-w-0 w-full max-w-full text-base leading-7 [overflow-wrap:anywhere] [&_code]:font-mono [&_code]:text-sm [&_strong]:font-semibold',
        className,
      )}
    >
      {document.blocks.map((block, index) => {
        const key = block.id ?? `block-${index}`;
        const data = block.data;
        switch (block.type) {
          case 'header': {
            const level = Math.max(1, Math.min(6, Number(data.level) || 2));
            const id = level <= 3 ? headingIds[headingIndex++] : undefined;
            return createElement(
              `h${Math.min(6, level + headingOffset)}`,
              {
                key,
                id,
                className: cn(
                  'my-5 scroll-mt-8 font-medium tracking-tight',
                  level === 1
                    ? 'text-2xl'
                    : level === 2
                      ? 'mt-10 text-xl'
                      : 'mt-7 text-lg',
                ),
              },
              <RichText text={String(data.text ?? '')} links={links} />,
            );
          }
          case 'paragraph':
            return (
              <p key={key} className="my-4 whitespace-pre-wrap">
                <RichText text={String(data.text ?? '')} links={links} />
              </p>
            );
          case 'quote':
            return (
              <blockquote
                key={key}
                className="my-5 rounded-md bg-muted/60 px-4 py-2 text-muted-foreground"
              >
                <RichText text={String(data.text ?? '')} links={links} />
                {data.caption ? (
                  <footer className="mt-2 text-sm">
                    <RichText text={String(data.caption)} links={links} />
                  </footer>
                ) : null}
              </blockquote>
            );
          case 'code':
            return (
              <pre
                key={key}
                className="my-5 min-w-0 max-w-full overflow-x-auto whitespace-pre rounded-md bg-muted/60 px-4 py-3 font-mono text-sm leading-6 [overflow-wrap:normal]"
              >
                <code>{String(data.code ?? '')}</code>
              </pre>
            );
          case 'delimiter':
            return <hr key={key} className="my-8 border-border" />;
          case 'list':
            return (
              <ContentList
                key={key}
                items={data.items ?? []}
                style={data.style}
                start={data.meta?.start}
                links={links}
              />
            );
          case 'table': {
            const rows: string[][] = data.content ?? [];
            const row = (
              cells: string[],
              rowIndex: number,
              heading: boolean,
            ) => (
              <TableRow key={rowIndex}>
                {cells.map((cell, cellIndex) => {
                  const Cell = heading ? TableHead : TableCell;
                  return (
                    // biome-ignore lint/suspicious/noArrayIndexKey: Editor.js table cells have no IDs.
                    <Cell key={cellIndex} className="whitespace-normal">
                      <RichText text={cell} links={links} />
                    </Cell>
                  );
                })}
              </TableRow>
            );
            return (
              <Table
                key={key}
                className="table-borderless my-5 w-full text-left"
              >
                {data.withHeadings && rows.length ? (
                  <TableHeader>{row(rows[0], 0, true)}</TableHeader>
                ) : null}
                <TableBody>
                  {rows
                    .slice(data.withHeadings ? 1 : 0)
                    .map((cells, i) => row(cells, i, false))}
                </TableBody>
              </Table>
            );
          }
          default:
            return (
              <p key={key} className="my-4 whitespace-pre-wrap">
                {typeof data.text === 'string' ? (
                  <RichText text={data.text} links={links} />
                ) : (
                  '此内容块暂不支持显示。'
                )}
              </p>
            );
        }
      })}
    </article>
  );
}
