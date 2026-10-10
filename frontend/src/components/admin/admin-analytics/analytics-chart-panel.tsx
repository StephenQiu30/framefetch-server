'use client';

import { TableIcon } from '@phosphor-icons/react';
import type { ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';

export const ANALYTICS_CHART_ASPECT = 'aspect-[4/3] w-full';
export const ANALYTICS_TREND_ASPECT = 'aspect-[4/3] w-full sm:aspect-[4/1]';

export function AnalyticsChartPanel({
  children,
  details,
  detailsLabel,
  id,
  title,
}: {
  children: ReactNode;
  details?: ReactNode;
  detailsLabel?: string;
  id: string;
  title: string;
}) {
  return (
    <Collapsible className="h-full min-w-0">
      <Card className="min-w-0 h-full" aria-labelledby={`${id}-title`}>
        <CardHeader className="items-center">
          <CardTitle>
            <h2 id={`${id}-title`}>{title}</h2>
          </CardTitle>
          {details ? (
            <CardAction className="row-span-1 self-center">
              <CollapsibleTrigger asChild>
                <Button
                  aria-label={detailsLabel}
                  title={detailsLabel}
                  size="icon"
                  variant="ghost"
                >
                  <TableIcon aria-hidden />
                </Button>
              </CollapsibleTrigger>
            </CardAction>
          ) : null}
        </CardHeader>
        <CardContent>{children}</CardContent>
        {details ? (
          <CollapsibleContent>
            <CardContent>{details}</CardContent>
          </CollapsibleContent>
        ) : null}
      </Card>
    </Collapsible>
  );
}
