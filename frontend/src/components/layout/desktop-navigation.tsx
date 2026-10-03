import {
  ArrowUpRightIcon,
  ClockCounterClockwiseIcon,
  FileTextIcon,
  GithubLogoIcon,
  HouseIcon,
  PulseIcon,
} from '@phosphor-icons/react';
import Link from 'next/link';
import type { ReactNode } from 'react';
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  navigationMenuTriggerStyle,
} from '@/components/ui/navigation-menu';
import { siteConfig } from '@/lib/site';

type DesktopNavigationProps = {
  documentsActive: boolean;
  contentActive?: boolean;
  historyActive: boolean;
  homeActive: boolean;
  providersActive: boolean;
  publicView: boolean;
};

export function DesktopNavigation({
  documentsActive,
  contentActive,
  historyActive,
  homeActive,
  providersActive,
  publicView,
}: DesktopNavigationProps) {
  return (
    <NavigationMenu
      aria-label="主要导航"
      className="hidden max-w-none flex-none lg:flex"
      viewport={false}
    >
      <NavigationMenuList className="gap-2">
        {publicView ? (
          <>
            <NavigationLink href="/#capabilities">产品能力</NavigationLink>
            <NavigationLink href="/#architecture">自托管架构</NavigationLink>
            <NavigationLink href={siteConfig.repositoryUrl}>
              <GithubLogoIcon aria-hidden />
              GitHub
              <ArrowUpRightIcon aria-hidden />
            </NavigationLink>
          </>
        ) : (
          <>
            <NavigationLink active={homeActive} href="/">
              <HouseIcon aria-hidden />
              首页
            </NavigationLink>
            <NavigationLink active={historyActive} href="/history">
              <ClockCounterClockwiseIcon aria-hidden />
              下载记录
            </NavigationLink>
            <NavigationLink active={contentActive} href="/content">
              <FileTextIcon aria-hidden />
              内容创作
            </NavigationLink>
            <NavigationLink active={documentsActive} href="/documents">
              <FileTextIcon aria-hidden />
              剧本文档
            </NavigationLink>
            <NavigationLink active={providersActive} href="/providers">
              <PulseIcon aria-hidden />
              平台状态
            </NavigationLink>
          </>
        )}
      </NavigationMenuList>
    </NavigationMenu>
  );
}

function NavigationLink({
  active = false,
  children,
  href,
}: {
  active?: boolean;
  children: ReactNode;
  href: string;
}) {
  const external = href.startsWith('https://');

  return (
    <NavigationMenuItem>
      <NavigationMenuLink
        active={active}
        asChild
        className={navigationMenuTriggerStyle()}
      >
        <Link
          aria-current={active ? 'page' : undefined}
          href={href}
          rel={external ? 'noreferrer' : undefined}
          target={external ? '_blank' : undefined}
        >
          {children}
        </Link>
      </NavigationMenuLink>
    </NavigationMenuItem>
  );
}
