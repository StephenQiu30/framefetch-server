import { CheckCircle, WarningCircle } from '@phosphor-icons/react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
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
import { ItemDescription } from '@/components/ui/item';
import { Spinner } from '@/components/ui/spinner';
import { Switch } from '@/components/ui/switch';

import type { CatalogEditorState } from './model';

type ProviderCatalogEditorProps = {
  editor: CatalogEditorState;
  onChange: (values: Partial<CatalogEditorState>) => void;
  onClose: () => void;
  onSave: () => void;
};

export function ProviderCatalogEditor({
  editor,
  onChange,
  onClose,
  onSave,
}: ProviderCatalogEditorProps) {
  const creating = editor.mode === 'create';
  return (
    <Dialog
      open={editor.mode !== null}
      onOpenChange={(open) => {
        if (!open && !editor.saving) onClose();
      }}
    >
      <DialogContent className="max-h-svh overflow-y-auto overscroll-contain sm:max-w-lg">
        <DialogHeader>
          <ItemDescription className="line-clamp-none mb-4">
            平台目录
          </ItemDescription>
          <DialogTitle>
            {creating ? '新增平台' : `编辑 ${editor.displayName}`}
          </DialogTitle>
          <DialogDescription className="max-w-md">
            此处只维护状态页名称、排序与可见性，不会新增下载域名或执行能力。
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
              <FieldLabel htmlFor="catalog-key">目录键</FieldLabel>
              <Input
                autoComplete="off"
                disabled={!creating || editor.saving}
                id="catalog-key"
                maxLength={32}
                onChange={(event) => onChange({ key: event.target.value })}
                pattern="[a-z][a-z0-9_-]{0,31}"
                placeholder="example_video"
                required
                value={editor.key}
              />
              <FieldDescription>
                以小写字母开头，仅使用小写字母、数字、下划线或连字符；创建后不可修改。
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="catalog-name">显示名称</FieldLabel>
              <Input
                autoComplete="off"
                disabled={editor.saving}
                id="catalog-name"
                maxLength={80}
                onChange={(event) =>
                  onChange({ displayName: event.target.value })
                }
                placeholder="Example Video"
                required
                value={editor.displayName}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="catalog-sort">排序值</FieldLabel>
              <Input
                disabled={editor.saving}
                id="catalog-sort"
                inputMode="numeric"
                max={10000}
                min={0}
                onChange={(event) =>
                  onChange({ sortOrder: event.target.value })
                }
                required
                type="number"
                value={editor.sortOrder}
              />
              <FieldDescription>
                数值越小，在平台状态页越靠前。
              </FieldDescription>
            </Field>
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="catalog-visible">公开显示</FieldLabel>
                <FieldDescription>
                  关闭后从平台状态页隐藏，但保留目录配置。
                </FieldDescription>
              </FieldContent>
              <Switch
                checked={editor.visible}
                disabled={editor.saving}
                id="catalog-visible"
                onCheckedChange={(visible) => onChange({ visible })}
              />
            </Field>
            {!creating ? (
              <Alert>
                <AlertDescription className="flex items-center gap-2">
                  <Badge
                    variant={editor.systemRegistered ? 'default' : 'secondary'}
                  >
                    {editor.systemRegistered ? '系统已注册' : '仅目录'}
                  </Badge>
                  {editor.systemRegistered
                    ? '实际下载能力仍由后端安全 Profile 控制。'
                    : '该条目不会获得下载能力，仅用于状态页展示。'}
                </AlertDescription>
              </Alert>
            ) : null}
            {editor.error ? (
              <Alert variant="destructive">
                <WarningCircle aria-hidden />
                <AlertDescription>{editor.error}</AlertDescription>
              </Alert>
            ) : null}
          </FieldGroup>
          <DialogFooter>
            <Button
              disabled={editor.saving}
              onClick={onClose}
              type="button"
              variant="ghost"
            >
              取消
            </Button>
            <Button disabled={editor.saving} type="submit">
              {editor.saving ? (
                <Spinner aria-hidden data-icon="inline-start" />
              ) : (
                <CheckCircle data-icon="inline-start" />
              )}
              {editor.saving ? '正在保存' : creating ? '新增平台' : '保存更改'}
            </Button>
          </DialogFooter>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
