'use client';

import { List } from '@phosphor-icons/react';
import { cn } from 'cn';
import Link from 'next/link';
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

function cleanHeadingText(value: string) {
  return value
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/<[^>]+>/g, '')
    .replace(/[*_`~]/g, '')
    .trim();
}

export function extractMarkdownHeadings(markdown: string): MarkdownHeading[] {
  const headings: MarkdownHeading[] = [];
  let inCodeBlock = false;

  for (const line of markdown.split(/\r?\n/)) {
    if (/^\s*(```|~~~)/.test(line)) {
      inCodeBlock = !inCodeBlock;
      continue;
    }

    if (inCodeBlock) {
      continue;
    }

    const match = /^\s*(#{1,3})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!match) {
      continue;
    }

    const text = cleanHeadingText(match[2]);
    if (!text) {
      continue;
    }

    headings.push({
      id: `screenplay-heading-${headings.length}`,
      level: match[1].length as MarkdownHeading['level'],
      text,
    });
  }

  return headings;
}

export function ScreenplayDocumentToc({
  headings,
}: {
  headings: MarkdownHeading[];
}) {
  return (
    <NavigationMenu
      aria-labelledby="screenplay-toc-title"
      className="block max-w-none flex-none lg:grid lg:h-full lg:min-h-0 lg:items-stretch lg:justify-stretch lg:grid-rows-[auto_minmax(0,1fr)] lg:overflow-hidden"
      orientation="vertical"
      viewport={false}
    >
      <div className="flex items-center justify-between gap-4 pb-3">
        <div className="flex items-center gap-2">
          <List
            aria-hidden
            className="size-4 text-muted-foreground"
            weight="regular"
          />
          <h2 className="text-sm font-medium" id="screenplay-toc-title">
            目录
          </h2>
        </div>
        {headings.length ? (
          <span className="text-xs text-muted-foreground">
            {headings.length} 节
          </span>
        ) : null}
      </div>

      {headings.length ? (
        <div className="mt-3 min-h-0 overflow-y-auto overscroll-contain scrollbar-thin">
          <NavigationMenuList className="w-full flex-none flex-col items-stretch justify-start gap-0.5">
            {headings.map((heading) => (
              <NavigationMenuItem key={heading.id}>
                <NavigationMenuLink
                  asChild
                  className={cn(
                    'block rounded-md py-1.5 text-sm leading-5 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    heading.level === 1
                      ? 'px-3'
                      : heading.level === 2
                        ? 'pr-3 pl-6 text-[13px]'
                        : 'pr-3 pl-9 text-xs',
                  )}
                >
                  <Link href={`#${heading.id}`}>{heading.text}</Link>
                </NavigationMenuLink>
              </NavigationMenuItem>
            ))}
          </NavigationMenuList>
        </div>
      ) : (
        <p className="mt-4 text-sm leading-6 text-muted-foreground">
          当前文档没有可用的标题目录。
        </p>
      )}
    </NavigationMenu>
  );
}
