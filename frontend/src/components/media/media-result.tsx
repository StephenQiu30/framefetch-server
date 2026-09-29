import type { ReactNode } from 'react';
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
export const mediaResultGridClassName =
  'grid items-start gap-10 lg:grid-cols-[minmax(0,1.55fr)_minmax(320px,1fr)] lg:items-stretch lg:gap-14';
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
    <div className={mediaResultGridClassName} data-slot="media-result">
      <Card
        className={borderlessCardClassName}
        data-media-result-column="media"
      >
        <CardContent className="px-0">{frame}</CardContent>
        <CardHeader className="mt-5 px-0">
          <CardTitle>
            <Heading className="break-words text-pretty text-xl font-semibold leading-7 tracking-[-0.03em] sm:text-2xl sm:leading-8">
              {title}
            </Heading>
          </CardTitle>
          <CardDescription>{metadata}</CardDescription>
        </CardHeader>
      </Card>
      <Card
        className={`${borderlessCardClassName} lg:pt-1`}
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
          className={
            panel
              ? 'mt-5 flex min-h-0 flex-1 flex-col px-0'
              : 'flex min-h-0 flex-1 flex-col px-0'
          }
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
    </div>
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
    <div aria-label={label} className={mediaResultGridClassName} role="status">
      <Card className={borderlessCardClassName}>
        <CardContent className="px-0">
          <AspectRatio ratio={mediaFrameAspectRatio}>
            <Skeleton className="size-full rounded-none" />
          </AspectRatio>
        </CardContent>
        <CardHeader className="mt-5 space-y-2 px-0">
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </CardHeader>
      </Card>
      <Card className={`${borderlessCardClassName} lg:pt-1`}>
        {selectionPanel ? (
          <CardHeader className="px-0">
            <Skeleton className="h-5 w-20" />
          </CardHeader>
        ) : null}
        <CardContent
          className={
            selectionPanel
              ? 'mt-5 flex-1 space-y-4 px-0'
              : 'flex-1 space-y-4 px-0'
          }
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
    </div>
  );
}
