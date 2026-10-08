'use client';

import type { ReactNode } from 'react';
import { DeferredContent } from '@/components/layout/deferred-content';
import { Skeleton } from '@/components/ui/skeleton';

export function ChartLoading() {
  return (
    <Skeleton
      aria-label="图表加载中"
      role="status"
      className="aspect-video w-full md:aspect-[3/1]"
    />
  );
}

export function DeferredChart({ children }: { children: ReactNode }) {
  return (
    <DeferredContent placeholder={<ChartLoading />}>{children}</DeferredContent>
  );
}
