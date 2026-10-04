import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CreationMaterialForm } from '@/components/creation/creation-material-form';
import { render } from '../helpers/query-render';

describe('creation material file intake', () => {
  it('submits genuine static WebP bytes and original filename after explicit rights confirmation', async () => {
    const submit = vi.fn().mockResolvedValue(true);
    const webp = 'UklGRiIAAABXRUJQVlA4TBUAAAAvd8AOAAcQ/Y/+B4CE8P++EtH/VBAA';
    render(
      <CreationMaterialForm
        projectId="project-1"
        busy={false}
        onSubmit={submit}
      />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: '材料类型' }));
    fireEvent.click(await screen.findByRole('option', { name: '授权图片' }));
    const input = screen.getByLabelText('选择授权图片');
    expect(input).toHaveAttribute('accept', 'image/png,image/jpeg,image/webp');
    fireEvent.change(input, {
      target: {
        files: [
          new File(
            [Uint8Array.from(atob(webp), (byte) => byte.charCodeAt(0))],
            'original-card.webp',
            { type: 'image/webp' },
          ),
        ],
      },
    });
    await screen.findByText(/original-card.webp 已读取/);
    expect(
      screen.getByRole('button', { name: '保存待确认材料' }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText('权利与用途说明'), {
      target: { value: '本人制作的静态原图，允许本次图卡使用。' },
    });
    fireEvent.click(
      screen.getByRole('checkbox', { name: /我有权使用这些材料/ }),
    );
    fireEvent.click(screen.getByRole('button', { name: '保存待确认材料' }));
    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    expect(submit.mock.calls[0][0]).toMatchObject({
      kind: 'image',
      image_data_base64: webp,
      data: { filename: 'original-card.webp' },
    });
    expect(submit.mock.calls[0][0]).not.toHaveProperty('text');
  });

  it('rejects a WebP over the original-image byte limit without submitting it', async () => {
    const submit = vi.fn();
    render(
      <CreationMaterialForm
        projectId="project-1"
        busy={false}
        onSubmit={submit}
      />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: '材料类型' }));
    fireEvent.click(await screen.findByRole('option', { name: '授权图片' }));
    fireEvent.change(screen.getByLabelText('选择授权图片'), {
      target: {
        files: [
          new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'oversize.webp', {
            type: 'image/webp',
          }),
        ],
      },
    });
    await screen.findByText(
      '请选择不超过 10 MiB 的 PNG、JPEG 或静态 WebP 原图。',
    );
    expect(submit).not.toHaveBeenCalled();
    expect(
      screen.getByRole('button', { name: '保存待确认材料' }),
    ).toBeDisabled();
  });

  it('submits the selected bounded PDF bytes for server extraction before human confirmation', async () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <CreationMaterialForm
        projectId="project-1"
        busy={false}
        onSubmit={submit}
      />,
    );
    const input = screen.getByLabelText('导入本地文档或文字文件（选填）');
    Object.defineProperty(input, 'value', {
      configurable: true,
      writable: true,
      value: 'C:\\fakepath\\自己的材料.pdf',
    });
    fireEvent.change(input, {
      target: {
        files: [
          new File(['%PDF-1.4 selected original'], '自己的材料.pdf', {
            type: 'application/pdf',
          }),
        ],
      },
    });
    await screen.findByText(/自己的材料.pdf 已读取/);
    expect(screen.queryByLabelText('材料正文')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('权利与用途说明'), {
      target: { value: '本人原创，供此次整理。' },
    });
    fireEvent.click(
      screen.getByRole('checkbox', {
        name: '我有权使用这些材料，并同意按上述用途处理',
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: '保存待确认材料' }));
    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    expect(submit.mock.calls[0][0]).toMatchObject({
      project_id: 'project-1',
      kind: 'text',
      title: '自己的材料.pdf',
      document_filename: '自己的材料.pdf',
      document_data_base64: btoa('%PDF-1.4 selected original'),
      rights_statement: '本人原创，供此次整理。',
    });
    expect(submit.mock.calls[0][0]).not.toHaveProperty('text');
    expect(submit.mock.calls[0][0]).not.toHaveProperty('document_id');
    await waitFor(() =>
      expect(
        screen.getByLabelText('导入本地文档或文字文件（选填）'),
      ).toHaveValue(''),
    );
  });

  it('clears the native file selection when changing material kind', async () => {
    render(
      <CreationMaterialForm
        projectId="project-1"
        busy={false}
        onSubmit={vi.fn()}
      />,
    );
    const input = screen.getByLabelText(
      '导入本地文档或文字文件（选填）',
    ) as HTMLInputElement;
    Object.defineProperty(input, 'value', {
      configurable: true,
      writable: true,
      value: 'C:\\fakepath\\article.docx',
    });
    fireEvent.change(input, {
      target: {
        files: [new File(['bounded DOCX bytes'], 'article.docx')],
      },
    });
    await screen.findByText(/article.docx 已读取/);
    fireEvent.click(screen.getByRole('combobox', { name: '材料类型' }));
    fireEvent.click(await screen.findByRole('option', { name: '授权图片' }));
    expect(screen.getByLabelText('选择授权图片')).toHaveValue('');
    expect(screen.queryByText(/article.docx 已读取/)).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '保存待确认材料' }),
    ).toBeDisabled();
  });

  it('rejects malformed UTF-8 instead of silently replacing the source text', async () => {
    const submit = vi.fn();
    render(
      <CreationMaterialForm
        projectId="project-1"
        busy={false}
        onSubmit={submit}
      />,
    );
    fireEvent.change(screen.getByLabelText('导入本地文档或文字文件（选填）'), {
      target: {
        files: [new File([new Uint8Array([0xff, 0xfe, 0xff])], '错误编码.txt')],
      },
    });
    await screen.findByText('文件不是有效 UTF-8 文本，请转换编码后导入。');
    expect(
      screen.getByRole('button', { name: '保存待确认材料' }),
    ).toBeDisabled();
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '改用粘贴正文' }));
    expect(
      screen.queryByText('文件不是有效 UTF-8 文本，请转换编码后导入。'),
    ).not.toBeInTheDocument();
  });
});
