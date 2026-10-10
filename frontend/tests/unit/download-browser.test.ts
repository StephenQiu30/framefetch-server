import { afterEach, describe, expect, it, vi } from 'vitest';

import { triggerBrowserDownload } from '@/lib/browser-download';

describe('browser download', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('hands the authenticated file directly to the browser download manager', () => {
    vi.useFakeTimers();
    const url = '/api/downloads/123/file';
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        expect(this.getAttribute('href')).toBe(url);
        expect(this.download).toBe('示例视频.mp4');
        expect(this.isConnected).toBe(true);
      });

    triggerBrowserDownload(url, '示例视频.mp4');

    expect(click).toHaveBeenCalledOnce();
    expect(document.querySelector('a[download]')).toBeNull();
    expect(document.querySelector('iframe')).toBeNull();
    // A large/slow file must not be aborted by a one-minute frame cleanup.
    expect(vi.getTimerCount()).toBe(0);
  });
});
