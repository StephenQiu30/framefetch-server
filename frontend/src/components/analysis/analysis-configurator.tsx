'use client';

import { ArrowCounterClockwise } from '@phosphor-icons/react';
import { useAnalysisSkills } from '@/components/analysis/use-analysis-skills';
import {
  emptyAnalysisDraft,
  useWorkspaceState,
} from '@/components/layout/workspace-state-provider';
import { Button } from '@/components/ui/button';
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';

import { AnalysisExecutionNotice } from './analysis-execution-notice';

const MAX_PROMPT_LENGTH = 4_000;

export default function AnalysisConfigurator({
  busy,
  inputKind = 'video',
  inputId,
  onStart,
}: {
  busy: boolean;
  inputId: string;
  inputKind?: API.AnalysisInputKind;
  onStart: (input: API.AnalysisRequest) => void;
}) {
  const catalog = useAnalysisSkills(inputKind);
  const { analyses, setAnalyses } = useWorkspaceState();
  const draftKey = `${inputKind}:${inputId}`;
  const draft = analyses[draftKey] ?? emptyAnalysisDraft;
  const { skillId, language, customPrompt } = draft;
  function updateDraft(patch: Partial<typeof draft>) {
    setAnalyses((current) => ({
      ...current,
      [draftKey]: { ...(current[draftKey] ?? emptyAnalysisDraft), ...patch },
    }));
  }
  const selected = skillId
    ? catalog.skills.find((skill) => skill.id === skillId)
    : catalog.skills[0];
  // Late catalog data supplies a default without overwriting user input.
  const prompt = customPrompt ?? selected?.default_prompt ?? '';

  function changeSkill(value: string) {
    const next = catalog.skills.find((skill) => skill.id === value);
    if (!next) return;
    updateDraft({
      skillId: next.id,
      customPrompt:
        customPrompt === null || prompt === selected?.default_prompt
          ? next.default_prompt
          : prompt,
    });
  }

  function startAnalysis() {
    if (!selected) return;
    onStart({
      skill_id: selected.id,
      output_language: language,
      custom_prompt: prompt.trim() || null,
    });
  }

  return (
    <FieldGroup className="mt-10 gap-6">
      <FieldGroup className="grid gap-5 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor={controlId(inputKind, 'skill')}>
            {inputKind === 'screenplay' ? '文档任务' : '分析任务'}
          </FieldLabel>
          <Select
            disabled={catalog.loading || catalog.skills.length === 0}
            onValueChange={changeSkill}
            value={selected?.id ?? ''}
          >
            <SelectTrigger
              aria-describedby={controlId(inputKind, 'skill-description')}
              className="w-full"
              id={controlId(inputKind, 'skill')}
            >
              <SelectValue
                placeholder={
                  catalog.error
                    ? '清单加载失败'
                    : catalog.loading
                      ? '正在加载…'
                      : catalog.skills.length === 0
                        ? '暂无可用任务'
                        : '请选择任务'
                }
              />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {catalog.skills.map((skill) => (
                  <SelectItem key={skill.id} value={skill.id}>
                    {skill.display_name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <FieldDescription id={controlId(inputKind, 'skill-description')}>
            {catalog.error ? (
              <>
                任务清单加载失败。{' '}
                <Button
                  className="align-baseline"
                  onClick={() => void catalog.retry()}
                  variant="link"
                  type="button"
                >
                  重试
                </Button>
              </>
            ) : catalog.loading ? (
              '正在加载可用的分析任务…'
            ) : catalog.skills.length === 0 ? (
              <>
                当前没有可用的分析任务。{' '}
                <Button
                  className="align-baseline"
                  onClick={() => void catalog.retry()}
                  variant="link"
                  type="button"
                >
                  刷新清单
                </Button>
              </>
            ) : !selected ? (
              '之前选择的任务 已不可用，请重新选择。'
            ) : (
              selected.description
            )}
          </FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor={controlId(inputKind, 'language')}>
            输出语言
          </FieldLabel>
          <Select
            onValueChange={(value) =>
              updateDraft({ language: value as typeof language })
            }
            value={language}
          >
            <SelectTrigger
              className="w-full"
              id={controlId(inputKind, 'language')}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="zh-CN">简体中文</SelectItem>
                <SelectItem value="en-US">English</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <FieldDescription>
            {selected?.result_contract === 'screenplay-rewrite'
              ? '与原文语言相同表示润色，不同表示跨语言改写。'
              : '使用所选语言撰写结果。'}
          </FieldDescription>
        </Field>
      </FieldGroup>

      <Field>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <FieldLabel htmlFor={controlId(inputKind, 'prompt')}>
            {inputKind === 'screenplay' ? '分析或整理要求' : '分析提示词'}
          </FieldLabel>
          <Button
            disabled={!selected || prompt === selected.default_prompt}
            onClick={() =>
              selected && updateDraft({ customPrompt: selected.default_prompt })
            }
            size="sm"
            type="button"
            variant="ghost"
          >
            <ArrowCounterClockwise data-icon="inline-start" />
            恢复模式默认值
          </Button>
        </div>
        <Textarea
          id={controlId(inputKind, 'prompt')}
          maxLength={MAX_PROMPT_LENGTH}
          onChange={(event) =>
            updateDraft({ customPrompt: event.target.value })
          }
          rows={5}
          value={prompt}
        />
        <div className="flex items-start justify-between gap-4 text-sm text-muted-foreground">
          <span>
            可补充阅读对象、分析重点或希望整理的问题，也可以清空使用任务默认要求。
          </span>
          <span aria-live="polite" className="shrink-0 tabular-nums">
            {prompt.length}/{MAX_PROMPT_LENGTH}
          </span>
        </div>
      </Field>

      <AnalysisExecutionNotice
        busy={busy}
        inputKind={inputKind}
        onStart={startAnalysis}
        resultContract={selected?.result_contract}
      />
    </FieldGroup>
  );
}

function controlId(inputKind: API.AnalysisInputKind, field: string) {
  return `${inputKind === 'video' ? 'analysis' : 'screenplay-analysis'}-${field}`;
}
