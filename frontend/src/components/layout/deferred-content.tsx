'use client';

import { type ComponentProps, type ReactNode, useRef } from 'react';
import { useNearViewport } from '@/hooks/use-near-viewport';

export function DeferredContent({
  children,
  placeholder,
  eager = false,
  ...props
}: ComponentProps<'div'> & { placeholder: ReactNode; eager?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const activated = useNearViewport(ref, eager);
  return (
    <div
      {...props}
      ref={ref}
      data-slot="deferred-content"
      aria-busy={!activated || undefined}
    >
      {activated ? children : placeholder}
    </div>
  );
}
