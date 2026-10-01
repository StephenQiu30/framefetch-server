import {
  BookOpenIcon,
  ChartLineUpIcon,
  ClockCounterClockwiseIcon,
  DesktopTowerIcon,
  FileTextIcon,
  GithubLogoIcon,
  HardDrivesIcon,
  HouseIcon,
  InfoIcon,
  ListBulletsIcon,
  PulseIcon,
  RobotIcon,
  StackIcon,
  UserCircleIcon,
  UserPlusIcon,
  UsersThreeIcon,
} from '@phosphor-icons/react';
import { type ReactNode, useId } from 'react';

import { MobileNavigationLink as MobileLink } from '@/components/layout/mobile-navigation-link';
import { NavigationMenuList } from '@/components/ui/navigation-menu';
import { siteConfig } from '@/lib/site';

export function MobileNavigationItems({
  pathname,
  user,
}: {
  pathname: string;
  user?: API.UserResponse;
}) {
  return (
    <div className="grid gap-6 px-4 pb-4">
      <MobileNavigationSection title="工作区">
        <MobileLink active={pathname === '/'} href="/">
          <HouseIcon aria-hidden />
          首页
        </MobileLink>
        <MobileLink active={pathname === '/history'} href="/history">
          <ClockCounterClockwiseIcon aria-hidden />
          下载记录
        </MobileLink>
        <MobileLink
          active={pathname.startsWith('/documents')}
          href="/documents"
        >
          <FileTextIcon aria-hidden />
          剧本文档
        </MobileLink>
        <MobileLink
          active={pathname.startsWith('/providers')}
          href="/providers"
        >
          <PulseIcon aria-hidden />
          平台状态
        </MobileLink>
        {user ? (
          <>
            <MobileLink
              active={pathname.startsWith('/history/activity')}
              href="/history/activity"
            >
              <ListBulletsIcon aria-hidden />
              我的处理记录
            </MobileLink>
            <MobileLink
              active={pathname.startsWith('/account')}
              href="/account"
            >
              <UserCircleIcon aria-hidden />
              个人资料
            </MobileLink>
          </>
        ) : (
          <>
            <MobileLink
              href={`/user/login?redirect=${encodeURIComponent(pathname)}`}
            >
              <UserCircleIcon aria-hidden />
              登录账户
            </MobileLink>
            <MobileLink href="/user/register">
              <UserPlusIcon aria-hidden />
              注册账户
            </MobileLink>
          </>
        )}
      </MobileNavigationSection>
      {user?.role === 'admin' ? (
        <MobileNavigationSection title="管理">
          <MobileLink
            active={pathname.startsWith('/admin/operation-logs')}
            href="/admin/operation-logs"
          >
            <ListBulletsIcon aria-hidden />
            系统操作日志
          </MobileLink>
          <MobileLink
            active={pathname.startsWith('/admin/ai-providers')}
            href="/admin/ai-providers"
          >
            <RobotIcon aria-hidden />
            AI 服务
          </MobileLink>
          <MobileLink
            active={pathname.startsWith('/admin/analytics')}
            href="/admin/analytics"
          >
            <ChartLineUpIcon aria-hidden />
            下载分析
          </MobileLink>
          <MobileLink
            active={pathname.startsWith('/admin/files')}
            href="/admin/files"
          >
            <HardDrivesIcon aria-hidden />
            文件管理
          </MobileLink>
          <MobileLink
            active={pathname.startsWith('/admin/providers')}
            href="/admin/providers"
          >
            <StackIcon aria-hidden />
            平台目录
          </MobileLink>
          <MobileLink
            active={pathname.startsWith('/admin/users')}
            href="/admin/users"
          >
            <UsersThreeIcon aria-hidden />
            用户管理
          </MobileLink>
        </MobileNavigationSection>
      ) : null}
      <MobileNavigationSection title="资源">
        <MobileLink active={pathname.startsWith('/guide')} href="/guide/">
          <BookOpenIcon aria-hidden />
          使用指南
        </MobileLink>
        <MobileLink
          active={pathname.startsWith('/self-hosting')}
          href="/self-hosting/"
        >
          <DesktopTowerIcon aria-hidden />
          自托管部署
        </MobileLink>
        <MobileLink active={pathname.startsWith('/about')} href="/about/">
          <InfoIcon aria-hidden />
          关于
        </MobileLink>
        <MobileLink href={siteConfig.repositoryUrl}>
          <GithubLogoIcon aria-hidden />
          GitHub
        </MobileLink>
        <MobileLink href={`${siteConfig.repositoryUrl}/tree/main/docs`}>
          <FileTextIcon aria-hidden />
          文档
        </MobileLink>
      </MobileNavigationSection>
    </div>
  );
}

function MobileNavigationSection({
  children,
  title,
}: {
  children: ReactNode;
  title: string;
}) {
  const titleId = useId();

  return (
    <section aria-labelledby={titleId} className="grid gap-2">
      <h3 className="text-xs font-medium text-muted-foreground" id={titleId}>
        {title}
      </h3>
      <NavigationMenuList className="grid w-full flex-none justify-stretch gap-1">
        {children}
      </NavigationMenuList>
    </section>
  );
}
