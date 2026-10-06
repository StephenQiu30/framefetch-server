'use client';

import { CaretDownIcon } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { ItemDescription, ItemTitle } from '@/components/ui/item';

import { formatInteger } from './analytics-format';
import { SourcePerformanceDetails } from './source-performance-details';

type Source = API.DownloadAnalyticsResponse['sources'][number];

export function SourcePerformance({ sources }: { sources: Source[] }) {
  const sorted = [...sources].sort((left, right) => right.total - left.total);
  if (sorted.length === 0) return null;

  return (
    <Collapsible>
      <div>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <ItemTitle className="line-clamp-none">
              <h2 id="source-performance-title">来源明细</h2>
            </ItemTitle>
            <ItemDescription className="line-clamp-none mt-1">
              需要精确对比时，再展开各视频源的完整数据。
            </ItemDescription>
          </div>
          <CollapsibleTrigger asChild>
            <Button
              className="group w-full justify-between sm:w-auto"
              type="button"
              variant="ghost"
            >
              查看 {formatInteger(sorted.length)} 个来源
              <CaretDownIcon
                aria-hidden
                className="transition-transform group-data-[state=open]:rotate-180"
              />
            </Button>
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent>
          <SourcePerformanceDetails sources={sorted} />
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
