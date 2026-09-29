'use client';

import { cn } from 'cn';
import Link from 'next/link';
import { useSyncExternalStore } from 'react';
import { QuickParseDialog } from '@/components/intake/quick-parse-dialog';
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from '@/components/ui/navigation-menu';
import { siteConfig } from '@/lib/site';

const desktopFooterQuery = '(min-width: 1024px)';

function subscribeToDesktopViewport(onChange: () => void) {
  if (typeof window.matchMedia !== 'function') return () => undefined;
  const media = window.matchMedia(desktopFooterQuery);
  media.addEventListener('change', onChange);
  return () => media.removeEventListener('change', onChange);
}

function isDesktopViewport() {
  return typeof window.matchMedia !== 'function'
    ? true
    : window.matchMedia(desktopFooterQuery).matches;
}

export function SiteFooter({ className }: { className?: string }) {
  const showFooterActions = useSyncExternalStore(
    subscribeToDesktopViewport,
    isDesktopViewport,
    () => false,
  );

  return (
    <footer className={cn('shrink-0 bg-card', className)}>
      <div className="content-shell flex min-h-16 flex-wrap items-center justify-between gap-x-8 gap-y-3 py-5 text-sm text-muted-foreground">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <Link className="focus-ring font-medium text-foreground" href="/">
            帧取 · FrameFetch
          </Link>
          <span>
            <Link className="focus-ring" href={siteConfig.licenseUrl}>
              MIT 开源
            </Link>{' '}
            · 请仅处理已获授权内容
          </span>
        </div>
        {showFooterActions ? (
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <QuickParseDialog />
            <NavigationMenu
              aria-label="项目链接"
              className="min-w-0 max-w-none"
              viewport={false}
            >
              <NavigationMenuList className="flex-wrap justify-start gap-x-4 gap-y-2">
                <FooterLink href="/guide/">使用指南</FooterLink>
                <FooterLink href="/self-hosting/">自托管部署</FooterLink>
                <FooterLink href="/about/">关于</FooterLink>
                <FooterLink href={siteConfig.repositoryUrl}>GitHub</FooterLink>
                <FooterLink href={`${siteConfig.repositoryUrl}/tree/main/docs`}>
                  文档
                </FooterLink>
              </NavigationMenuList>
            </NavigationMenu>
          </div>
        ) : null}
      </div>
    </footer>
  );
}

function FooterLink({ children, href }: { children: string; href: string }) {
  return (
    <NavigationMenuItem>
      <NavigationMenuLink asChild className="focus-ring">
        <Link href={href}>{children}</Link>
      </NavigationMenuLink>
    </NavigationMenuItem>
  );
}

export default SiteFooter;
