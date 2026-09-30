'use client';

import { ImageIcon } from '@phosphor-icons/react';
import { cn } from 'cn';
import Image from 'next/image';
import { useEffect, useState } from 'react';
import { AspectRatio } from '@/components/ui/aspect-ratio';
import { Skeleton } from '@/components/ui/skeleton';
import {
  isPrivateThumbnailPath,
  loadPrivateThumbnail,
} from '@/lib/media-assets';

type MediaCoverProps = {
  alt: string;
  className?: string;
  compact?: boolean;
  fallback?: {
    detail?: string | null;
    eyebrow?: string | null;
    title?: string | null;
  };
  priority?: boolean;
  pending?: boolean;
  src?: string | null;
};

export const mediaFrameAspectRatio = 16 / 9;

export default function MediaCover({
  alt,
  className,
  compact = false,
  fallback,
  pending = false,
  priority = false,
  src,
}: MediaCoverProps) {
  const privateSource = isPrivateThumbnailPath(src);
  const [loadedPrivateSource, setLoadedPrivateSource] = useState<{
    objectUrl: string;
    source: string;
  } | null>(null);
  const [failedSource, setFailedSource] = useState<string | null>(null);

  useEffect(() => {
    if (!privateSource || !src) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setFailedSource(null);
    setLoadedPrivateSource(null);

    void loadPrivateThumbnail(src, controller.signal)
      .then((image) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(image);
        setLoadedPrivateSource({ objectUrl, source: src });
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailedSource(src);
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [privateSource, src]);

  const resolvedSource = privateSource
    ? loadedPrivateSource?.source === src
      ? loadedPrivateSource.objectUrl
      : null
    : src;
  const unavailable = !src || failedSource === src;
  const loading = Boolean(
    privateSource && src && !resolvedSource && !unavailable,
  );
  const generating = pending && !src;
  const fallbackTitle = fallback?.title?.trim() || alt;
  const fallbackEyebrow = fallback?.eyebrow?.trim() || '媒体内容';
  const fallbackDetail = fallback?.detail?.trim() || '封面未提供';
  return (
    <div
      className={cn(
        'media-frame min-w-0 overflow-hidden rounded-none bg-muted',
        className,
      )}
    >
      <AspectRatio ratio={mediaFrameAspectRatio}>
        {loading ? (
          <Skeleton
            aria-label={`${alt}（封面加载中）`}
            className="size-full rounded-none"
            role="img"
          />
        ) : generating ? (
          <Skeleton
            aria-label={`${alt}（封面生成中）`}
            className="flex size-full flex-col items-center justify-center gap-3 rounded-none"
            role="img"
          >
            <ImageIcon aria-hidden className="size-7" />
            <span className="text-xs">封面生成中</span>
          </Skeleton>
        ) : unavailable || !resolvedSource ? (
          <MediaCoverFallback
            compact={compact}
            detail={fallbackDetail}
            eyebrow={fallbackEyebrow}
            title={fallbackTitle}
          />
        ) : (
          <Image
            alt={alt}
            className="object-cover"
            fill
            onError={() => setFailedSource(src)}
            priority={priority}
            sizes="(min-width: 1024px) 50vw, 100vw"
            src={resolvedSource}
            unoptimized
          />
        )}
      </AspectRatio>
    </div>
  );
}

function MediaCoverFallback({
  compact,
  detail,
  eyebrow,
  title,
}: {
  compact: boolean;
  detail: string;
  eyebrow: string;
  title: string;
}) {
  return (
    <div
      aria-label={`${title}（暂无封面）`}
      className="relative size-full overflow-hidden bg-muted/60 text-foreground"
      role="img"
    >
      <div
        className={cn(
          'relative flex h-full min-w-0 flex-col justify-between',
          compact ? 'gap-0.5 p-1.5' : 'gap-3 p-3 sm:p-4',
        )}
      >
        <span
          className={cn(
            'truncate font-medium',
            compact
              ? 'text-xs leading-tight text-foreground/70'
              : 'text-xs text-foreground/70',
          )}
        >
          {eyebrow}
        </span>
        <div className="min-w-0">
          <p
            className={cn(
              'font-medium tracking-tight text-foreground',
              compact
                ? 'line-clamp-1 text-xs leading-tight'
                : 'line-clamp-2 text-sm leading-snug sm:text-base',
            )}
          >
            {title}
          </p>
        </div>
        <div
          className={cn(
            'min-w-0',
            compact
              ? 'text-xs leading-none text-foreground/70'
              : 'text-xs leading-4 text-foreground/70',
          )}
        >
          <p className="truncate">{detail}</p>
          {!compact ? (
            <p className="mt-0.5 text-foreground/70">暂无封面</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
