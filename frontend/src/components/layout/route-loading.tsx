import { Spinner } from '@/components/ui/spinner';

export function RouteLoading({ label = '正在加载页面' }: { label?: string }) {
  return (
    <div
      aria-label={label}
      className="flex flex-1 items-center justify-center gap-3 py-16 text-sm text-muted-foreground"
      data-slot="route-loading"
      role="status"
    >
      <Spinner aria-hidden role="presentation" />
      <span>{label}</span>
    </div>
  );
}
