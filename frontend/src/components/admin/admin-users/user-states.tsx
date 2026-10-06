import { UserList } from '@phosphor-icons/react';

import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { Skeleton } from '@/components/ui/skeleton';

export function AdminSkeleton({ rowsOnly = false }: { rowsOnly?: boolean }) {
  return (
    <div
      aria-label="正在加载用户列表"
      className="flex flex-col gap-6"
      role="status"
    >
      {!rowsOnly && (
        <>
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-20 w-full max-w-2xl" />
          <Skeleton className="h-16 w-full" />
        </>
      )}
      <div className="flex flex-col gap-2">
        {['first', 'second', 'third', 'fourth', 'fifth'].map((row) => (
          <div key={row}>
            <Skeleton className="h-12 w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function UsersLoadError({
  error,
  onRetry,
}: {
  error: string;
  onRetry: () => void;
}) {
  return (
    <PageErrorNotice
      message={error}
      onRetry={onRetry}
      retryLabel="重新加载"
      title="暂时无法读取用户列表"
    />
  );
}

export function EmptyUsers() {
  return (
    <PageEmptyNotice
      compact
      description="尝试清空搜索词或更换筛选条件。"
      icon={<UserList aria-hidden />}
      title="没有匹配的用户"
    />
  );
}

export function UnauthenticatedUsers() {
  return (
    <PageErrorNotice
      message="登录状态已失效，无法读取用户列表。"
      title="暂时无法读取用户列表"
    />
  );
}
