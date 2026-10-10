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
      <ItemTitle className="line-clamp-none">
        <h3 className="mb-4">{heading}</h3>
      </ItemTitle>
      {items.length ? (
        <ul className="flex flex-col gap-2">
          {items.map((item) => (
            <Item asChild className="block" key={item.id}>
              <li>
                <strong>{item.title}</strong>
                <ItemDescription className="line-clamp-none mt-2">
                  {item.description}
                </ItemDescription>
              </li>
            </Item>
          ))}
        </ul>
      ) : (
        <ItemDescription className="line-clamp-none">
          {emptyMessage}
        </ItemDescription>
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
        <ItemTitle className="line-clamp-none">{label}</ItemTitle>
        <ItemDescription className="line-clamp-none">
          {children}
        </ItemDescription>
      </ItemContent>
    </Item>
  );
}

export function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <ItemDescription className="line-clamp-none">{label}</ItemDescription>
      <ItemTitle className="line-clamp-none">
        <p className="mt-1 tabular-nums">{value}</p>
      </ItemTitle>
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
