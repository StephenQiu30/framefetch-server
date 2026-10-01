'use client';

import { usePathname, useRouter } from 'next/navigation';
import { type ReactNode, useEffect } from 'react';

import { AuthStatusCode, useAuth } from '@/components/auth/auth-provider';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { RouteLoading } from '@/components/layout/route-loading';

type ProtectedRouteProps = {
  children: ReactNode;
  requireAdmin?: boolean;
};

export function ProtectedRoute({
  children,
  requireAdmin = false,
}: ProtectedRouteProps) {
  const { user, loading, status, sessionError, refreshUser } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;

    if (status === AuthStatusCode.Anonymous) {
      const currentPath = `${pathname ?? '/'}${window.location.search}`;
      router.replace(`/user/login?redirect=${encodeURIComponent(currentPath)}`);
      return;
    }

    if (user && requireAdmin && user.role !== 'admin') router.replace('/');
  }, [loading, status, pathname, requireAdmin, router, user]);

  if (status === AuthStatusCode.Unknown && sessionError)
    return (
      <PageErrorNotice
        title="暂时无法确认登录状态"
        titleAs="h1"
        message={sessionError}
        onRetry={() => void refreshUser()}
      />
    );
  if (loading) return <RouteLoading label="正在恢复登录状态" />;
  if (!user || (requireAdmin && user.role !== 'admin')) {
    return <RouteLoading label="正在前往可访问页面" />;
  }

  return children;
}
