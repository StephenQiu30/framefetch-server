'use client';

import {
  MediaPlayer,
  type MediaPlayerInstance,
  MediaProvider,
  Poster,
} from '@vidstack/react';
import {
  DefaultVideoLayout,
  defaultLayoutIcons,
} from '@vidstack/react/player/layouts/default';
import { type Ref, useEffect } from 'react';
import { useVideoPreviewSource } from '@/components/downloads/use-video-preview-source';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { mediaFrameAspectRatio } from '@/components/media/media-cover';
import { AspectRatio } from '@/components/ui/aspect-ratio';
import { Skeleton } from '@/components/ui/skeleton';

type Props = {
  container?: 'mp4' | 'webm';
  downloadId: string;
  poster?: string | null;
  title: string;
  playerRef?: Ref<MediaPlayerInstance>;
  onFilenameChange?: (filename: string | null) => void;
  onReadyChange?: (ready: boolean) => void;
};

export default function DownloadVideoPreview({
  container,
  downloadId,
  poster,
  title,
  playerRef,
  onReadyChange,
  onFilenameChange,
}: Props) {
  const preview = useVideoPreviewSource(downloadId);
  useEffect(() => {
    onFilenameChange?.(preview.filename ?? null);
    return () => onFilenameChange?.(null);
  }, [preview.filename, onFilenameChange]);
  useEffect(() => {
    if (preview.loading || preview.error || !preview.source)
      onReadyChange?.(false);
    return () => onReadyChange?.(false);
  }, [preview.loading, preview.error, preview.source, onReadyChange]);

  if (preview.loading) {
    return (
      <AspectRatio ratio={mediaFrameAspectRatio}>
        <Skeleton aria-label="正在准备视频预览" className="size-full" />
      </AspectRatio>
    );
  }

  if (preview.error || !preview.source) {
    return (
      <AspectRatio ratio={mediaFrameAspectRatio}>
        <PageErrorNotice
          className="size-full"
          compact
          message={preview.error ?? '没有可用的视频预览地址。'}
          onRetry={preview.reload}
          retryLabel="重新加载预览"
          title="暂时无法预览视频"
        />
      </AspectRatio>
    );
  }

  return (
    <AspectRatio className="overflow-hidden" ratio={mediaFrameAspectRatio}>
      <MediaPlayer
        ref={playerRef}
        ariaLabel={`${title}视频预览`}
        aspectRatio="auto"
        className="size-full overflow-hidden"
        crossOrigin="anonymous"
        key={preview.source}
        load="eager"
        onCanPlay={() => onReadyChange?.(true)}
        onError={() => {
          onReadyChange?.(false);
          preview.reportPlaybackError();
        }}
        playsInline
        poster={poster ?? undefined}
        src={
          container
            ? { src: preview.source, type: `video/${container}` }
            : preview.source
        }
        title={title}
      >
        <MediaProvider>
          {poster ? (
            <Poster
              alt={`${title}封面`}
              className="vds-poster size-full object-cover"
              src={poster}
            />
          ) : null}
        </MediaProvider>
        <DefaultVideoLayout icons={defaultLayoutIcons} />
      </MediaPlayer>
    </AspectRatio>
  );
}
