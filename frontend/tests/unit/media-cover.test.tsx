import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import MediaCover from '@/components/media/media-cover';
import { loadPrivateThumbnail } from '@/lib/media-assets';

vi.mock('@/lib/media-assets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/media-assets')>();
  return {
    ...actual,
    loadPrivateThumbnail: vi.fn(),
  };
});

const THUMBNAIL =
  '/api/inspections/8cba925d-9196-4f48-89ee-76566a705446/thumbnail';

describe('MediaCover', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.mocked(URL.createObjectURL).mockReset();
  });

  it('loads a private thumbnail through the authenticated refresh-aware client', async () => {
    const image = new Blob(['cover'], { type: 'image/jpeg' });
    vi.mocked(loadPrivateThumbnail).mockResolvedValue(image);
    vi.mocked(URL.createObjectURL).mockReturnValue('blob:private-thumbnail');
    const revoke = vi.spyOn(URL, 'revokeObjectURL');

    const view = render(<MediaCover alt="测试视频" src={THUMBNAIL} />);

    expect(
      screen.getByRole('img', { name: '测试视频（封面加载中）' }),
    ).toBeVisible();
    await waitFor(() =>
      expect(screen.getByRole('img', { name: '测试视频' })).toHaveAttribute(
        'src',
        'blob:private-thumbnail',
      ),
    );
    expect(loadPrivateThumbnail).toHaveBeenCalledWith(
      THUMBNAIL,
      expect.any(AbortSignal),
    );

    view.unmount();
    expect(revoke).toHaveBeenCalledWith('blob:private-thumbnail');
  });

  it('shows readable metadata when the authenticated thumbnail request fails', async () => {
    vi.mocked(loadPrivateThumbnail).mockRejectedValue(
      new Error('storage unavailable'),
    );

    render(
      <MediaCover
        alt="测试视频媒体封面"
        fallback={{
          detail: '1080p MP4',
          eyebrow: '链接下载',
          title: '测试视频',
        }}
        src={THUMBNAIL}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByRole('img', { name: '测试视频（暂无封面）' }),
      ).toBeVisible(),
    );
    expect(screen.getByText('链接下载')).toBeVisible();
    expect(screen.getByText('1080p MP4')).toBeVisible();
    expect(screen.getByText('暂无封面')).toBeVisible();
  });

  it('uses the same readable metadata fallback when no thumbnail exists', () => {
    render(
      <MediaCover
        alt="图集媒体封面"
        fallback={{
          detail: '4 张原图 · ZIP',
          eyebrow: 'Instagram',
          title: 'Post by angelababy.weibo',
        }}
      />,
    );

    expect(
      screen.getByRole('img', { name: 'Post by angelababy.weibo（暂无封面）' }),
    ).toBeVisible();
    expect(screen.getByText('Instagram')).toBeVisible();
    expect(screen.getByText('4 张原图 · ZIP')).toBeVisible();
    expect(screen.queryByText('封面不可用')).not.toBeInTheDocument();
  });

  it('keeps the compact fallback borderless and readable', () => {
    render(
      <MediaCover
        alt="列表视频媒体封面"
        compact
        fallback={{
          detail: '1080p MP4',
          eyebrow: '链接下载',
          title: '列表视频',
        }}
      />,
    );

    const fallback = screen.getByRole('img', {
      name: '列表视频（暂无封面）',
    });
    expect(fallback).not.toHaveClass('border');
    expect(screen.getByText('链接下载')).toHaveClass(
      'text-xs',
      'text-foreground/70',
    );
    expect(screen.getByText('1080p MP4').parentElement).toHaveClass(
      'text-xs',
      'text-foreground/70',
    );
  });

  it('shows generating while a task can still produce a cover', () => {
    render(<MediaCover alt="测试视频" pending src={null} />);

    expect(
      screen.getByRole('img', { name: '测试视频（封面生成中）' }),
    ).toBeVisible();
    expect(screen.queryByText('封面不可用')).not.toBeInTheDocument();
  });

  it('keeps public and bundled images on the direct browser path', () => {
    render(<MediaCover alt="演示视频" src="/images/demo.webp" />);

    const image = screen.getByRole('img', { name: '演示视频' });
    expect(image).toHaveAttribute(
      'src',
      'http://localhost:3000/images/demo.webp',
    );
    expect(image).toHaveClass('object-cover');
    expect(image).not.toHaveClass('object-contain');
    const frame = image.closest('[data-slot="aspect-ratio"]');
    const images = frame?.querySelectorAll('img');
    expect(images).toHaveLength(1);
    expect(frame).not.toBeNull();
    expect(frame?.parentElement).toHaveStyle({ paddingBottom: '56.25%' });
    expect(loadPrivateThumbnail).not.toHaveBeenCalled();
  });

  it('switches a public image to the readable fallback after an image error', () => {
    render(
      <MediaCover
        alt="演示视频媒体封面"
        fallback={{ title: '演示视频' }}
        src="/images/missing.webp"
      />,
    );

    fireEvent.error(screen.getByRole('img', { name: '演示视频媒体封面' }));

    expect(
      screen.getByRole('img', { name: '演示视频（暂无封面）' }),
    ).toBeVisible();
  });
});
