'use client';

import type { ReactNode } from 'react';
import { DeferredContent } from '@/components/layout/deferred-content';
import { Skeleton } from '@/components/ui/skeleton';
import {
  ANALYTICS_CHART_ASPECT,
  ANALYTICS_TREND_ASPECT,
} from './analytics-chart-panel';

export function ChartLoading({ trend = false }: { trend?: boolean }) {
  return (
    <Skeleton
      aria-label="图表加载中"
      role="status"
      className={trend ? ANALYTICS_TREND_ASPECT : ANALYTICS_CHART_ASPECT}
    />
  );
}

export function DeferredChart({
  children,
  trend = false,
}: {
  children: ReactNode;
  trend?: boolean;
}) {
  return (
    <DeferredContent placeholder={<ChartLoading trend={trend} />}>
      {children}
    </DeferredContent>
  );
}
