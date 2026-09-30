import { cn } from 'cn';
import type { ReactNode } from 'react';
import { SplitLayout } from '@/components/layout/split-layout';
import { mediaFrameAspectRatio } from '@/components/media/media-cover';
import { AspectRatio } from '@/components/ui/aspect-ratio';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

// The media column and frame position stay the same from inspection through
// download and playback. Only the content inside the 16:9 frame changes.
const borderlessCardClassName =
  'min-w-0 gap-0 overflow-visible rounded-none bg-transparent py-0 ring-0';

export function MediaResult({
  actions,
  headingLevel,
  media,
  metadata,
  panel,
  title,
}: {
  actions: ReactNode;
  headingLevel: 1 | 2;
  media: ReactNode;
  metadata: ReactNode;
  panel?: { title: string; footer?: ReactNode };
  title: string;
}) {
  const Heading = headingLevel === 1 ? 'h1' : 'h2';
  const frame = (
    <div className="w-full" data-slot="media-result-frame">
      {media}
    </div>
  );

  return (
    <SplitLayout columns="primary" data-slot="media-result">
      <Card
        className={borderlessCardClassName}
        data-media-result-column="media"
      >
        <CardContent className="px-0">{frame}</CardContent>
        <CardHeader className="mt-5 px-0">
          <CardTitle>
            <Heading className="break-words text-pretty text-xl font-semibold leading-7 tracking-tight sm:text-2xl sm:leading-8">
              {title}
            </Heading>
          </CardTitle>
          <CardDescription>{metadata}</CardDescription>
        </CardHeader>
      </Card>
      <Card
        // Let the fixed media frame and its metadata determine the desktop row.
        // The selection list scrolls within the remaining panel space.
        className={cn(
          borderlessCardClassName,
          'lg:pt-1',
          panel && 'lg:contain-size',
        )}
        data-media-result-column="actions"
      >
        {panel ? (
          <CardHeader className="px-0">
            <CardTitle>
              <h2>{panel.title}</h2>
            </CardTitle>
          </CardHeader>
        ) : null}
        <CardContent
          className={cn('flex min-h-0 flex-1 flex-col px-0', panel && 'mt-5')}
        >
          {actions}
        </CardContent>
        {panel?.footer ? (
          <CardFooter
            className="mt-auto rounded-none border-0 bg-transparent p-0 pt-7"
            data-media-result-footer=""
          >
            {panel.footer}
          </CardFooter>
        ) : null}
      </Card>
    </SplitLayout>
  );
}

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
          'lg:pt-1',
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
            <Skeleton className="h-11 w-full" />
          </CardFooter>
        ) : null}
      </Card>
    </SplitLayout>
  );
}
