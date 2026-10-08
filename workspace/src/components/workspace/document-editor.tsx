'use client';

import { ArrowLeftIcon, FloppyDiskIcon } from '@phosphor-icons/react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { getCurrentUser } from '@/api/auth';
import {
  getWorkspaceDocument,
  listWorkspaceDocuments,
  updateWorkspaceDocument,
} from '@/api/workspace';
import {
  Editor,
  type EditorDocument,
  type EditorHandle,
  markdownToEditorDocument,
} from '@/components/editor';
import { Button } from '@/components/ui/button';
import {
  localizedErrorMessage,
  statusErrorMessage,
} from '@/lib/error-messages';
import { ApiError } from '@/lib/request-error';
import {
  documentRoute,
  linksForEditing,
  linksForSaving,
} from '@/lib/workspace/links';
import { editorDocumentToMarkdown } from '@/lib/workspace/markdown';

const errorMessage = (error: unknown) =>
  error instanceof ApiError
    ? (localizedErrorMessage(error.code) ?? statusErrorMessage(error.status))
    : '请求失败，请检查网络后重试。';

type Loaded = {
  document: API.WorkspaceDocumentResponse;
  documents: string[];
  value: EditorDocument;
};

type State =
  | { kind: 'loading' }
  | { kind: 'forbidden' }
  | { kind: 'failed'; message: string }
  | ({ kind: 'ready' } & Loaded);

export function DocumentEditor({
  path,
  webUrl,
}: {
  path: string;
  webUrl: string;
}) {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const editor = useRef<EditorHandle>(null);
  const route = useMemo(() => documentRoute(path), [path]);

  const load = useCallback(async () => {
    setState({ kind: 'loading' });
    try {
      const user = await getCurrentUser({ skipErrorHandler: true });
      if (user.role !== 'admin') return setState({ kind: 'forbidden' });
      const [document, list] = await Promise.all([
        getWorkspaceDocument({ path }, { skipErrorHandler: true }),
        listWorkspaceDocuments({ skipErrorHandler: true }),
      ]);
      const editable = linksForEditing(
        document.content,
        path,
        window.location.origin,
      );
      setState({
        kind: 'ready',
        document,
        documents: list.items.map((item) => item.path),
        value: markdownToEditorDocument(editable),
      });
      setDirty(false);
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) {
        return setState({ kind: 'forbidden' });
      }
      setState({ kind: 'failed', message: errorMessage(error) });
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  async function save() {
    if (state.kind !== 'ready' || !editor.current) return;
    setSaving(true);
    try {
      const markdown = editorDocumentToMarkdown(await editor.current.save());
      const content = linksForSaving(
        markdown,
        path,
        window.location.origin,
        state.documents,
      );
      const saved = await updateWorkspaceDocument(
        { path },
        { content, base_sha256: state.document.sha256 },
        { skipErrorHandler: true },
      );
      setState({ ...state, document: saved });
      setDirty(false);
      toast.success('已保存文档', {
        description: '开发预览自动更新；部署站点需重新构建后发布。',
      });
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  if (state.kind === 'loading')
    return <p className="text-muted-foreground py-12 text-sm">正在加载文档…</p>;
  if (state.kind === 'forbidden')
    return (
      <div className="flex flex-col items-start gap-3 py-12">
        <p className="text-sm">
          只有管理员可以编辑文档。请先在帧取 Web 以管理员身份登录，再回到本页。
        </p>
        <Button asChild>
          <a href={`${webUrl}/user/login`}>前往登录</a>
        </Button>
      </div>
    );
  if (state.kind === 'failed')
    return (
      <div className="flex flex-col items-start gap-3 py-12">
        <p className="text-sm">{state.message}</p>
        <Button variant="outline" onClick={() => void load()}>
          重试
        </Button>
      </div>
    );

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="ghost">
          <a href={route}>
            <ArrowLeftIcon aria-hidden />
            返回文档
          </a>
        </Button>
        <div className="flex items-center gap-3">
          <span className="text-muted-foreground text-sm">
            {dirty ? '有未保存的修改' : '已是最新'}
          </span>
          <Button onClick={() => void save()} disabled={!dirty || saving}>
            <FloppyDiskIcon aria-hidden />
            {saving ? '正在保存…' : '保存'}
          </Button>
        </div>
      </div>
      <Editor
        ref={editor}
        value={state.value}
        onChange={() => setDirty(true)}
        label={`编辑 ${state.document.title}`}
        autofocus
      />
    </div>
  );
}
