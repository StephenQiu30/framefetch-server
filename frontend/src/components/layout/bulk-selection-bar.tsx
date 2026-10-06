import { type ReactNode, useId } from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Field,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field';

export function BulkSelectionBar({
  all,
  some,
  count,
  busy,
  onSelectAll,
  onClear,
  children,
}: {
  all?: boolean;
  some?: boolean;
  count: number;
  busy: boolean;
  onSelectAll?: (checked: boolean) => void;
  onClear?: () => void;
  children: ReactNode;
}) {
  const id = useId();
  if (count === 0 && !onSelectAll) return null;
  return (
    <FieldSet
      className="min-w-0 flex-row flex-wrap items-center gap-3"
      aria-label="批量操作"
    >
      <FieldLegend className="sr-only">批量操作</FieldLegend>
      {onSelectAll ? (
        <Field orientation="horizontal" className="w-auto">
          <Checkbox
            id={id}
            aria-label="全选本页"
            checked={all ? true : some ? 'indeterminate' : false}
            disabled={busy}
            onCheckedChange={(checked) => onSelectAll(checked === true)}
          />
          <FieldLabel htmlFor={id}>全选本页</FieldLabel>
        </Field>
      ) : null}
      <span aria-live="polite">{count ? `已选 ${count} 项` : null}</span>
      {count > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          {children}
          {onClear ? (
            <Button variant="ghost" disabled={busy} onClick={onClear}>
              取消选择
            </Button>
          ) : null}
        </div>
      ) : null}
    </FieldSet>
  );
}
