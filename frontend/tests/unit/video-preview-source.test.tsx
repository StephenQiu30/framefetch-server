import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useVideoPreviewSource } from '@/components/downloads/use-video-preview-source';
import { ApiError } from '@/lib/request-error';
import {
  httpRequests,
  mockHttpError,
  mockHttpResponses,
} from '../helpers/http';

const downloadId = '33333333-3333-4333-8333-333333333333';
const signedVideoUrl = {
  filename: 'Owned video.mp4',
  url: 'https://objects.example/downloads/video.mp4?signature=preview',
  expires_at: '2026-08-26T07:05:00Z',
};

describe('useVideoPreviewSource', () => {
  it('loads a short-lived source for the completed video', async () => {
    mockHttpResponses(signedVideoUrl);

    const { result } = renderHook(() => useVideoPreviewSource(downloadId));

    await waitFor(() => expect(result.current.source).toBe(signedVideoUrl.url));
    expect(result.current.loading).toBe(false);
    expect(result.current.filename).toBe(signedVideoUrl.filename);
    expect(httpRequests()[0]).toMatchObject({
      headers: { 'X-FrameFetch-Download-Client': 'local-web' },
      method: 'POST',
      params: { preview: true },
      url: `/api/downloads/${downloadId}/download-url`,
    });
  });

  it('lets the user reload after a preview request fails', async () => {
    mockHttpError(new ApiError(503, 'unavailable', 'Unavailable', '稍后重试'));
    mockHttpResponses(signedVideoUrl);

    const { result } = renderHook(() => useVideoPreviewSource(downloadId));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.source).toBe(signedVideoUrl.url));
    expect(httpRequests()).toHaveLength(2);
  });
});
