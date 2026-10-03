'use client';

import { cn } from 'cn';
import Image from 'next/image';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';
import { AuthStatusCode, useAuth } from '@/components/auth/auth-provider';
import { DesktopNavigation } from '@/components/layout/desktop-navigation';
import { HeaderAccount } from '@/components/layout/header-account';
import { MobileNavigation } from '@/components/layout/mobile-navigation';
import { ThemeToggle } from '@/components/layout/theme-toggle';
import { Button } from '@/components/ui/button';
import { displayError } from '@/lib/request-error';
import { isPublicPage } from '@/lib/site';

function BrandLink({ className }: { className?: string }) {
  return (
    <Link
      aria-label="帧取首页"
      className={cn(
        'focus-ring inline-flex min-h-9 items-center gap-3 rounded-md text-lg font-semibold tracking-tight',
        className,
      )}
      href="/"
    >
      <Image
        alt=""
        aria-hidden
        className="size-8 shrink-0"
        height={32}
        // Always above the fold: lazy loading made the brand mark pop in
        // after every navigation.
        loading="eager"
        src="/logo.svg"
        width={32}
      />
      <span>帧取</span>
    </Link>
  );
}

function SiteHeader() {
  const { user, loading, status, signOut } = useAuth();
  const [signingOut, setSigningOut] = useState(false);
  const pathname = usePathname() ?? '/';
  const router = useRouter();
  const homeActive = pathname === '/';
  const publicPage = isPublicPage(pathname);
  const authView = pathname.startsWith('/user/');
  const historyActive = pathname === '/history';
  const documentsActive = pathname.startsWith('/documents');
  const providersActive = pathname.startsWith('/providers');
  const analyticsActive = pathname.startsWith('/admin/analytics');
  const filesActive = pathname.startsWith('/admin/files');
  const aiProvidersActive = pathname.startsWith('/admin/ai-providers');
  const catalogActive = pathname.startsWith('/admin/providers');
  const usersActive = pathname.startsWith('/admin/users');
  const headerAuthPending =
    !user && (loading || status === AuthStatusCode.Unknown);
  const publicView = publicPage && status === AuthStatusCode.Anonymous;

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await signOut();
      router.replace('/user/login');
      router.refresh();
    } catch (error) {
      toast.error(displayError(error));
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <header className="sticky top-0 z-40 bg-background">
      <div className="content-shell flex h-16 items-center justify-between">
        <BrandLink />
        <div
          aria-busy={(headerAuthPending && loading) || undefined}
          className="flex min-w-0 shrink-0 items-center justify-end gap-2"
          data-slot="header-actions"
        >
          {headerAuthPending ? (
            <div
              aria-hidden
              className="h-9 w-32"
              data-slot="header-auth-pending"
            />
          ) : (
            <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
              {authView ? (
                <ThemeToggle />
              ) : (
                <>
                  <div
                    className="hidden min-w-0 flex-1 items-center justify-end lg:flex"
                    data-slot="header-navigation"
                  >
                    <DesktopNavigation
                      contentActive={pathname.startsWith('/content')}
                      documentsActive={documentsActive}
                      historyActive={historyActive}
                      homeActive={homeActive}
                      providersActive={providersActive}
                      publicView={publicView}
                    />
                  </div>
                  <ThemeToggle />
                  {publicView ? (
                    <>
                      <div className="flex shrink-0 justify-end">
                        <Button asChild size="sm">
                          <Link href="/user/login">登录</Link>
                        </Button>
                      </div>
                      <MobileNavigation
                        loading={loading}
                        onSignOut={handleSignOut}
                        pathname={pathname}
                        signingOut={signingOut}
                      />
                    </>
                  ) : (
                    <>
                      <div className="hidden lg:block">
                        <HeaderAccount
                          analyticsActive={analyticsActive}
                          aiProvidersActive={aiProvidersActive}
                          catalogActive={catalogActive}
                          filesActive={filesActive}
                          loading={loading}
                          onSignOut={() => void handleSignOut()}
                          pathname={pathname}
                          signingOut={signingOut}
                          user={user}
                          usersActive={usersActive}
                        />
                      </div>
                      <MobileNavigation
                        loading={loading}
                        onSignOut={handleSignOut}
                        pathname={pathname}
                        signingOut={signingOut}
                        user={user}
                      />
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

export default SiteHeader;
