'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { listCreationTaskRevisions } from '@/api/creation';
import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { Button } from '@/components/ui/button';
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';
import { CreationComparison } from './creation-comparison';
import { CreationEvidence } from './creation-evidence';
import { CreationExports } from './creation-exports';
import { CreationStructuredEditor } from './creation-structured-editor';

export function CreationVersionEditor({
  task,
  materials,
  formats,
  busy,
  onSave,
  onConfirm,
  onDirtyChange,
  onUseAsMaterial,
}: {
  task: API.CreationTaskResponse;
  materials: API.CreationMaterialResponse[];
  formats: string[];
  busy: boolean;
  onSave: (
    revision: API.CreationRevisionSaveRequest,
  ) => Promise<API.CreationTaskResponse | undefined>;
  onConfirm: (revisionId: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
  onUseAsMaterial?: (revisionId: string) => Promise<void>;
}) {
  const [base, setBase] = useState(task.revision);
  const [text, setText] = useState(task.revision?.text ?? '');
  const [data, setData] = useState<Record<string, unknown>>(
    task.revision?.data ?? {},
  );
  const [comparisonId, setComparisonId] = useState('');
  const [discard, setDiscard] = useState(false);
  const dirty = Boolean(
    base &&
      (text !== base.text ||
        JSON.stringify(data) !== JSON.stringify(base.data)),
  );
  const changedRemotely = Boolean(
    base && task.revision && base.id !== task.revision.id,
  );
  const active = task.status === 'queued' || task.status === 'processing';
  const locked = busy || active;
  const versions = useQuery({
    queryKey: privateQueryKey(
      'creation-task-revisions',
      task.id,
      task.revision?.id,
    ),
    queryFn: ({ signal }) =>
      listCreationTaskRevisions({ task_id: task.id }, { signal }),
  });
  const comparison =
    versions.data?.find((item) => item.id === comparisonId) ?? base;

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (task.revision && !dirty) {
      setBase(task.revision);
      setText(task.revision.text);
      setData(task.revision.data);
    }
  }, [task.revision, dirty]);

  function loadCurrent() {
    if (!task.revision) return;
    setBase(task.revision);
    setText(task.revision.text);
    setData(task.revision.data);
    setDiscard(false);
  }

  async function save(source?: API.CreationRevisionResponse) {
    if (!base || changedRemotely || locked) return;
    const next = await onSave({
      expected_revision_id: base.id,
      text: source?.text ?? text,
      data: source?.data ?? data,
    });
    if (next?.revision) {
      setBase(next.revision);
      setText(next.revision.text);
      setData(next.revision.data);
      setDiscard(false);
    }
  }

  if (!base) return null;
  return (
    <section aria-label="人工版本与交付" className="grid min-w-0 gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-medium">
          第 {base.number} 版{base.confirmed ? '确认稿' : '候选稿'}
        </h2>
        <span className="text-sm text-muted-foreground">
          {dirty ? '有未保存修改' : '内容已保存'}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        人工修改保存为新版本，不覆盖原件。确认代表你的采用决定；新增事实仍需核对来源。
      </p>
      {changedRemotely ? (
        <FeedbackNotice
          title="服务器已有更新版本"
          tone="info"
          description="当前编辑保留在本页。先比较最新版本，再决定取用；不会自动覆盖你的修改。"
          action={
            <Button variant="outline" onClick={() => setDiscard(true)}>
              载入服务器版本
            </Button>
          }
        />
      ) : null}
      {discard ? (
        <div className="grid gap-3" role="alert">
          <p>载入会放弃本页未保存修改。可先复制当前正文保留。</p>
          <div className="flex flex-wrap gap-3">
            <Button variant="outline" onClick={() => setDiscard(false)}>
              继续保留编辑
            </Button>
            <Button onClick={loadCurrent}>放弃本页修改并载入</Button>
          </div>
        </div>
      ) : null}
      <Tabs defaultValue="edit" className="min-w-0">
        <div className="max-w-full overflow-x-auto">
          <TabsList aria-label="版本工作区">
            <TabsTrigger value="edit">编辑</TabsTrigger>
            <TabsTrigger value="preview">正文</TabsTrigger>
            <TabsTrigger value="compare">版本比较</TabsTrigger>
            <TabsTrigger value="evidence">依据与待核</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="edit" className="mt-5 grid gap-6">
          <Field>
            <FieldLabel htmlFor={`creation-body-${task.id}`}>
              可编辑母稿
            </FieldLabel>
            <Textarea
              id={`creation-body-${task.id}`}
              rows={12}
              value={text}
              maxLength={100_000}
              disabled={locked}
              onChange={(event) => setText(event.target.value)}
            />
            <FieldDescription>
              修改母稿或结构化条目后先保存，再确认、导出。页面刷新前请保存工作。
            </FieldDescription>
          </Field>
          <CreationStructuredEditor
            data={data}
            onChange={setData}
            disabled={locked}
            images={materials.filter(
              (material) =>
                material.kind === 'image' &&
                material.current_revision.confirmed &&
                task.material_revision_ids.includes(
                  material.current_revision.id,
                ),
            )}
          />
        </TabsContent>
        <TabsContent value="preview" className="mt-5">
          <AnalysisReportPreview markdown={text} />
        </TabsContent>
        <TabsContent value="compare" className="mt-5 grid gap-5">
          <Field>
            <FieldLabel htmlFor="creation-compare-version">
              比较的已保存版本
            </FieldLabel>
            <Select
              value={comparisonId || base.id}
              onValueChange={setComparisonId}
            >
              <SelectTrigger id="creation-compare-version">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {versions.data?.map((version) => (
                  <SelectItem key={version.id} value={version.id}>
                    第 {version.number} 版
                    {version.confirmed ? ' · 确认稿' : ' · 候选稿'}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {versions.error ? (
            <FeedbackNotice
              title="版本历史读取失败"
              description={displayError(versions.error)}
              tone="error"
              action={
                <Button
                  variant="outline"
                  onClick={() => void versions.refetch()}
                >
                  重新读取历史
                </Button>
              }
            />
          ) : null}
          {comparison ? (
            <>
              <CreationComparison previous={comparison.text} current={text} />
              <p className="text-sm text-muted-foreground">
                恢复会把所选版本的正文与结构化内容保存为一份新草稿，旧版本继续保留。
              </p>
              <div>
                <Button
                  variant="outline"
                  disabled={
                    locked || changedRemotely || comparison.id === base.id
                  }
                  onClick={() => void save(comparison)}
                >
                  从此版本恢复为新草稿
                </Button>
              </div>
            </>
          ) : null}
        </TabsContent>
        <TabsContent value="evidence" className="mt-5">
          <CreationEvidence data={data} materials={materials} />
        </TabsContent>
      </Tabs>
      <div className="flex flex-wrap gap-3">
        <Button
          disabled={locked || changedRemotely || !dirty}
          onClick={() => void save()}
        >
          保存人工新版本
        </Button>
        <Button
          variant="outline"
          disabled={
            locked || changedRemotely || dirty || base.confirmed || task.stale
          }
          onClick={() => void onConfirm(base.id)}
        >
          核对后确认采用
        </Button>
        {onUseAsMaterial ? (
          <Button
            variant="outline"
            disabled={
              locked ||
              changedRemotely ||
              dirty ||
              !base.confirmed ||
              task.stale
            }
            onClick={() => void onUseAsMaterial(base.id)}
          >
            用确认结果作母稿
          </Button>
        ) : null}
      </div>
      {onUseAsMaterial ? (
        <p className="text-sm text-muted-foreground">
          保存为本作品的一份材料，保留此次确认版本的来源。核对并确认材料后，可继续整理公众号图文或小红书卡片。母稿更新只会标记衍生稿需要复核，不会自动生成或收费。
        </p>
      ) : null}
      <CreationExports
        task={task}
        formats={formats}
        unsaved={dirty || changedRemotely}
      />
    </section>
  );
}
