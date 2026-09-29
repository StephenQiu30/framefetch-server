import { cn } from 'cn';
import type * as React from 'react';
import { Button } from '@/components/ui/button';
import { Field, FieldGroup } from '@/components/ui/field';

export function IntakePickerButton({
  className,
  ...props
}: React.ComponentProps<typeof Button>) {
  return (
    <Button
      className={cn('min-w-0 justify-start', className)}
      type="button"
      variant="secondary"
      {...props}
    />
  );
}

export function IntakeSubmitButton({
  className,
  ...props
}: React.ComponentProps<typeof Button>) {
  return <Button className={className} size="xl" type="submit" {...props} />;
}

export function IntakeControlRow(props: React.ComponentProps<typeof Field>) {
  return (
    <FieldGroup>
      <Field orientation="responsive" {...props} />
    </FieldGroup>
  );
}
