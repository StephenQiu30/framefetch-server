'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import {
  cancelCreationTask,
  confirmCreationMaterial,
  confirmCreationTask,
  createCreationMaterial,
  createCreationProject,
  createCreationTask,
  getCreationTask,
  listCreationMaterials,
  listCreationProjects,
  listCreationSkills,
  listCreationTasks,
  retryCreationTask,
  saveCreationMaterialRevision,
  saveCreationTaskRevision,
} from '@/api/creation';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';
import { CreationMaterialForm } from './creation-material-form';
import { CreationMaterialList } from './creation-material-list';
import {
  completeCreationOperation,
  creationIdempotencyKey,
} from './creation-operation';
import { CreationOptions } from './creation-options';
import { CreationTaskStatus } from './creation-task-status';
import { CreationVersionEditor } from './creation-version-editor';

export default function CreationWorkspace() {
  const queries = useQueryClient();
  const [projectId, setProjectId] = useState('');
  const [projectTitle, setProjectTitle] = useState('');
  const [route, setRoute] = useState<'article' | 'film'>('article');
  const [skillId, setSkillId] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [options, setOptions] = useState<Record<string, unknown>>({});
  const [budget, setBudget] = useState<API.CreationBudget>({
    max_calls: 4,
    max_tokens: 16_000,
    timeout_seconds: 600,
  });
  const [authorized, setAuthorized] = useState(false);
  const [taskId, setTaskId] = useState('');
  const [step, setStep] = useState('materials');
  const [taskDirty, setTaskDirty] = useState(false);
  const [navigation, setNavigation] = useState<{
    projectId?: string;
    taskId?: string;
  }>();
  const [pending, setPending] = useState<string>();
  const [error, setError] = useState<string>();
  const actionRef = useRef(false);
  const catalog = useQuery({
    queryKey: privateQueryKey('creation-skills'),
    queryFn: ({ signal }) => listCreationSkills({ signal }),
  });
  const projects = useQuery({
    queryKey: privateQueryKey('creation-projects'),
    queryFn: ({ signal }) => listCreationProjects({ limit: 50 }, { signal }),
  });
  const materials = useQuery({
    queryKey: privateQueryKey('creation-materials', projectId),
    enabled: Boolean(projectId),
    queryFn: ({ signal }) =>
      listCreationMaterials({ project_id: projectId, limit: 100 }, { signal }),
  });
  const tasks = useQuery({
    queryKey: privateQueryKey('creation-tasks', projectId),
    enabled: Boolean(projectId),
    queryFn: ({ signal }) =>
      listCreationTasks({ project_id: projectId, limit: 50 }, { signal }),
    refetchInterval: 5000,
  });
  const detail = useQuery({
    queryKey: privateQueryKey('creation-task', taskId),
    enabled: Boolean(taskId),
    queryFn: ({ signal }) => getCreationTask({ task_id: taskId }, { signal }),
    refetchInterval: (query) =>
      query.state.data &&
      ['queued', 'processing'].includes(query.state.data.status)
        ? 3000
        : false,
  });
  const skill = catalog.data?.find((item) => item.id === skillId);
  const taskSkill = catalog.data?.find(
    (item) => item.id === detail.data?.skill_id,
  );
  const compatible =
    materials.data?.filter(
      (item) =>
        item.current_revision.confirmed &&
        selected.includes(item.current_revision.id),
    ) ?? [];

  useEffect(() => {
    if (!taskDirty) return;
    const protect = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [taskDirty]);

  function navigate(
    target: { projectId?: string; taskId?: string },
    discard = false,
  ) {
    if (taskDirty && !discard) {
      setNavigation(target);
      return;
    }
    if (target.projectId !== undefined) {
      setProjectId(target.projectId);
      setTaskId('');
      setSelected([]);
      setAuthorized(false);
    } else if (target.taskId !== undefined) setTaskId(target.taskId);
    setTaskDirty(false);
    setNavigation(undefined);
  }

  useEffect(() => {
    if (!projectId && projects.data?.[0]) setProjectId(projects.data[0].id);
  }, [projectId, projects.data]);
  useEffect(() => {
    if (!catalog.data) return;
    const existing = catalog.data.find(
      (item) => item.id === skillId && item.route === route,
    );
    if (!existing) {
      const first =
        catalog.data.find((item) => item.route === route && item.available) ??
        catalog.data.find((item) => item.route === route);
      setSkillId(first?.id ?? '');
    }
  }, [catalog.data, skillId, route]);

  function idempotency(scope: string, body: unknown) {
    return creationIdempotencyKey(scope, body);
  }

  async function action<T>(
    name: string,
    run: () => Promise<T>,
  ): Promise<T | undefined> {
    if (actionRef.current) return undefined;
    actionRef.current = true;
    setPending(name);
    setError(undefined);
    try {
      return await run();
    } catch (reason) {
      setError(displayError(reason));
      return undefined;
    } finally {
      actionRef.current = false;
      setPending(undefined);
    }
  }

  async function updateTask(next: API.CreationTaskResponse) {
    queries.setQueryData(privateQueryKey('creation-task', next.id), next);
    setTaskId(next.id);
    setStep('tasks');
    await tasks.refetch();
  }
  async function refreshMaterials() {
    await materials.refetch();
    await tasks.refetch();
    if (taskId) await detail.refetch();
  }

  async function createProject(event: React.FormEvent) {
    event.preventDefault();
    if (taskDirty) return;
    const input: API.CreationProjectCreateRequest = {
      title: projectTitle.trim(),
    };
    if (!input.title) return;
    const created = await action('project', () =>
      createCreationProject(input, {
        headers: { 'Idempotency-Key': idempotency('project', input) },
      }),
    );
    if (created) {
      await projects.refetch();
      setProjectId(created.id);
      setProjectTitle('');
      setSelected([]);
      setTaskId('');
      completeCreationOperation('project');
    }
  }

  async function createTask(event: React.FormEvent) {
    event.preventDefault();
    if (
      !skill?.available ||
      !authorized ||
      !compatible.length ||
      !projectId ||
      taskDirty
    )
      return;
    const input: API.CreationTaskCreateRequest = {
      project_id: projectId,
      skill_id: skill.id,
      material_revision_ids: compatible.map((item) => item.current_revision.id),
      options: {
        ...(skill.id === 'article-edit' ? { mode: 'format' } : {}),
        ...options,
      },
      budget,
      output_language: 'zh-CN',
    };
    const next = await action('task', () =>
      createCreationTask(input, {
        headers: { 'Idempotency-Key': idempotency('task', input) },
      }),
    );
    if (next) {
      await updateTask(next);
      setAuthorized(false);
      completeCreationOperation('task');
    }
  }

  return (
    <div className="inner-page">
      <PageHeader
        title="内容工作台"
        description="核对自己的材料，完成影视分析、文章整理、公众号图文与小红书卡片。保留原件和人工版本，再交付实际文件。"
        action={
          <Button asChild variant="outline">
            <Link
              href="/history/activity"
              onClick={(event) => {
                if (taskDirty) {
                  event.preventDefault();
                  setStep('tasks');
                  setError(
                    '当前人工稿有未保存修改，请先保存或明确放弃后再查看旧记录。',
                  );
                }
              }}
            >
              查看旧报告与处理记录
            </Link>
          </Button>
        }
      />
      {navigation ? (
        <FeedbackNotice
          className="mt-6"
          title="当前人工稿尚未保存"
          tone="info"
          description="切换会放弃本页编辑。可先继续保存，或明确放弃后切换；已保存版本不会改变。"
          action={
            <>
              <Button
                variant="outline"
                onClick={() => {
                  setNavigation(undefined);
                  setStep('tasks');
                }}
              >
                继续编辑
              </Button>
              <Button onClick={() => navigate(navigation, true)}>
                放弃本页修改并切换
              </Button>
            </>
          }
        />
      ) : null}
      {error ? (
        <FeedbackNotice
          className="mt-6"
          title="操作未完成"
          description={error}
          tone="error"
          action={
            <Button
              variant="outline"
              onClick={() => {
                setError(undefined);
                void projects.refetch();
                void refreshMaterials();
              }}
            >
              核对最新状态
            </Button>
          }
        />
      ) : null}
      {catalog.error || projects.error ? (
        <FeedbackNotice
          className="mt-6"
          title="工作台读取失败"
          description={displayError(catalog.error ?? projects.error)}
          tone="error"
          action={
            <Button
              variant="outline"
              onClick={() => {
                void catalog.refetch();
                void projects.refetch();
              }}
            >
              重新读取
            </Button>
          }
        />
      ) : null}
      {catalog.isPending || projects.isPending ? (
        <p role="status" className="py-10">
          正在读取可用能力和作品…
        </p>
      ) : null}
      <section aria-label="作品选择" className="mt-8 grid gap-5 md:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="creation-project">当前作品</FieldLabel>
          <Select
            value={projectId}
            disabled={Boolean(pending)}
            onValueChange={(id) => {
              navigate({ projectId: id });
            }}
          >
            <SelectTrigger
              id="creation-project"
              className="data-placeholder:text-foreground"
            >
              <SelectValue placeholder="创建或选择一个作品" />
            </SelectTrigger>
            <SelectContent>
              {projects.data?.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={createProject}
        >
          <Field className="min-w-0 flex-1">
            <FieldLabel htmlFor="creation-project-title">新作品名称</FieldLabel>
            <Input
              id="creation-project-title"
              value={projectTitle}
              onChange={(event) => setProjectTitle(event.target.value)}
              maxLength={200}
              disabled={Boolean(pending)}
              required
            />
          </Field>
          <Button
            disabled={Boolean(pending) || !projectTitle.trim() || taskDirty}
            type="submit"
          >
            创建作品
          </Button>
        </form>
      </section>
      {!projectId ? (
        <PageEmptyNotice
          className="mt-10"
          title="从一个作品开始"
          description="创建文章或影视作品，再添加有权材料。每次任务会绑定你确认的材料版本。"
        />
      ) : (
        <Tabs value={step} onValueChange={setStep} className="mt-10 min-w-0">
          <div className="max-w-full overflow-x-auto">
            <TabsList aria-label="内容工作流程">
              <TabsTrigger value="materials">材料与确认</TabsTrigger>
              <TabsTrigger value="new">新建任务</TabsTrigger>
              <TabsTrigger value="tasks">任务与版本</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent
            value="materials"
            forceMount
            className="mt-6 grid min-w-0 gap-10 data-[state=inactive]:hidden lg:grid-cols-2"
          >
            <section className="min-w-0 grid content-start gap-5">
              <h2 className="text-lg font-medium">添加原始材料</h2>
              <CreationMaterialForm
                key={projectId}
                projectId={projectId}
                busy={Boolean(pending)}
                onSubmit={async (input) => {
                  const created = await action('material', () =>
                    createCreationMaterial(input, {
                      headers: {
                        'Idempotency-Key': idempotency('material', input),
                      },
                    }),
                  );
                  if (created) {
                    await refreshMaterials();
                    completeCreationOperation('material');
                  }
                  return Boolean(created);
                }}
              />
            </section>
            <section className="min-w-0 grid content-start gap-5">
              <h2 className="text-lg font-medium">核对与选择材料</h2>
              {materials.error ? (
                <FeedbackNotice
                  title="材料读取失败"
                  description={displayError(materials.error)}
                  tone="error"
                  action={
                    <Button
                      variant="outline"
                      onClick={() => void materials.refetch()}
                    >
                      重新读取材料
                    </Button>
                  }
                />
              ) : null}
              <CreationMaterialList
                materials={materials.data ?? []}
                selected={selected}
                onSelect={(ids) => {
                  setSelected(ids);
                  setAuthorized(false);
                }}
                busy={Boolean(pending)}
                onSave={async (material, text) => {
                  const input: API.CreationRevisionSaveRequest = {
                    expected_revision_id: material.current_revision.id,
                    text,
                    data: material.current_revision.data,
                  };
                  const next = await action('material-edit', () =>
                    saveCreationMaterialRevision(
                      { material_id: material.id },
                      input,
                      {
                        headers: {
                          'Idempotency-Key': idempotency(
                            `material-${material.id}`,
                            input,
                          ),
                        },
                      },
                    ),
                  );
                  if (next) {
                    setSelected((ids) =>
                      ids.filter((id) => id !== material.current_revision.id),
                    );
                    await refreshMaterials();
                  }
                }}
                onConfirm={async (material) => {
                  const next = await action('material-confirm', () =>
                    confirmCreationMaterial(
                      { material_id: material.id },
                      { expected_revision_id: material.current_revision.id },
                    ),
                  );
                  if (next) await refreshMaterials();
                }}
              />
            </section>
          </TabsContent>
          <TabsContent
            value="new"
            forceMount
            className="mt-6 max-w-3xl data-[state=inactive]:hidden"
          >
            <form className="grid gap-8" onSubmit={createTask}>
              <Tabs
                value={route}
                onValueChange={(value) => {
                  setRoute(value as 'article' | 'film');
                  setOptions({});
                  setAuthorized(false);
                }}
              >
                <TabsList aria-label="创作方向">
                  <TabsTrigger value="article">文章与图文</TabsTrigger>
                  <TabsTrigger value="film">影视分析</TabsTrigger>
                </TabsList>
              </Tabs>
              <Field>
                <FieldLabel htmlFor="creation-skill">要完成的任务</FieldLabel>
                <Select
                  value={skillId}
                  disabled={Boolean(pending)}
                  onValueChange={(id) => {
                    setSkillId(id);
                    setOptions({});
                    setAuthorized(false);
                  }}
                >
                  <SelectTrigger
                    id="creation-skill"
                    className="data-placeholder:text-foreground"
                  >
                    <SelectValue placeholder="选择当前开放的任务" />
                  </SelectTrigger>
                  <SelectContent>
                    {catalog.data
                      ?.filter((item) => item.route === route)
                      .map((item) => (
                        <SelectItem
                          key={item.id}
                          value={item.id}
                          disabled={!item.available}
                        >
                          {item.name}
                          {item.available ? '' : ' · 当前未开放'}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                {skill?.limitations?.map((item) => (
                  <FieldDescription key={item}>{item}</FieldDescription>
                ))}
              </Field>
              <div className="grid gap-3">
                <h3 className="font-medium">本次使用的确认材料</h3>
                {compatible.length ? (
                  <ul className="grid list-disc gap-2 pl-5">
                    {compatible.map((material) => (
                      <li key={material.id}>
                        {material.title} · 第 {material.current_revision.number}{' '}
                        版
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>先在“材料与确认”中核对、确认并勾选材料。</p>
                )}
              </div>
              <CreationOptions
                skillId={skillId}
                value={options}
                onChange={(next) => {
                  setOptions(next);
                  setAuthorized(false);
                }}
                disabled={Boolean(pending)}
              />
              <FieldGroup className="sm:grid sm:grid-cols-3">
                <Field>
                  <FieldLabel htmlFor="creation-max-calls">
                    最多模型调用（次）
                  </FieldLabel>
                  <Input
                    id="creation-max-calls"
                    type="number"
                    min={1}
                    max={32}
                    value={budget.max_calls}
                    disabled={Boolean(pending)}
                    onChange={(event) => {
                      setBudget({
                        ...budget,
                        max_calls: Number(event.target.value),
                      });
                      setAuthorized(false);
                    }}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="creation-max-tokens">
                    Token 预留额度
                  </FieldLabel>
                  <Input
                    id="creation-max-tokens"
                    type="number"
                    min={1}
                    max={200_000}
                    value={budget.max_tokens}
                    disabled={Boolean(pending)}
                    onChange={(event) => {
                      setBudget({
                        ...budget,
                        max_tokens: Number(event.target.value),
                      });
                      setAuthorized(false);
                    }}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="creation-timeout">
                    处理时限（秒）
                  </FieldLabel>
                  <Input
                    id="creation-timeout"
                    type="number"
                    min={10}
                    max={3600}
                    value={budget.timeout_seconds}
                    disabled={Boolean(pending)}
                    onChange={(event) => {
                      setBudget({
                        ...budget,
                        timeout_seconds: Number(event.target.value),
                      });
                      setAuthorized(false);
                    }}
                  />
                </Field>
              </FieldGroup>
              <FieldDescription>
                模型任务按已配置线路处理已选材料，可能产生费用。Token
                额度用于调用前预留，当前不对实际消耗硬封顶。回执未知时保留预算占用，不会自动重复调用；本地整理和导出不代表调用了模型。
              </FieldDescription>
              {taskDirty ? (
                <FieldDescription>
                  另一份人工稿有未保存修改，请先在任务与版本中保存，再开始新任务。
                </FieldDescription>
              ) : null}
              <Field orientation="horizontal">
                <Checkbox
                  id="creation-task-authorized"
                  checked={authorized}
                  disabled={Boolean(pending)}
                  onCheckedChange={(checked) => setAuthorized(checked === true)}
                />
                <FieldLabel htmlFor="creation-task-authorized">
                  我已确认任务、材料、处理范围与调用预算，授权开始本次处理
                </FieldLabel>
              </Field>
              <div>
                <Button
                  type="submit"
                  disabled={
                    Boolean(pending) ||
                    !skill?.available ||
                    !compatible.length ||
                    !authorized ||
                    taskDirty
                  }
                >
                  {pending === 'task' ? '正在提交…' : '开始所选任务'}
                </Button>
              </div>
            </form>
          </TabsContent>
          <TabsContent
            value="tasks"
            forceMount
            className="mt-6 grid min-w-0 gap-8 data-[state=inactive]:hidden lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]"
          >
            <section
              aria-label="作品任务"
              className="min-w-0 grid content-start gap-4"
            >
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-lg font-medium">任务记录</h2>
                <Button variant="ghost" onClick={() => void tasks.refetch()}>
                  刷新
                </Button>
              </div>
              {tasks.error ? (
                <FeedbackNotice
                  title="任务列表读取失败"
                  description={displayError(tasks.error)}
                  tone="error"
                  action={
                    <Button
                      variant="outline"
                      onClick={() => void tasks.refetch()}
                    >
                      重新读取
                    </Button>
                  }
                />
              ) : null}
              {tasks.data?.length ? (
                tasks.data.map((task) => (
                  <Button
                    className="max-w-full justify-start"
                    key={task.id}
                    variant={task.id === taskId ? 'secondary' : 'ghost'}
                    onClick={() => navigate({ taskId: task.id })}
                  >
                    <span className="truncate">
                      {catalog.data?.find((item) => item.id === task.skill_id)
                        ?.name ?? '内容任务'}{' '}
                      · 第 {task.attempt} 次
                    </span>
                  </Button>
                ))
              ) : (
                <PageEmptyNotice
                  compact
                  title="还没有任务"
                  description="选择确认材料后，在新建任务中开始一次处理。"
                />
              )}
            </section>
            <section
              aria-label="当前任务"
              className="min-w-0 grid content-start gap-6"
            >
              {detail.isFetching && !detail.data && taskId ? (
                <p role="status">正在读取任务…</p>
              ) : null}
              {detail.error ? (
                <FeedbackNotice
                  title="任务读取失败"
                  description={displayError(detail.error)}
                  tone="error"
                  action={
                    <Button
                      variant="outline"
                      onClick={() => void detail.refetch()}
                    >
                      核对服务器状态
                    </Button>
                  }
                />
              ) : null}
              {detail.data ? (
                <>
                  <div className="flex flex-wrap items-center gap-3">
                    <h2 className="text-lg font-medium">
                      {taskSkill?.name ?? '内容任务'}
                    </h2>
                    {detail.data.stale ? (
                      <Badge variant="secondary">源材料已更新</Badge>
                    ) : null}
                    <Button
                      variant="ghost"
                      onClick={() => void detail.refetch()}
                    >
                      核对最新状态
                    </Button>
                  </div>
                  {detail.data.stale ? (
                    <p role="status">
                      这份稿件仍绑定旧材料版本。人工稿会保留；请主动选择新的确认材料重新处理，不会静默刷新或收费。
                    </p>
                  ) : null}
                  <CreationTaskStatus
                    task={detail.data}
                    busy={Boolean(pending)}
                    onCancel={async () => {
                      const next = await action('cancel', () =>
                        cancelCreationTask({ task_id: taskId }),
                      );
                      if (next) await updateTask(next);
                    }}
                    onRetry={async (acknowledge) => {
                      const input: API.CreationRetryRequest = {
                        acknowledge_unknown_cost: acknowledge,
                      };
                      const next = await action('retry', () =>
                        retryCreationTask({ task_id: taskId }, input, {
                          headers: {
                            'Idempotency-Key': idempotency(
                              `retry-${taskId}-${detail.data?.attempt}`,
                              input,
                            ),
                          },
                        }),
                      );
                      if (next) await updateTask(next);
                    }}
                  />
                  {detail.data.revision ? (
                    <CreationVersionEditor
                      key={detail.data.id}
                      task={detail.data}
                      materials={materials.data ?? []}
                      formats={taskSkill?.export_formats ?? []}
                      busy={Boolean(pending)}
                      onDirtyChange={setTaskDirty}
                      onUseAsMaterial={async (revisionId) => {
                        const input: API.CreationMaterialCreateRequest = {
                          project_id: projectId,
                          kind: 'text',
                          title: `${taskSkill?.name ?? '内容'} · 确认母稿`,
                          source_revision_id: revisionId,
                          rights_statement:
                            '仅在原材料已声明的权利和用途范围内，继续整理本作品的渠道稿。',
                        };
                        const scope = `master-${revisionId}`;
                        const created = await action('material-master', () =>
                          createCreationMaterial(input, {
                            headers: {
                              'Idempotency-Key': idempotency(scope, input),
                            },
                          }),
                        );
                        if (created) {
                          await refreshMaterials();
                          completeCreationOperation(scope);
                          setAuthorized(false);
                          setStep('materials');
                        }
                      }}
                      onSave={async (input) => {
                        const next = await action('task-edit', () =>
                          saveCreationTaskRevision({ task_id: taskId }, input, {
                            headers: {
                              'Idempotency-Key': idempotency(
                                `revision-${taskId}`,
                                input,
                              ),
                            },
                          }),
                        );
                        if (next) await updateTask(next);
                        return next;
                      }}
                      onConfirm={async (revisionId) => {
                        const next = await action('task-confirm', () =>
                          confirmCreationTask(
                            { task_id: taskId },
                            { expected_revision_id: revisionId },
                          ),
                        );
                        if (next) await updateTask(next);
                      }}
                    />
                  ) : null}
                </>
              ) : !taskId ? (
                <PageEmptyNotice
                  compact
                  title="选择一个任务"
                  description="查看真实处理状态、核对候选、编辑版本或取回交付文件。"
                />
              ) : null}
            </section>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
