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
  ...props
}: ComponentProps<'div'> & {
  columns?: keyof typeof columnVariants;
}) {
  return (
    <div
      data-slot="split-layout"
      className={cn(
        'grid min-w-0 items-stretch gap-10 *:min-w-0 lg:gap-14',
        columnVariants[columns],
        className,
      )}
      {...props}
    />
  );
}
