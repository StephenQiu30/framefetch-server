import { CheckCircle, WarningCircle } from '@phosphor-icons/react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field';
import { Form } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Spinner } from '@/components/ui/spinner';
import { Switch } from '@/components/ui/switch';

import type { UserEditorState, UserQuotaDraft } from './model';

type UserEditorProps = {
  editor: UserEditorState;
  onRoleChange: (value: API.UserRole) => void;
  onActiveChange: (value: boolean) => void;
  onQuotaChange: <K extends keyof UserQuotaDraft>(
    field: K,
    value: UserQuotaDraft[K],
  ) => void;
  onClose: () => void;
  onSave: () => void;
};

export function UserEditor({
  editor,
  onRoleChange,
  onActiveChange,
  onQuotaChange,
  onClose,
  onSave,
}: UserEditorProps) {
  return (
    <Dialog
      open={Boolean(editor.user)}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-svh overflow-y-auto overscroll-contain sm:max-w-lg">
        <DialogHeader>
          <p className="mb-4 text-sm font-medium">账户权限</p>
          <DialogTitle>
            管理用户{editor.user ? `：${editor.user.username}` : ''}
          </DialogTitle>
          <DialogDescription className="max-w-md">
            角色和停用状态会在该用户下一次认证请求时立即生效。
          </DialogDescription>
        </DialogHeader>
        <Form
          aria-busy={editor.saving}
          className="grid gap-6"
          onSubmit={(event) => {
            event.preventDefault();
            if (!editor.saving) onSave();
          }}
        >
          <FieldGroup className="gap-6">
            <Field>
              <FieldLabel htmlFor="edit-role">账户身份</FieldLabel>
              <Select
                disabled={editor.saving}
                value={editor.role}
                onValueChange={(value) => onRoleChange(value as API.UserRole)}
              >
                <SelectTrigger className="w-full" id="edit-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="admin">管理员</SelectItem>
                    <SelectItem value="user">普通用户</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="edit-active">启用账号</FieldLabel>
                <FieldDescription>
                  停用后将撤销该账户的 Refresh 会话。
                </FieldDescription>
              </FieldContent>
              <Switch
                checked={editor.active}
                disabled={editor.saving}
                id="edit-active"
                onCheckedChange={onActiveChange}
              />
            </Field>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="edit-quota-exempt">配额豁免</FieldLabel>
                <FieldDescription>
                  管理员始终豁免；普通用户可按需单独豁免业务配额。
                </FieldDescription>
              </FieldContent>
              <Switch
                checked={editor.quota.exempt}
                disabled={editor.saving || editor.role === 'admin'}
                id="edit-quota-exempt"
                onCheckedChange={(value) => onQuotaChange('exempt', value)}
              />
            </Field>
            <FieldGroup className="grid gap-4 sm:grid-cols-2">
              <QuotaInput
                id="edit-quota-active"
                label="同时活跃任务"
                value={editor.quota.maxActiveTasks}
                onChange={(value) => onQuotaChange('maxActiveTasks', value)}
              />
              <QuotaInput
                id="edit-quota-daily-tasks"
                label="24 小时任务数"
                value={editor.quota.dailyTasks}
                onChange={(value) => onQuotaChange('dailyTasks', value)}
              />
              <QuotaInput
                id="edit-quota-daily-gib"
                inputMode="decimal"
                label="24 小时处理量（GiB）"
                min="0.000000001"
                step="any"
                value={editor.quota.dailyGiB}
                onChange={(value) => onQuotaChange('dailyGiB', value)}
              />
              <QuotaInput
                id="edit-quota-storage-gib"
                inputMode="decimal"
                label="保留存储（GiB）"
                min="0.000000001"
                step="any"
                value={editor.quota.storageGiB}
                onChange={(value) => onQuotaChange('storageGiB', value)}
              />
              <QuotaInput
                id="edit-quota-analysis"
                label="24 小时分析尝试"
                value={editor.quota.dailyAnalysisAttempts}
                onChange={(value) =>
                  onQuotaChange('dailyAnalysisAttempts', value)
                }
              />
            </FieldGroup>
            {editor.error ? (
              <Alert variant="destructive">
                <WarningCircle aria-hidden />
                <AlertDescription>{editor.error}</AlertDescription>
              </Alert>
            ) : null}
          </FieldGroup>
          <DialogFooter>
            <DialogClose asChild>
              <Button disabled={editor.saving} type="button" variant="ghost">
                取消
              </Button>
            </DialogClose>
            <Button disabled={editor.saving || !editor.user} type="submit">
              {editor.saving ? (
                <Spinner aria-hidden data-icon="inline-start" />
              ) : (
                <CheckCircle aria-hidden data-icon="inline-start" />
              )}
              {editor.saving ? '正在保存' : '保存更改'}
            </Button>
          </DialogFooter>
        </Form>
      </DialogContent>
    </Dialog>
  );
}

function QuotaInput({
  id,
  inputMode = 'numeric',
  label,
  min = '1',
  step = '1',
  value,
  onChange,
}: {
  id: string;
  inputMode?: 'decimal' | 'numeric';
  label: string;
  min?: string;
  step?: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        inputMode={inputMode}
        min={min}
        placeholder="使用系统默认"
        step={step}
        type="number"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  );
}
