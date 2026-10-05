'use client';

import type EditorJS from '@editorjs/editorjs';
import { cn } from 'cn';
import {
  type Ref,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Button } from '@/components/ui/button';
import {
  documentKey,
  type EditorDocument,
  sanitizeEditorDocument,
} from './document';
import { loadEditorEngine } from './engine';
import { safeWebUrl } from './rich-text';
import './editor.css';

export type EditorHandle = { save: () => Promise<EditorDocument> };
export type EditorProps = {
  value: EditorDocument;
  onChange?: (document: EditorDocument) => void;
  onError?: (error: unknown) => void;
  ref?: Ref<EditorHandle>;
  className?: string;
  label?: string;
  /** Used when the instance is initialized. */
  placeholder?: string;
  readOnly?: boolean;
  autofocus?: boolean;
  links?: boolean;
  /** Anchors for the document's header blocks, in block order. */
  headingIds?: (string | undefined)[];
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
  links = true,
  headingIds = [],
}: EditorProps) {
  const holder = useRef<HTMLDivElement>(null);
  const instance = useRef<EditorJS | null>(null);
  const document = useMemo(
    () => sanitizeEditorDocument(value, links),
    [value, links],
  );
  const latest = useRef({
    document,
    readOnly,
    placeholder,
    autofocus,
    label,
    headingIds,
  });
  const callbacks = useRef({ onChange, onError });
  const rendered = useRef('');
  const revision = useRef(0);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const decorate = useRef<() => void>(() => {});
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>(
    'loading',
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    callbacks.current = { onChange, onError };
    latest.current = {
      document,
      readOnly,
      placeholder,
      autofocus,
      label,
      headingIds,
    };
    decorate.current();
  }, [
    onChange,
    onError,
    document,
    readOnly,
    placeholder,
    autofocus,
    label,
    headingIds,
  ]);

  const enqueue = useCallback(
    <T,>(editor: EditorJS, operation: () => Promise<T>): Promise<T> => {
      const task = queue.current.then(() => {
        if (instance.current !== editor) throw new Error('编辑器已关闭');
        return operation();
      });
      queue.current = task.catch(() => {});
      return task;
    },
    [],
  );
  const reportError = useCallback((error: unknown) => {
    setStatus('error');
    callbacks.current.onError?.(error);
  }, []);
  useImperativeHandle(ref, () => ({
    async save() {
      const editor = instance.current;
      if (!editor) throw new Error('编辑器尚未就绪');
      return enqueue(editor, async () => {
        if (editor.readOnly.isEnabled) throw new Error('只读模式不能保存正文');
        return sanitizeEditorDocument(await editor.save());
      });
    },
  }));

  useEffect(() => {
    const editor = instance.current;
    if (!editor || rendered.current === documentKey(document)) return;
    revision.current += 1;
    void enqueue(editor, async () => {
      const next = latest.current.document;
      await editor.render(next);
      rendered.current = documentKey(next);
      decorate.current();
    }).catch((error) => {
      if (instance.current === editor) reportError(error);
    });
  }, [document, enqueue, reportError]);

  useEffect(() => {
    const editor = instance.current;
    if (!editor) return;
    void enqueue(editor, async () => {
      await editor.readOnly.toggle(readOnly);
      decorate.current();
    }).catch((error) => {
      if (instance.current === editor) reportError(error);
    });
  }, [readOnly, enqueue, reportError]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: the holder owns one instance; latest refs handle value/mode changes without reconstruction.
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
        /* An initialization failure may occur before the public API is exported. */
      }
      mount?.remove();
    }
    function decorateContent() {
      if (!mount || cancelled) return;
      mount
        .querySelectorAll<HTMLElement>('[contenteditable="true"],textarea')
        .forEach((field, index) => {
          field.setAttribute(
            'aria-label',
            `${latest.current.label}，内容 ${index + 1}`,
          );
          if (field.getAttribute('contenteditable') === 'true') {
            field.setAttribute('role', 'textbox');
            field.setAttribute('aria-multiline', 'true');
          }
        });
      mount
        .querySelectorAll<HTMLElement>('.ce-header')
        .forEach((heading, index) => {
          const id = latest.current.headingIds[index];
          if (id) heading.id = id;
          else heading.removeAttribute('id');
        });
      mount.querySelectorAll<HTMLAnchorElement>('a').forEach((anchor) => {
        const href = safeWebUrl(anchor.getAttribute('href'));
        if (!href) {
          anchor.replaceWith(...anchor.childNodes);
          return;
        }
        anchor.href = href;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
      });
    }
    setStatus('loading');
    async function initialize() {
      const { EditorJS, tools } = await loadEditorEngine();
      if (cancelled || !holder.current) return;
      const initial = latest.current;
      mount = window.document.createElement('div');
      holder.current.append(mount);
      editor = new EditorJS({
        holder: mount,
        data: initial.document,
        readOnly: initial.readOnly,
        autofocus: initial.autofocus,
        placeholder: initial.placeholder,
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
              'Ordered List': '有序列表',
              'Unordered List': '无序列表',
              Checklist: '任务列表',
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
          const current = editor;
          if (
            cancelled ||
            !current ||
            instance.current !== current ||
            current.readOnly.isEnabled
          )
            return;
          const changedRevision = revision.current;
          try {
            await enqueue(current, async () => {
              if (
                cancelled ||
                revision.current !== changedRevision ||
                current.readOnly.isEnabled
              )
                return;
              const saved = sanitizeEditorDocument(await current.save());
              if (
                cancelled ||
                instance.current !== current ||
                revision.current !== changedRevision
              )
                return;
              const key = documentKey(saved);
              if (key === rendered.current) return;
              rendered.current = key;
              callbacks.current.onChange?.(saved);
            });
          } catch (error) {
            if (!cancelled) callbacks.current.onError?.(error);
          }
        },
      });
      await editor.isReady;
      if (cancelled) return;
      let applied = initial.document;
      while (!cancelled) {
        const next = latest.current;
        if (documentKey(applied) !== documentKey(next.document)) {
          await editor.render(next.document);
          applied = next.document;
        }
        await editor.readOnly.toggle(next.readOnly);
        if (
          documentKey(applied) === documentKey(latest.current.document) &&
          editor.readOnly.isEnabled === latest.current.readOnly
        )
          break;
      }
      if (cancelled) return;
      rendered.current = documentKey(applied);
      instance.current = editor;
      decorate.current = decorateContent;
      decorateContent();
      observer = new MutationObserver(decorateContent);
      observer.observe(mount, { childList: true, subtree: true });
      setStatus('ready');
    }
    void initialize().catch((error) => {
      if (cancelled) return;
      dispose();
      instance.current = null;
      reportError(error);
    });
    return () => {
      cancelled = true;
      decorate.current = () => {};
      observer?.disconnect();
      mount?.remove();
      instance.current = null;
      revision.current += 1;
      if (editor) void editor.isReady.then(dispose, dispose);
      else dispose();
    };
  }, [attempt]);

  return (
    <section
      aria-label={label}
      aria-busy={status === 'loading'}
      data-slot="editor"
      className={cn(
        'block-editor min-w-0 text-foreground',
        readOnly
          ? 'block-editor--readonly'
          : 'rounded-md bg-surface px-4 py-3 sm:px-10',
        className,
      )}
    >
      {status === 'loading' ? (
        <p role="status" className="text-sm text-muted-foreground">
          正在加载正文…
        </p>
      ) : null}
      {status === 'error' ? (
        <div role="alert" className="flex items-center gap-3 text-sm">
          <span>正文加载失败，请重试。</span>
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
