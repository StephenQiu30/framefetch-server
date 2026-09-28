'use client';

import {
  CheckCircleIcon,
  InfoIcon,
  WarningCircleIcon,
} from '@phosphor-icons/react';
import { cn } from 'cn';
import { type ReactNode, useEffect, useId } from 'react';
import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';

type FeedbackTone = 'error' | 'info' | 'success';

export function FeedbackNotice({
  action,
  className,
  description,
  descriptionId,
  id,
  role,
  title,
  tone = 'info',
  presentation = 'inline',
}: {
  action?: ReactNode;
  className?: string;
  description: ReactNode;
  descriptionId?: string;
  id?: string;
  role?: 'alert' | 'status';
  title?: ReactNode;
  tone?: FeedbackTone;
  presentation?: 'inline' | 'toast';
}) {
  const toastId = useId();
  useEffect(() => {
    if (presentation !== 'toast' || !description) return;
    toast[tone](title ?? description, {
      id: toastId,
      description: title ? description : undefined,
    });
  }, [description, presentation, title, toastId, tone]);

  if (presentation === 'toast') return null;

  if (tone === 'error' && action && title) {
    return (
      <Empty
        aria-atomic="true"
        aria-live="assertive"
        className={cn('flex-none', className)}
        id={id}
        role={role ?? 'alert'}
      >
        <EmptyHeader className="max-w-md">
          <EmptyMedia variant="icon">
            <WarningCircleIcon aria-hidden className="text-destructive" />
          </EmptyMedia>
          <EmptyTitle>{title}</EmptyTitle>
          <EmptyDescription id={descriptionId}>{description}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent className="flex-row flex-wrap justify-center">
          {action}
        </EmptyContent>
      </Empty>
    );
  }

  const icon =
    tone === 'error' ? (
      <WarningCircleIcon aria-hidden />
    ) : tone === 'success' ? (
      <CheckCircleIcon aria-hidden />
    ) : (
      <InfoIcon aria-hidden />
    );

  return (
    <Alert
      className={className}
      id={id}
      role={role ?? 'alert'}
      variant={tone === 'error' ? 'destructive' : 'default'}
    >
      {icon}
      {title ? <AlertTitle>{title}</AlertTitle> : null}
      <AlertDescription id={descriptionId} className="min-w-0">
        {description}
        {action ? (
          <div className="mt-3 flex flex-wrap gap-2">{action}</div>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
