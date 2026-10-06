'use client';

import Link from 'next/link';
import { isDownloadEnabled } from '@/components/providers/provider-availability';
import { useProviderStatuses } from '@/components/providers/use-provider-statuses';
import { ItemDescription } from '@/components/ui/item';

export function SupportedPlatforms() {
  const state = useProviderStatuses();
  const names =
    state.error || state.loading
      ? []
      : (state.data?.items ?? [])
          .filter(isDownloadEnabled)
          .slice(0, 5)
          .map((provider) => provider.display_name);

  return (
    <ItemDescription
      className="line-clamp-none"
      data-slot="supported-platforms"
    >
      {names.length
        ? `支持 ${names.join('、')} 等平台的公开内容`
        : '支持多个平台的公开内容'}
      {' · '}
      <Link href="/providers">查看平台状态</Link>
    </ItemDescription>
  );
}
