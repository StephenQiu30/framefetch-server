import type { ReactNode } from 'react';

import {
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from '@/components/ui/item';
import { TabsTrigger } from '@/components/ui/tabs';

type ScreenplayFinding =
  API.ScreenplayAnalysisResultResponse['dialogue_findings'][number];

export function FindingList({
  className = '',
  emptyMessage = '本项没有独立发现。',
  heading,
  items,
}: {
  className?: string;
  emptyMessage?: string;
  heading: string;
  items: ScreenplayFinding[];
}) {
  return (
    <div className={className}>
      <h3 className="mb-4 text-lg font-medium tracking-tight">{heading}</h3>
      {items.length ? (
        <ul className="flex flex-col gap-2">
          {items.map((item) => (
            <Item asChild className="block" key={item.id}>
              <li>
                <strong className="font-medium">{item.title}</strong>
                <p className="mt-2 leading-7 text-muted-foreground">
                  {item.description}
                </p>
              </li>
            </Item>
          ))}
        </ul>
      ) : (
        <p className="py-7 text-muted-foreground">{emptyMessage}</p>
      )}
    </div>
  );
}

export function Detail({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  return (
    <Item className="items-start" role="listitem">
      <ItemContent className="gap-1">
        <ItemTitle>{label}</ItemTitle>
        <ItemDescription className="line-clamp-none">
          {children}
        </ItemDescription>
      </ItemContent>
    </Item>
  );
}

export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl tabular-nums sm:text-2xl">{value}</p>
    </div>
  );
}

export function ResultTab({
  children,
  value,
}: {
  children: ReactNode;
  value: string;
}) {
  return <TabsTrigger value={value}>{children}</TabsTrigger>;
}

export function languageLabel(language: string) {
  if (language === 'zh-CN') return '简体中文';
  if (language === 'en-US') return 'English';
  if (language === 'mixed') return '中英混合';
  return '未知';
}
