import { cn } from 'cn';
import type { ComponentProps, ReactNode } from 'react';

type EditorialIntroProps = Omit<ComponentProps<'div'>, 'title'> & {
  as?: 'h1' | 'h2';
  className?: string;
  description: ReactNode;
  descriptionClassName?: string;
  eyebrow?: string;
  title: ReactNode;
  titleClassName?: string;
  titleId?: string;
};

export function EditorialIntro({
  as = 'h1',
  children,
  className,
  description,
  descriptionClassName,
  eyebrow,
  title,
  titleClassName,
  titleId,
  ...props
}: EditorialIntroProps) {
  const Heading = as;

  return (
    <div
      className={cn('min-w-0', className)}
      data-slot="editorial-intro"
      {...props}
    >
      {eyebrow ? (
        <p className="font-mono text-xs text-muted-foreground">{eyebrow}</p>
      ) : null}
      <Heading
        className={cn(
          as === 'h1'
            ? 'editorial-title'
            : 'text-balance text-2xl font-semibold tracking-tight sm:text-3xl',
          eyebrow && 'mt-5',
          titleClassName,
        )}
        id={titleId}
      >
        {title}
      </Heading>
      <p
        className={cn(
          'mt-4 max-w-2xl text-lg leading-7 text-muted-foreground',
          descriptionClassName,
        )}
      >
        {description}
      </p>
      {children}
    </div>
  );
}
