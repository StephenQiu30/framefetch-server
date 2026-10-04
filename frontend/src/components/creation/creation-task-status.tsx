'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldLabel } from '@/components/ui/field';
import { localizedErrorMessage } from '@/lib/error-messages';

export function CreationTaskStatus({
  task,
  busy,
  onCancel,
  onRetry,
}: {
  task: API.CreationTaskResponse;
  busy: boolean;
  onCancel: () => Promise<void>;
  onRetry: (acknowledgeUnknownCost: boolean) => Promise<void>;
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  const active = task.status === 'queued' || task.status === 'processing';
  const unknown =
    task.status === 'outcome_unknown' ||
    (task.usage.unknown_operations ?? 0) > 0;
  return (
    <section aria-label="任务状态与预算" className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3" aria-live="polite">
        <Badge variant="secondary">{statusLabels[task.status]}</Badge>
        {active ? (
          <span role="status">结果由后台处理，离开页面后可继续取回。</span>
        ) : null}
      </div>
      <p className="text-sm text-muted-foreground">
        已预留调用 {task.usage.calls_reserved ?? '未提供'} 次 /{' '}
        {task.budget.max_calls ?? '未提供'} 次， 已预留 Token{' '}
        {task.usage.tokens_reserved ?? '未提供'} /{' '}
        {task.budget.max_tokens ?? '未提供'}。
        {task.budget.max_cost_minor !== null &&
        task.budget.max_cost_minor !== undefined
          ? ` 费用预留 ${task.usage.cost_minor_reserved} / ${task.budget.max_cost_minor}（${task.budget.currency} 最小货币单位）。`
          : ' 本任务没有可核对的金额上限，实际费用以配置线路及确定回执为准。'}
      </p>
      <p className="text-sm text-muted-foreground">
        Token
        额度用于调用前预留，当前不对实际消耗硬封顶；实际用量与费用需核对确定回执。
      </p>
      {unknown ? (
        <div className="grid gap-3" role="status">
          <p>
            调用回执或费用尚未确定。系统保留预算占用，不会自动重发；新的尝试可能重复计费。
          </p>
          <Field orientation="horizontal">
            <Checkbox
              id="creation-unknown-cost"
              checked={acknowledged}
              disabled={busy}
              onCheckedChange={(checked) => setAcknowledged(checked === true)}
            />
            <FieldLabel htmlFor="creation-unknown-cost">
              我已核对旧调用，理解费用仍不确定，并明确授权一次新的尝试
            </FieldLabel>
          </Field>
        </div>
      ) : null}
      {task.error_code ? (
        <p role="status" className="text-sm">
          {localizedErrorMessage(task.error_code) ??
            '任务未完成，请核对所选材料、线路与任务范围。'}{' '}
          保留的材料和人工版本仍可取回。
        </p>
      ) : null}
      {task.limitations.length ? (
        <ul className="grid list-disc gap-2 pl-5 text-sm text-muted-foreground">
          {task.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      ) : null}
      <div className="flex flex-wrap gap-3">
        {active ? (
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void onCancel()}
          >
            取消后续处理
          </Button>
        ) : null}
        {task.status === 'failed' ||
        task.status === 'cancelled' ||
        task.status === 'outcome_unknown' ? (
          <Button
            variant="outline"
            disabled={busy || (unknown && !acknowledged)}
            onClick={() => void onRetry(acknowledged)}
          >
            明确开始一次新尝试
          </Button>
        ) : null}
      </div>
    </section>
  );
}

const statusLabels: Record<API.CreationTaskResponse['status'], string> = {
  queued: '等待处理',
  processing: '正在处理',
  awaiting_confirmation: '候选待人工确认',
  completed: '已确认',
  failed: '处理失败',
  cancelled: '已取消',
  outcome_unknown: '调用结果未知',
};
