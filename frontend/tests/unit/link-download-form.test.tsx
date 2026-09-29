import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { LinkDownloadForm } from '@/components/intake/link-download-form';

describe('LinkDownloadForm', () => {
  it('keeps the compact link field and submit action accessible', () => {
    const onInspect = vi.fn();
    const onUrlChange = vi.fn();

    render(
      <LinkDownloadForm
        busy={false}
        disabled={false}
        hasResult={false}
        invalid={false}
        onInspect={onInspect}
        onUrlChange={onUrlChange}
        url=""
      />,
    );

    const field = screen.getByRole('textbox', { name: '公开视频地址' });
    expect(field.tagName).toBe('INPUT');
    expect(field).toHaveAttribute(
      'placeholder',
      '粘贴公开媒体链接或完整分享文案',
    );
    const controlRow = field.closest('[data-slot="field"]');
    expect(controlRow).toBe(
      screen
        .getByRole('button', { name: '解析媒体' })
        .closest('[data-slot="field"]'),
    );
    expect(controlRow).toHaveAttribute('data-orientation', 'responsive');

    field.focus();
    expect(field).toHaveFocus();

    fireEvent.keyDown(field, { key: 'Enter' });
    expect(onInspect).toHaveBeenCalledTimes(1);

    fireEvent.paste(field, {
      clipboardData: {
        getData: () => '看看这个视频\nhttps://example.com/video',
      },
    });
    expect(onUrlChange).toHaveBeenCalledWith(
      '看看这个视频 https://example.com/video',
    );

    fireEvent.click(screen.getByRole('button', { name: '解析媒体' }));
    expect(onInspect).toHaveBeenCalledTimes(2);
  });
});
