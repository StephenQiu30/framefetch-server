import { ImageResponse } from 'next/og';

import { socialPalette } from '@/lib/site';

export const alt =
  'Framefetch — self-hosted media workflow and AI video analysis';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        alignItems: 'stretch',
        background: socialPalette.background,
        color: socialPalette.foreground,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        justifyContent: 'space-between',
        padding: '72px 80px',
        width: '100%',
      }}
    >
      <div
        style={{
          alignItems: 'center',
          display: 'flex',
          fontSize: 24,
          fontWeight: 600,
          letterSpacing: '-0.02em',
        }}
      >
        <div
          style={{
            background: socialPalette.foreground,
            borderRadius: 12,
            height: 34,
            marginRight: 16,
            width: 34,
          }}
        />
        FRAMEFETCH · OPEN SOURCE
      </div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <div
          style={{
            display: 'flex',
            fontSize: 72,
            fontWeight: 600,
            letterSpacing: '-0.055em',
            lineHeight: 1,
          }}
        >
          Self-hosted media workflow
        </div>
        <div
          style={{
            color: socialPalette.muted,
            display: 'flex',
            fontSize: 34,
            marginTop: 28,
          }}
        >
          Video parsing · Screenplay · AI analysis
        </div>
      </div>
      <div
        style={{
          color: socialPalette.muted,
          display: 'flex',
          fontSize: 22,
          justifyContent: 'space-between',
        }}
      >
        <span>FastAPI · Next.js · FFmpeg · yt-dlp</span>
        <span>MIT licensed</span>
      </div>
    </div>,
    size,
  );
}
