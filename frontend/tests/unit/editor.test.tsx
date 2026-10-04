import type { EditorConfig } from '@editorjs/editorjs';
import { act, render, screen, waitFor } from '@testing-library/react';
import { createRef, StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  type EditorDocument,
  toEditorDocument,
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
      constructor(config: EditorConfig) {
        this.config = config;
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
      <Editor value="# 初始" onChange={onChange} ref={ref} />,
    );
    await waitFor(() =>
      expect(screen.queryByRole('status')).not.toBeInTheDocument(),
    );
    const editor = mocks.instances[0];
    expect(
      screen.getByRole('textbox', { name: '正文编辑器，内容 1' }),
    ).toHaveAttribute('aria-multiline', 'true');
    editor.data = toEditorDocument('## 已编辑');
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
    rerender(<Editor value="# 替换" onChange={onChange} ref={ref} />);
    await waitFor(() =>
      expect(editor.render).toHaveBeenCalledWith(toEditorDocument('# 替换')),
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
    const { rerender, unmount } = render(<Editor value="初始" />);
    await waitFor(() => expect(mocks.instances).toHaveLength(1));
    const editor = mocks.instances[0];
    rerender(<Editor value="最新" />);
    await act(async () => {
      ready();
    });
    await waitFor(() =>
      expect(editor.render).toHaveBeenCalledWith(toEditorDocument('最新')),
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
        <Editor value="正文" />
      </StrictMode>,
    );
    await waitFor(() => expect(mocks.instances).toHaveLength(1));
    unmount();
    await act(async () => {
      ready();
    });
    expect(mocks.instances[0].destroy).toHaveBeenCalledTimes(1);
  });

  it('rejects unsupported blocks without silently deleting them', async () => {
    const onError = vi.fn();
    const document = {
      blocks: [{ type: 'unknown', data: { text: '保留的内容' } }],
    };
    render(<Editor value={document} onError={onError} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '编辑器加载失败',
    );
    expect(onError).toHaveBeenCalled();
    expect(mocks.instances).toHaveLength(0);
    expect(document.blocks).toHaveLength(1);
  });
});
