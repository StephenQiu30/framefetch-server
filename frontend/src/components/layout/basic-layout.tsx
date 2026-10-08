'use client';

import dynamic from 'next/dynamic';
import { usePathname } from 'next/navigation';
import { type ReactNode, useState } from 'react';

import { NavigationHistoryProvider } from '@/components/layout/navigation-history';
import SiteFooter from '@/components/layout/site-footer';
import SiteHeader from '@/components/layout/site-header';
import { Button } from '@/components/ui/button';

const ContentMotion = dynamic(
  () => import('@/components/layout/content-motion'),
  { ssr: false },
);

export function BasicLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? '/';
  const [main, setMain] = useState<HTMLElement | null>(null);

  return (
    <NavigationHistoryProvider currentPath={pathname}>
      <div
        className="flex min-h-svh flex-col bg-background text-foreground"
        data-slot="basic-layout"
      >
        <Button
          asChild
          className="fixed left-4 top-0 z-50 -translate-y-full focus-visible:top-3 focus-visible:translate-y-0"
          size="lg"
        >
          <a href="#main-content">跳到主要内容</a>
        </Button>
        <SiteHeader />
        <main
          ref={setMain}
          className="content-shell flex flex-1 flex-col"
          data-slot="basic-layout-main"
          id="main-content"
          tabIndex={-1}
        >
          {children}
          {main ? <ContentMotion scope={main} contentKey={pathname} /> : null}
        </main>
        <SiteFooter />
      </div>
    </NavigationHistoryProvider>
  );
}
