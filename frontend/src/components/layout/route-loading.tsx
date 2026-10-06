import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { SplitLayout } from '@/components/layout/split-layout';
import { Item, ItemContent, ItemTitle } from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';

export function RouteLoading({ label = '正在加载页面' }: { label?: string }) {
  return (
    <div
      className="inner-page flex flex-col gap-8"
      data-slot="route-loading"
      aria-busy
    >
      <div>
        <PageNavigation fallbackHref="/" />
        <PageHeader title={label} />
      </div>
      <Item role="status" aria-label={label} variant="muted">
        <Spinner aria-hidden role="presentation" />
        <ItemContent>
          <ItemTitle className="line-clamp-none">{label}</ItemTitle>
        </ItemContent>
      </Item>
      <SplitLayout aria-hidden>
        <Skeleton className="aspect-video w-full" />
        <div className="flex flex-col gap-4">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      </SplitLayout>
    </div>
  );
}
