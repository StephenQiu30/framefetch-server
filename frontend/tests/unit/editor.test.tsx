import type { EditorConfig } from '@editorjs/editorjs';
import { act, render, screen, waitFor } from '@testing-library/react';
import { createRef, StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  type EditorDocument,
  markdownToEditorDocument,
} from '@/components/editor/document';
import { Editor, type EditorHandle } from '@/components/editor/editor';

const mocks = vi.hoisted(() => ({
  instances: [] as any[],
  ready: undefined as Promise<void> | undefined,
}));
vi.mock('@/components/editor/engine', () => ({
  loadEditorEngine: async () => ({
    tools: {},
    EditorJS: class {
      data: EditorDocument;
      config: EditorConfig;
      isReady: Promise<void>;
      render = vi.fn(async (data: EditorDocument) => {
        this.data = data;
      });
      save = vi.fn(async () => this.data);
      destroy = vi.fn();
      readOnly = {
        isEnabled: false,
        toggle: vi.fn(async (state: boolean) => {
          this.readOnly.isEnabled = state;
          return state;
        }),
      };
      constructor(config: EditorConfig) {
        this.config = config;
        this.readOnly.isEnabled = Boolean(config.readOnly);
        this.data = config.data ?? { blocks: [] };
        this.isReady = mocks.ready ?? Promise.resolve();
        if (config.holder instanceof HTMLElement) {
          const field = document.createElement('div');
          field.contentEditable = 'true';
          config.holder.append(field);
        }
        mocks.instances.push(this);
      }
    },
  }),
}));

beforeEach(() => {
  mocks.instances.length = 0;
  mocks.ready = undefined;
});

describe('shared Editor lifecycle', () => {
  it('emits Editor.js data and accepts controlled echoes without resetting the cursor', async () => {
    const onChange = vi.fn();
    const ref = createRef<EditorHandle>();
    const { rerender, unmount } = render(
      <Editor
        value={markdownToEditorDocument('# 初始')}
        onChange={onChange}
        ref={ref}
      />,
    );
    await waitFor(() =>
      expect(screen.queryByRole('status')).not.toBeInTheDocument(),
    );
    const editor = mocks.instances[0];
    expect(
      screen.getByRole('textbox', { name: '正文编辑器，内容 1' }),
    ).toHaveAttribute('aria-multiline', 'true');
    editor.data = markdownToEditorDocument('## 已编辑');
    await act(async () => {
      await editor.config.onChange();
    });
    expect(onChange).toHaveBeenCalledWith(editor.data);
    rerender(
      <Editor
        value={onChange.mock.calls[0][0]}
        onChange={onChange}
        ref={ref}
      />,
    );
    expect(editor.render).not.toHaveBeenCalled();
    expect(await ref.current?.save()).toEqual(editor.data);
    rerender(
      <Editor
        value={markdownToEditorDocument('# 替换')}
        onChange={onChange}
        ref={ref}
      />,
    );
    await waitFor(() =>
      expect(editor.render).toHaveBeenCalledWith(
        markdownToEditorDocument('# 替换'),
      ),
    );
    await act(async () => {
      await editor.config.onChange();
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    unmount();
    await waitFor(() => expect(editor.destroy).toHaveBeenCalledTimes(1));
  });

  it('uses the newest value while initialization is pending and destroys exactly once', async () => {
    let ready!: () => void;
    mocks.ready = new Promise<void>((resolve) => {
      ready = resolve;
    });
    const { rerender, unmount } = render(
      <Editor value={markdownToEditorDocument('初始')} />,
    );
    await waitFor(() => expect(mocks.instances).toHaveLength(1));
    const editor = mocks.instances[0];
    rerender(<Editor value={markdownToEditorDocument('最新')} />);
    await act(async () => {
      ready();
    });
    await waitFor(() =>
      expect(editor.render).toHaveBeenCalledWith(
        markdownToEditorDocument('最新'),
      ),
    );
    unmount();
    await waitFor(() => expect(editor.destroy).toHaveBeenCalledTimes(1));
  });

  it('releases an instance unmounted during initialization and supports StrictMode', async () => {
    let ready!: () => void;
    mocks.ready = new Promise<void>((resolve) => {
      ready = resolve;
    });
    const { unmount } = render(
      <StrictMode>
        <Editor value={markdownToEditorDocument('正文')} />
      </StrictMode>,
    );
    await waitFor(() => expect(mocks.instances).toHaveLength(1));
    unmount();
    await act(async () => {
      ready();
    });
    expect(mocks.instances[0].destroy).toHaveBeenCalledTimes(1);
  });

  it('delegates unknown blocks to the official core without changing their data', async () => {
    const document = {
      blocks: [{ type: 'unknown', data: { text: '保留的内容' } }],
    };
    const { unmount } = render(<Editor value={document} />);
    await waitFor(() =>
      expect(mocks.instances[0]?.config.data).toEqual(document),
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    unmount();
  });

  it('switches read-only mode on the same instance and rejects saving while read-only', async () => {
    const ref = createRef<EditorHandle>();
    const document = markdownToEditorDocument('旧正文');
    const { rerender, unmount } = render(<Editor value={document} ref={ref} />);
    await waitFor(() =>
      expect(screen.queryByRole('status')).not.toBeInTheDocument(),
    );
    const editor = mocks.instances[0];
    editor.data = markdownToEditorDocument('尚未回传的编辑');
    rerender(<Editor value={document} ref={ref} readOnly />);
    await waitFor(() => expect(editor.readOnly.isEnabled).toBe(true));
    expect(mocks.instances).toHaveLength(1);
    expect(editor.render).not.toHaveBeenCalled();
    await expect(ref.current?.save()).rejects.toThrow('只读模式不能保存正文');
    rerender(<Editor value={document} ref={ref} />);
    await waitFor(() => expect(editor.readOnly.isEnabled).toBe(false));
    expect(await ref.current?.save()).toEqual(
      markdownToEditorDocument('尚未回传的编辑'),
    );
    unmount();
  });

  it('discards a stale save when an external replacement arrives and serializes both operations', async () => {
    const onChange = vi.fn();
    const { rerender, unmount } = render(
      <Editor value={markdownToEditorDocument('旧正文')} onChange={onChange} />,
    );
    await waitFor(() =>
      expect(screen.queryByRole('status')).not.toBeInTheDocument(),
    );
    const editor = mocks.instances[0];
    let finish!: (value: EditorDocument) => void;
    editor.save.mockImplementationOnce(
      () =>
        new Promise<EditorDocument>((resolve) => {
          finish = resolve;
        }),
    );
    let pending!: Promise<void>;
    await act(async () => {
      pending = editor.config.onChange();
    });
    rerender(
      <Editor
        value={markdownToEditorDocument('外部新正文')}
        onChange={onChange}
      />,
    );
    expect(editor.render).not.toHaveBeenCalled();
    await act(async () => {
      finish(markdownToEditorDocument('过期编辑'));
      await pending;
    });
    await waitFor(() =>
      expect(editor.render).toHaveBeenCalledWith(
        markdownToEditorDocument('外部新正文'),
      ),
    );
    expect(onChange).not.toHaveBeenCalled();
    unmount();
  });
});
