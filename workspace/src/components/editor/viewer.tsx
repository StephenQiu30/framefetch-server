'use client';

import { cn } from 'cn';
import { type ComponentProps, useMemo } from 'react';
import type { EditorDocument } from './document';
import { Editor } from './editor';

export type ViewerProps = Omit<ComponentProps<'article'>, 'children'> & {
  value: EditorDocument;
  headingOffset?: number;
  headingIds?: string[];
  links?: boolean;
};

/** The official Editor.js read-only surface shares every block tool with Editor. */
export function Viewer({
  value,
  headingOffset = 0,
  headingIds = [],
  links = true,
  className,
  ...props
}: ViewerProps) {
  const presentation = useMemo(() => {
    let headingIndex = 0;
    const anchors: (string | undefined)[] = [];
    const blocks = value.blocks.map((block) => {
      if (block.type !== 'header') return block;
      const level = Math.max(1, Math.min(6, Number(block.data.level) || 2));
      anchors.push(level <= 3 ? headingIds[headingIndex++] : undefined);
      return {
        ...block,
        data: { ...block.data, level: Math.min(6, level + headingOffset) },
      };
    });
    return { document: { ...value, blocks }, anchors };
  }, [value, headingOffset, headingIds]);
  return (
    <article
      {...props}
      data-slot="viewer"
      className={cn('min-w-0 w-full max-w-full', className)}
    >
      <Editor
        value={presentation.document}
        readOnly
        links={links}
        headingIds={presentation.anchors}
        label="正文阅读器"
      />
    </article>
  );
}
