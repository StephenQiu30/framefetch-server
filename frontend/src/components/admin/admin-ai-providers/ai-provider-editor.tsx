import { CheckCircle } from '@phosphor-icons/react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Form } from '@/components/ui/form';
import { Spinner } from '@/components/ui/spinner';

import { AiProviderFields } from './ai-provider-fields';
import type { AiProviderEditorState } from './model';

type Props = {
  editor: AiProviderEditorState;
  onChange: (values: Partial<AiProviderEditorState>) => void;
  onClose: () => void;
  onSave: () => void;
  onRestoreFocus?: () => void;
};

export function AiProviderEditor({
  editor,
  onChange,
  onClose,
  onSave,
  onRestoreFocus,
}: Props) {
  const creating = editor.mode === 'create';
  return (
    <Dialog
      open={editor.mode !== null}
      onOpenChange={(open) => {
        if (!open && !editor.saving) onClose();
      }}
    >
      <DialogContent
        className="max-h-svh overflow-y-auto overscroll-contain sm:max-w-xl"
        onCloseAutoFocus={(event) => {
          if (onRestoreFocus) {
            event.preventDefault();
            onRestoreFocus();
          }
        }}
      >
        <DialogHeader>
          <p className="mb-4 text-sm font-medium text-primary">AI 分析路由</p>
          <DialogTitle>
            {creating ? '新增 AI 服务' : `编辑 ${editor.displayName}`}
          </DialogTitle>
          <DialogDescription className="max-w-lg">
            本机登录模式复用当前用户的 Codex 或 Claude 登录；API Key
            会加密保存，仅在分析任务运行时交给所选适配器，不写入环境文件。
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
          <AiProviderFields editor={editor} onChange={onChange} />
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
              {editor.saving ? '正在保存' : '保存配置'}
            </Button>
          </DialogFooter>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
