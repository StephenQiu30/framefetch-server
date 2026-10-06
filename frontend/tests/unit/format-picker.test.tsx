import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import FormatPicker from '@/components/intake/format-picker';
import { inspection } from '../fixtures/download-fixtures';

describe('FormatPicker', () => {
  it('renders every semantic format as a selectable card', () => {
    const formats = Array.from({ length: 8 }, (_, index) => ({
      ...inspection.formats[0],
      id: `format-${index}`,
      display_name: `${1080 - index * 90}p MP4`,
    }));
    const onChange = vi.fn();

    render(
      <FormatPicker
        formats={formats}
        onChange={onChange}
        selectedId={formats[0].id}
      />,
    );

    expect(screen.getAllByRole('radio')).toHaveLength(8);
    expect(
      screen.getByRole('radio', { name: formats[0].display_name }),
    ).toHaveAccessibleDescription('1920×1080 · H264 · AAC · 最高 30 FPS');

    fireEvent.click(screen.getAllByRole('radio')[1]);
    expect(onChange).toHaveBeenCalledWith('format-1');
  });

  it('lets users select an image gallery ZIP option', () => {
    const onChange = vi.fn();
    const format = {
      id: 'image-gallery-zip',
      display_name: '下载 3 张原图（ZIP）',
      plan: null,
    };

    render(
      <FormatPicker formats={[format]} onChange={onChange} selectedId="" />,
    );

    const radio = screen.getByRole('radio');
    expect(radio).not.toBeChecked();

    fireEvent.click(screen.getByText(format.display_name));
    expect(onChange).toHaveBeenCalledWith('image-gallery-zip');
  });
});
