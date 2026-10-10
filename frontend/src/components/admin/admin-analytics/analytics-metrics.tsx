'use client';
import { InfoIcon } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Item, ItemContent, ItemGroup, ItemTitle } from '@/components/ui/item';
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverTrigger,
} from '@/components/ui/popover';

export function AnalyticsMetrics({
  label,
  metrics,
}: {
  label: string;
  metrics: { label: string; value: string; detail: string }[];
}) {
  return (
    <ItemGroup
      aria-label={label}
      className="grid grid-cols-2 gap-4 lg:grid-cols-4"
    >
      {metrics.map((metric) => (
        <Item
          variant="muted"
          className="min-w-0 items-start"
          key={metric.label}
          role="listitem"
        >
          <ItemContent className="gap-2">
            <ItemTitle className="flex w-full items-center justify-between gap-2">
              {metric.label}
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    aria-label={`${metric.label}说明`}
                    size="icon-sm"
                    variant="ghost"
                  >
                    <InfoIcon aria-hidden />
                  </Button>
                </PopoverTrigger>
                <PopoverContent
                  align="start"
                  aria-label={`${metric.label}说明`}
                >
                  <PopoverDescription>{metric.detail}</PopoverDescription>
                </PopoverContent>
              </Popover>
            </ItemTitle>
            <p className="text-2xl font-medium tracking-tight tabular-nums sm:text-3xl">
              {metric.value}
            </p>
            <span className="sr-only">{metric.detail}</span>
          </ItemContent>
        </Item>
      ))}
    </ItemGroup>
  );
}
