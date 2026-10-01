import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MediaUploadForm } from '@/components/intake/media-upload-form';
import { ScreenplayUploadForm } from '@/components/screenplay/screenplay-upload-form';

const mediaFile = new File(['video'], 'sample.mp4', { type: 'video/mp4' });
const documentFile = new File(['script'], 'script.txt', { type: 'text/plain' });

function callbacks() {
  return {
    onCancel: vi.fn(),
    onFileSelect: vi.fn(),
    onStart: vi.fn(),
  };
}

describe('upload form entry states', () => {
  it('allows media submission only after a valid file is selected', () => {
    const actions = callbacks();
    const props = {
      ...actions,
      busy: false,
      canCancel: false,
      declaredOrigin: 'user_file' as const,
      fileInvalid: false,
      phase: 'idle' as const,
      progress: 0,
    };
    const { container, rerender } = render(
      <MediaUploadForm {...props} file={null} />,
    );
    const form = container.querySelector('form');
    expect(form).not.toBeNull();
    expect(screen.getByRole('button', { name: '上传视频' })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: '选择本地 MP4 视频' }),
    ).toHaveAccessibleDescription(
      '支持 MP4 格式。选择文件后，点击“上传视频”开始导入。',
    );
    fireEvent.submit(form as HTMLFormElement);
    expect(actions.onStart).not.toHaveBeenCalled();

    rerender(<MediaUploadForm {...props} file={mediaFile} fileInvalid />);
    expect(screen.getByRole('button', { name: '上传视频' })).toBeDisabled();
    fireEvent.submit(form as HTMLFormElement);
    expect(actions.onStart).not.toHaveBeenCalled();

    rerender(<MediaUploadForm {...props} file={mediaFile} />);
    const upload = screen.getByRole('button', { name: '上传视频' });
    expect(upload).toBeEnabled();
    expect(upload).toHaveAttribute('data-size', 'xl');
    fireEvent.click(upload);
    expect(actions.onStart).toHaveBeenCalledOnce();
  });

  it.each(['dialog', 'workspace'] as const)(
    'keeps document upload disabled for missing, invalid and busy files in %s',
    (layout) => {
      const actions = callbacks();
      const props = {
        ...actions,
        busy: false,
        canCancel: false,
        error: null,
        fileInvalid: false,
        layout,
        phase: 'idle' as const,
        progress: 0,
      };
      const { container, rerender } = render(
        <ScreenplayUploadForm {...props} file={null} />,
      );
      const form = container.querySelector('form');
      expect(form).not.toBeNull();
      expect(screen.getByRole('button', { name: '上传剧本' })).toBeDisabled();
      expect(
        screen.getByLabelText('选择剧本文档文件'),
      ).toHaveAccessibleDescription(
        '支持 DOCX、PDF、TXT、Markdown 和 Fountain 格式。选择文件后，点击“上传剧本”开始导入。',
      );
      fireEvent.submit(form as HTMLFormElement);
      expect(actions.onStart).not.toHaveBeenCalled();

      rerender(
        <ScreenplayUploadForm {...props} file={documentFile} fileInvalid />,
      );
      expect(screen.getByRole('button', { name: '上传剧本' })).toBeDisabled();
      fireEvent.submit(form as HTMLFormElement);
      expect(actions.onStart).not.toHaveBeenCalled();

      rerender(<ScreenplayUploadForm {...props} file={documentFile} busy />);
      expect(screen.getByRole('button', { name: '处理中…' })).toBeDisabled();
      fireEvent.submit(form as HTMLFormElement);
      expect(actions.onStart).not.toHaveBeenCalled();

      rerender(<ScreenplayUploadForm {...props} file={documentFile} />);
      const upload = screen.getByRole('button', { name: '上传剧本' });
      expect(upload).toBeEnabled();
      if (layout === 'workspace') {
        expect(upload).toHaveAttribute('data-size', 'xl');
      }
      fireEvent.click(upload);
      expect(actions.onStart).toHaveBeenCalledOnce();
    },
  );

  it('cancels a media upload without dispatching another form submission', () => {
    const actions = callbacks();
    const { container } = render(
      <MediaUploadForm
        {...actions}
        busy
        canCancel
        declaredOrigin="user_file"
        file={mediaFile}
        fileInvalid={false}
        phase="uploading"
        progress={40}
      />,
    );
    const onSubmit = vi.fn();
    container.querySelector('form')?.addEventListener('submit', onSubmit);

    const cancel = screen.getByRole('button', { name: '取消上传' });
    expect(cancel).toHaveAttribute('type', 'button');
    fireEvent.click(cancel);

    expect(actions.onCancel).toHaveBeenCalledOnce();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(actions.onStart).not.toHaveBeenCalled();
  });
});
