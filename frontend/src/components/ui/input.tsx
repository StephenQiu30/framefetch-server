import { cn } from 'cn';
import type * as React from 'react';

function Input({
  className,
  type,
  controlSize = 'default',
  ...props
}: React.ComponentProps<'input'> & { controlSize?: 'default' | 'xl' }) {
  return (
    <input
      type={type}
      data-slot="input"
      data-size={controlSize}
      className={cn(
        'h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 py-1 text-base transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm dark:bg-input/30 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40',
        controlSize === 'xl' && 'h-control-xl px-4 text-base md:text-base',
        className,
      )}
      {...props}
    />
  );
}

export { Input };
