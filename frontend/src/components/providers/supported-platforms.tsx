'use client';

import { ShieldCheckIcon } from '@phosphor-icons/react';
import Link from 'next/link';
import { isDownloadEnabled } from '@/components/providers/provider-availability';
import { useProviderStatuses } from '@/components/providers/use-provider-statuses';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';

export function SupportedPlatforms() {
  const state = useProviderStatuses();
  const enabled = (state.data?.items ?? []).filter(isDownloadEnabled);

  return (
    <aside aria-label="身份与平台" className="flex flex-col gap-8">
      <Item variant="muted">
        <ItemMedia variant="icon">
          <ShieldCheckIcon aria-hidden />
        </ItemMedia>
        <ItemContent>
          <ItemTitle>平台身份来自你的 Chrome</ItemTitle>
          <ItemDescription>
            需要登录的平台使用 FrameFetch 扩展提供的 Chrome
            登录态，公开内容无需登录。
          </ItemDescription>
        </ItemContent>
        <ItemActions className="basis-full">
          <Button asChild variant="outline">
            <Link href="/providers">查看平台状态</Link>
          </Button>
        </ItemActions>
      </Item>

      <section
        aria-labelledby="supported-platforms-title"
        className="flex flex-col gap-3"
      >
        <h2 className="text-base font-medium" id="supported-platforms-title">
          支持的平台
        </h2>
        {state.loading && !state.data ? (
          <div aria-hidden className="flex flex-wrap gap-2">
            {['a', 'b', 'c', 'd', 'e', 'f'].map((key) => (
              <Skeleton className="h-5 w-16" key={key} />
            ))}
          </div>
        ) : null}
        {state.error && !state.data ? (
          <p className="text-sm text-muted-foreground">
            平台列表暂时无法加载。{' '}
            <Button onClick={state.retry} size="sm" variant="link">
              重试
            </Button>
          </p>
        ) : null}
        {enabled.length ? (
          <ul aria-label="可下载的平台" className="flex flex-wrap gap-2">
            {enabled.map((provider) => (
              <li key={provider.key}>
                <Badge variant="secondary">{provider.display_name}</Badge>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="text-sm leading-6 text-muted-foreground">
          只处理公开、免费、非 DRM
          的内容；受保护的视频会如实提示，并引导改用本地视频导入。
        </p>
      </section>
    </aside>
  );
}
