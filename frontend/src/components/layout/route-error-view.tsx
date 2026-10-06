'use client';

import { cn } from 'cn';
import Link from 'next/link';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { Button } from '@/components/ui/button';
import { displayError } from '@/lib/request-error';

export function RouteErrorView({
  className,
  error,
  reset,
}: {
  className?: string;
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div
      className={cn('inner-page flex flex-col gap-8', className)}
      data-slot="route-error"
    >
      <div>
        <PageNavigation fallbackHref="/" />
        <PageHeader title="页面暂时无法打开。" />
      </div>
      <PageErrorNotice
        className="flex-1"
        message={displayError(error)}
        onRetry={reset}
        retryLabel="重新尝试"
        secondaryAction={
          <Button asChild variant="outline">
            <Link href="/">回到首页</Link>
          </Button>
        }
        title="页面暂时无法打开。"
        titleAs="h2"
      />
    </div>
  );
}
