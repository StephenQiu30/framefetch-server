'use client';

import type { ReactNode } from 'react';

import { AuthStatusCode, useAuth } from '@/components/auth/auth-provider';
import { HomeStartup } from '@/components/intake/home-startup';
import { WorkspaceHome } from '@/components/intake/workspace-home';
import { PageErrorNotice } from '@/components/layout/page-error-notice';

type ResolvedHome = 'public' | 'workspace';

export function HomeExperience({
  publicHome,
  initialPublic = false,
}: {
  publicHome: ReactNode;
  initialPublic?: boolean;
}) {
  const { loading, user, status, sessionError, refreshUser } = useAuth();
  if (status === AuthStatusCode.Unknown && sessionError && !initialPublic) {
    return (
      <PageErrorNotice
        title="暂时无法确认登录状态"
        titleAs="h1"
        message={sessionError}
        onRetry={() => void refreshUser()}
      />
    );
  }
  const resolvedView: ResolvedHome | undefined = loading
    ? initialPublic
      ? 'public'
      : undefined
    : user
      ? 'workspace'
      : 'public';

  return (
    <div
      aria-busy={(loading && !resolvedView) || undefined}
      className="flex flex-1 flex-col"
      data-auth-pending={loading || undefined}
      data-home-phase={loading ? 'resolving' : 'ready'}
      data-slot="home-experience"
    >
      {resolvedView ? (
        <div data-home-view={resolvedView} data-slot="home-auth-content">
          {resolvedView === 'workspace' ? <WorkspaceHome /> : publicHome}
        </div>
      ) : (
        <HomeStartup />
      )}
    </div>
  );
}
