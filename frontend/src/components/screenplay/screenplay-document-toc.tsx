'use client';

import { List } from '@phosphor-icons/react';
import { cn } from 'cn';
import Link from 'next/link';
import { markdownToEditorDocument } from '@/components/editor/document';
import { richTextToPlainText } from '@/components/editor/rich-text';
import { ItemDescription, ItemTitle } from '@/components/ui/item';
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from '@/components/ui/navigation-menu';

export type MarkdownHeading = {
  id: string;
  level: 1 | 2 | 3;
  text: string;
};

export function extractMarkdownHeadings(markdown: string): MarkdownHeading[] {
  return markdownToEditorDocument(markdown)
    .blocks.filter((block) => block.type === 'header' && block.data.level <= 3)
    .map((block, index) => ({
      id: `screenplay-heading-${index}`,
      level: block.data.level as MarkdownHeading['level'],
      text: richTextToPlainText(block.data.text),
    }));
}

export function ScreenplayDocumentToc({
  headings,
}: {
  headings: MarkdownHeading[];
}) {
  return (
    <NavigationMenu
      aria-labelledby="screenplay-toc-title"
      className="block max-w-none flex-none"
      orientation="vertical"
      viewport={false}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <List aria-hidden weight="regular" />
          <ItemTitle className="line-clamp-none">
            <h2 id="screenplay-toc-title">目录</h2>
          </ItemTitle>
        </div>
        {headings.length ? <span>{headings.length} 节</span> : null}
      </div>

      {headings.length ? (
        <div className="mt-3">
          <NavigationMenuList className="w-full flex-none flex-col items-stretch justify-start gap-0.5">
            {headings.map((heading) => (
              <NavigationMenuItem key={heading.id}>
                <NavigationMenuLink
                  asChild
                  className={cn(
                    'min-w-0',
                    heading.level === 2 && 'ml-3',
                    heading.level === 3 && 'ml-6',
                  )}
                >
                  <Link className="break-words" href={`#${heading.id}`}>
                    {heading.text}
                  </Link>
                </NavigationMenuLink>
              </NavigationMenuItem>
            ))}
          </NavigationMenuList>
        </div>
      ) : (
        <ItemDescription className="line-clamp-none mt-4">
          当前文档没有可用的标题目录。
        </ItemDescription>
      )}
    </NavigationMenu>
  );
}
