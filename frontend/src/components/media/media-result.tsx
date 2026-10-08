import { cn } from 'cn';
import { SplitLayout } from '@/components/layout/split-layout';
import { mediaFrameAspectRatio } from '@/components/media/media-cover';
import { AspectRatio } from '@/components/ui/aspect-ratio';
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

// The media column and frame position stay the same from inspection through
// download and playback. Only the content inside the 16:9 frame changes.
const borderlessCardClassName =
  'min-w-0 gap-0 overflow-visible rounded-none bg-transparent py-0 ring-0';

export function MediaResultSkeleton({
  label,
  selectionPanel = false,
}: {
  label: string;
  selectionPanel?: boolean;
}) {
  return (
    <SplitLayout aria-label={label} columns="primary" role="status">
      <Card className={borderlessCardClassName}>
        <CardContent className="px-0">
          <AspectRatio ratio={mediaFrameAspectRatio}>
            <Skeleton className="size-full rounded-none" />
          </AspectRatio>
        </CardContent>
        <CardHeader className="mt-5 flex flex-col gap-2 px-0">
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </CardHeader>
      </Card>
      <Card
        className={cn(
          borderlessCardClassName,
          selectionPanel && 'lg:contain-size',
        )}
      >
        {selectionPanel ? (
          <CardHeader className="px-0">
            <Skeleton className="h-5 w-20" />
          </CardHeader>
        ) : null}
        <CardContent
          className={cn(
            'flex min-h-0 flex-1 flex-col gap-4 px-0',
            selectionPanel && 'mt-5',
          )}
        >
          {selectionPanel ? (
            <>
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-20 w-full" />
            </>
          ) : (
            <>
              <Skeleton className="h-5 w-20" />
              <Skeleton className="h-9 w-4/5" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-11 w-full" />
              <Skeleton className="h-11 w-3/4" />
            </>
          )}
        </CardContent>
        {selectionPanel ? (
          <CardFooter className="mt-auto rounded-none border-0 bg-transparent p-0 pt-7">
            <Skeleton className="h-8 w-full" />
          </CardFooter>
        ) : null}
      </Card>
    </SplitLayout>
  );
}
