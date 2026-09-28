import { cn } from 'cn';
import type { ReactNode } from 'react';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

// The media column and frame position stay the same from inspection through
// download and playback. Only the content inside the 16:9 frame changes.
export const mediaResultGridClassName =
  'grid items-start gap-10 lg:grid-cols-[minmax(0,1.55fr)_minmax(320px,1fr)] lg:gap-14';

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
  const heading = (
    <Heading
      className={cn(
        'break-words text-pretty text-xl font-semibold leading-7 tracking-[-0.03em] sm:text-2xl sm:leading-8',
        !panel && 'mt-5',
      )}
    >
      {title}
    </Heading>
  );

  if (panel) {
    return (
      <div
        className={cn(mediaResultGridClassName, 'lg:items-stretch')}
        data-slot="media-result"
      >
        <Card className="min-w-0">
          <CardContent className="-mx-(--card-spacing) -mt-(--card-spacing)">
            {frame}
          </CardContent>
          <CardHeader>
            <CardTitle>{heading}</CardTitle>
            <CardDescription>{metadata}</CardDescription>
          </CardHeader>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>
              <h2>{panel.title}</h2>
            </CardTitle>
          </CardHeader>
          <CardContent className="min-h-0 flex-1">{actions}</CardContent>
          {panel.footer ? <CardFooter>{panel.footer}</CardFooter> : null}
        </Card>
      </div>
    );
  }

  return (
    <div className={mediaResultGridClassName} data-slot="media-result">
      <div className="min-w-0">
        {frame}
        {heading}
        {metadata}
      </div>
      <div className="min-w-0 lg:pt-1">{actions}</div>
    </div>
  );
}
