import { Skeleton } from '@/components/ui/skeleton';

export function AnalyticsLoading({
  analysis = false,
  label = '正在加载下载分析',
}: {
  label?: string;
  analysis?: boolean;
}) {
  return (
    <div aria-label={label} className="flex flex-col gap-8" role="status">
      <span className="sr-only">{label}</span>
      <div aria-hidden className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {['total', 'rate', 'third', 'fourth'].map((key) => (
          <Skeleton className="h-32 w-full" key={key} />
        ))}
      </div>
      <Skeleton aria-hidden className="aspect-[4/3] w-full sm:aspect-[4/1]" />
      <div
        aria-hidden
        className={
          analysis ? 'grid gap-6 lg:grid-cols-2' : 'grid gap-6 lg:grid-cols-3'
        }
      >
        {(analysis ? ['first', 'second'] : ['first', 'second', 'third']).map(
          (key) => (
            <Skeleton className="aspect-[4/3] w-full" key={key} />
          ),
        )}
      </div>
    </div>
  );
}
