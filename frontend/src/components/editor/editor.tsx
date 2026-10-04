'use client';

import type EditorJS from '@editorjs/editorjs';
import { cn } from 'cn';
import {
  type Ref,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import { Button } from '@/components/ui/button';
import {
  assertEditableDocument,
  documentKey,
  type EditorContent,
  type EditorDocument,
  toEditorDocument,
} from './document';
import { loadEditorEngine } from './engine';
import { sanitizeRichText } from './rich-text';
import './editor.css';

function editableDocument(value: EditorContent): EditorDocument {
  const document = toEditorDocument(value);
  assertEditableDocument(document);
  const cleanItems = (
    items: import('./document').ListItem[],
  ): import('./document').ListItem[] =>
    items.map((item) => ({
      ...item,
      content: sanitizeRichText(item.content),
      items: cleanItems(item.items ?? []),
    }));
  return {
    ...document,
    blocks: document.blocks.map((block) => {
      const data = { ...block.data };
      if (typeof data.text === 'string')
        data.text = sanitizeRichText(data.text);
      if (typeof data.caption === 'string')
        data.caption = sanitizeRichText(data.caption);
      if (block.type === 'list') data.items = cleanItems(data.items ?? []);
      if (block.type === 'table')
        data.content = (data.content ?? []).map((row: string[]) =>
          row.map(sanitizeRichText),
        );
      return { ...block, data };
    }),
  };
}

export type EditorHandle = { save: () => Promise<EditorDocument> };
export type EditorProps = {
  value: EditorContent;
  onChange?: (document: EditorDocument) => void;
  onError?: (error: unknown) => void;
  ref?: Ref<EditorHandle>;
  className?: string;
  label?: string;
  placeholder?: string;
  readOnly?: boolean;
  autofocus?: boolean;
};

export function Editor({
  value,
  onChange,
  onError,
  ref,
  className,
  label = '正文编辑器',
  placeholder = '开始编写正文…',
  readOnly = false,
  autofocus = false,
}: EditorProps) {
  const holder = useRef<HTMLDivElement>(null);
  const instance = useRef<EditorJS | null>(null);
  const latest = useRef(toEditorDocument(value));
  const rendered = useRef('');
  const callbacks = useRef({ onChange, onError });
  const queue = useRef(Promise.resolve());
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>(
    'loading',
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    callbacks.current = { onChange, onError };
  }, [onChange, onError]);

  useImperativeHandle(
    ref,
    () => ({
      async save() {
        await queue.current;
        if (!instance.current) throw new Error('编辑器尚未就绪');
        return editableDocument(await instance.current.save());
      },
    }),
    [],
  );

  useEffect(() => {
    latest.current = toEditorDocument(value);
    const editor = instance.current;
    if (!editor || rendered.current === documentKey(latest.current)) return;
    queue.current = queue.current
      .then(async () => {
        if (instance.current !== editor) return;
        const next = editableDocument(latest.current);
        await editor.render(next);
        rendered.current = documentKey(next);
      })
      .catch((error) => {
        if (instance.current !== editor) return;
        setStatus('error');
        callbacks.current.onError?.(error);
      });
  }, [value]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt explicitly retries initialization.
  useEffect(() => {
    let cancelled = false;
    let editor: EditorJS | undefined;
    let observer: MutationObserver | undefined;
    let mount: HTMLDivElement | undefined;
    let disposed = false;
    function dispose() {
      if (disposed) return;
      disposed = true;
      observer?.disconnect();
      try {
        editor?.destroy?.();
      } catch {
        /* Initialization may fail before destroy is available. */
      }
      mount?.remove();
    }
    function labelFields() {
      mount
        ?.querySelectorAll<HTMLElement>('[contenteditable="true"],textarea')
        .forEach((field, index) => {
          field.setAttribute('aria-label', `${label}，内容 ${index + 1}`);
          if (
            field.isContentEditable ||
            field.getAttribute('contenteditable') === 'true'
          ) {
            field.setAttribute('role', 'textbox');
            field.setAttribute('aria-multiline', 'true');
          }
        });
    }
    setStatus('loading');
    async function initialize() {
      const { EditorJS, tools } = await loadEditorEngine();
      if (cancelled || !holder.current) return;
      const initial = editableDocument(latest.current);
      mount = document.createElement('div');
      holder.current.append(mount);
      editor = new EditorJS({
        holder: mount,
        data: initial,
        readOnly,
        autofocus,
        placeholder,
        minHeight: 0,
        tools,
        i18n: {
          messages: {
            ui: {
              blockTunes: {
                toggler: {
                  'Click to tune': '块设置',
                  'or drag to move': '拖动排序',
                },
              },
              toolbar: { toolbox: { Add: '添加内容' } },
              popover: { Filter: '搜索', 'Nothing found': '没有匹配内容' },
            },
            toolNames: {
              Text: '正文',
              Heading: '标题',
              List: '列表',
              Quote: '引用',
              Code: '代码',
              Table: '表格',
              Delimiter: '分隔线',
              Bold: '加粗',
              Italic: '斜体',
              Link: '链接',
              'Inline Code': '行内代码',
            },
            blockTunes: {
              delete: { Delete: '删除', 'Click to delete': '确认删除' },
              moveUp: { 'Move up': '上移' },
              moveDown: { 'Move down': '下移' },
            },
          },
        },
        async onChange() {
          if (cancelled || !editor || instance.current !== editor) return;
          try {
            const document = editableDocument(await editor.save());
            if (cancelled) return;
            const key = documentKey(document);
            if (key === rendered.current || instance.current !== editor) return;
            rendered.current = key;
            callbacks.current.onChange?.(document);
          } catch (error) {
            callbacks.current.onError?.(error);
          }
        },
      });
      await editor.isReady;
      if (cancelled) return;
      if (documentKey(initial) !== documentKey(latest.current))
        await editor.render(editableDocument(latest.current));
      rendered.current = documentKey(latest.current);
      instance.current = editor;
      labelFields();
      observer = new MutationObserver(labelFields);
      observer.observe(mount, { childList: true, subtree: true });
      setStatus('ready');
    }
    void initialize().catch((error) => {
      if (cancelled) return;
      dispose();
      setStatus('error');
      callbacks.current.onError?.(error);
    });
    return () => {
      cancelled = true;
      observer?.disconnect();
      mount?.remove();
      instance.current = null;
      // isReady owns initialization: wait before invoking the instance's destroy method.
      if (editor) void editor.isReady.then(dispose, dispose);
      else dispose();
    };
  }, [placeholder, readOnly, autofocus, label, attempt]);

  return (
    <section
      aria-label={label}
      aria-busy={status === 'loading'}
      data-slot="editor"
      className={cn(
        'block-editor min-w-0 rounded-md border border-border bg-surface px-4 py-3 text-foreground sm:px-10',
        className,
      )}
    >
      {status === 'loading' ? (
        <p role="status" className="text-sm text-muted-foreground">
          正在加载编辑器…
        </p>
      ) : null}
      {status === 'error' ? (
        <div role="alert" className="flex items-center gap-3 text-sm">
          <span>编辑器加载失败，请重试。</span>
          <Button
            type="button"
            variant="outline"
            onClick={() => setAttempt((current) => current + 1)}
          >
            重试
          </Button>
        </div>
      ) : null}
      <div ref={holder} />
    </section>
  );
}
