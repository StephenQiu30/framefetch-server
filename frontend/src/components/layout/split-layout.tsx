import { cn } from 'cn';
import type { ComponentProps } from 'react';

const columnVariants = {
  equal: 'lg:grid-cols-2',
  primary: 'lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]',
  'sidebar-start': 'lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]',
  'sidebar-end': 'lg:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]',
};

/** Both columns share one grid row; content determines its height. */
export function SplitLayout({
  className,
  columns = 'equal',
  scrollable = false,
  ...props
}: ComponentProps<'div'> & {
  columns?: keyof typeof columnVariants;
  scrollable?: boolean;
}) {
  return (
    <div
      data-slot="split-layout"
      data-motion-group
      className={cn(
        'grid min-w-0 items-stretch gap-10 *:min-w-0 lg:gap-14',
        columnVariants[columns],
        scrollable &&
          'lg:max-h-dvh lg:grid-rows-[minmax(0,1fr)] lg:overflow-hidden lg:*:min-h-0 lg:*:overflow-hidden',
        className,
      )}
      {...props}
    />
  );
}
