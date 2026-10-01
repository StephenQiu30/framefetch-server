'use client';

import { useEffect } from 'react';

import { RouteErrorView } from '@/components/layout/route-error-view';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body data-design="borderless">
        <main className="flex min-h-svh flex-col bg-background px-6 text-foreground sm:px-10">
          <RouteErrorView error={error} reset={reset} />
        </main>
      </body>
    </html>
  );
}
