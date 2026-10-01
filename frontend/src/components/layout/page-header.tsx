import { cn } from 'cn';
import type { ReactNode } from 'react';

type PageHeaderProps = {
  action?: ReactNode;
  className?: string;
  description?: ReactNode;
  title: ReactNode;
  size?: 'default' | 'lg';
  titleClassName?: string;
  titleId?: string;
};

export function PageHeader({
  action,
  className,
  description,
  title,
  size = 'default',
  titleClassName,
  titleId,
}: PageHeaderProps) {
  return (
    <header
      data-slot="page-header"
      className={cn(
        'flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between sm:gap-8',
        className,
      )}
    >
      <div className="min-w-0 max-w-4xl">
        <h1
          className={cn(
            'text-balance font-medium tracking-tight',
            size === 'lg' ? 'text-3xl sm:text-4xl' : 'text-2xl sm:text-3xl',
            titleClassName,
          )}
          id={titleId}
        >
          {title}
        </h1>
        {description ? (
          <p
            className={cn(
              'mt-2 leading-6 text-muted-foreground',
              size === 'lg' ? 'text-base' : 'text-sm',
            )}
          >
            {description}
          </p>
        ) : null}
      </div>
      {action ? (
        <div className="w-full shrink-0 [&>*]:w-full sm:w-auto sm:pt-0.5 sm:[&>*]:w-auto">
          {action}
        </div>
      ) : null}
    </header>
  );
}
