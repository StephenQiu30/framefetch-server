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
      <Card className="min-w-0">
        <CardContent className="-mx-(--card-spacing) -mt-(--card-spacing)">
          {frame}
        </CardContent>
        <CardHeader>
          <CardTitle>
            <Heading className="break-words text-pretty text-xl font-semibold leading-7 tracking-[-0.03em] sm:text-2xl sm:leading-8">
              {title}
            </Heading>
          </CardTitle>
          <CardDescription>{metadata}</CardDescription>
        </CardHeader>
      </Card>
      <Card className="min-w-0">
        {panel ? (
          <CardHeader>
            <CardTitle>
              <h2>{panel.title}</h2>
            </CardTitle>
          </CardHeader>
        ) : null}
        <CardContent
          className={panel ? 'min-h-0 flex-1' : 'flex min-h-0 flex-1 flex-col'}
        >
          {actions}
        </CardContent>
        {panel?.footer ? <CardFooter>{panel.footer}</CardFooter> : null}
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
      <Card className="min-w-0">
        <CardContent className="-mx-(--card-spacing) -mt-(--card-spacing)">
          <AspectRatio ratio={mediaFrameAspectRatio}>
            <Skeleton className="size-full rounded-none" />
          </AspectRatio>
        </CardContent>
        <CardHeader>
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </CardHeader>
      </Card>
      <Card className="min-w-0">
        {selectionPanel ? (
          <CardHeader>
            <Skeleton className="h-5 w-20" />
          </CardHeader>
        ) : null}
        <CardContent className="flex-1 space-y-4">
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
          <CardFooter>
            <Skeleton className="h-11 w-full" />
          </CardFooter>
        ) : null}
      </Card>
    </div>
  );
}
