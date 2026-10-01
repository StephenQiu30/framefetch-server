'use client';

import { ListIcon, SignOutIcon } from '@phosphor-icons/react';
import { useRef } from 'react';

import { MobileNavigationItems } from '@/components/layout/mobile-navigation-items';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { NavigationMenu } from '@/components/ui/navigation-menu';
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { Spinner } from '@/components/ui/spinner';
import { avatarUrl } from '@/lib/avatar';

type MobileNavigationProps = {
  loading: boolean;
  onSignOut: () => Promise<void>;
  pathname: string;
  signingOut: boolean;
  user?: API.UserResponse;
};

export function MobileNavigation({
  loading,
  onSignOut,
  pathname,
  signingOut,
  user,
}: MobileNavigationProps) {
  const navigationTitleRef = useRef<HTMLHeadingElement>(null);

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          aria-label="打开导航菜单"
          className="lg:hidden"
          disabled={loading}
          size="icon"
          variant="ghost"
        >
          <ListIcon aria-hidden />
        </Button>
      </SheetTrigger>
      <SheetContent
        className="max-h-dvh overflow-hidden"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          navigationTitleRef.current?.focus();
        }}
        side="right"
      >
        <SheetHeader className="shrink-0">
          <SheetTitle ref={navigationTitleRef} tabIndex={-1}>
            导航
          </SheetTitle>
          <SheetDescription>访问工作区、账户与使用资源。</SheetDescription>
        </SheetHeader>
        {user ? (
          <div className="flex shrink-0 items-center gap-3 px-4">
            <Avatar size="lg">
              <AvatarImage alt="" src={avatarUrl(user)} />
              <AvatarFallback>
                {user.username.slice(0, 1).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <p className="truncate font-medium">{user.username}</p>
              <p className="truncate text-xs text-muted-foreground">
                {user.email}
              </p>
            </div>
          </div>
        ) : null}
        <NavigationMenu
          aria-label="移动导航"
          className="block min-h-0 max-w-none flex-1 overflow-y-auto overscroll-contain"
          orientation="vertical"
          viewport={false}
        >
          <MobileNavigationItems pathname={pathname} user={user} />
        </NavigationMenu>
        {user ? (
          <SheetFooter className="shrink-0">
            <SheetClose asChild>
              <Button
                className="w-full justify-start"
                disabled={signingOut}
                onClick={() => void onSignOut()}
                variant="ghost"
              >
                {signingOut ? (
                  <Spinner aria-hidden data-icon="inline-start" />
                ) : (
                  <SignOutIcon aria-hidden data-icon="inline-start" />
                )}
                {signingOut ? '正在退出…' : '退出登录'}
              </Button>
            </SheetClose>
          </SheetFooter>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
