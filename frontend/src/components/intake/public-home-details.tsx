import { CheckCircleIcon } from '@phosphor-icons/react/dist/ssr';

import { Badge } from '@/components/ui/badge';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from '@/components/ui/item';

type Capability = readonly [
  eyebrow: string,
  title: string,
  description: string,
];
type WorkflowStep = readonly [title: string, description: string];

export function PublicHomeCapabilities({
  items,
}: {
  items: readonly Capability[];
}) {
  return (
    <ul className="mt-12 grid gap-4 md:grid-cols-3">
      {items.map(([eyebrow, title, description], index) => (
        <li className="flex h-full flex-col gap-3" key={title}>
          <div className="flex items-center justify-between gap-3">
            <Badge variant="secondary">
              {String(index + 1).padStart(2, '0')}
            </Badge>
            <span className="text-xs font-medium text-muted-foreground">
              {eyebrow}
            </span>
          </div>
          <h3 className="text-xl font-semibold leading-7 tracking-tight">
            {title}
          </h3>
          <p className="text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function PublicHomeSafeguards({ items }: { items: readonly string[] }) {
  return (
    <ItemGroup className="gap-4">
      {items.map((item) => (
        <Item
          className="flex-nowrap items-start gap-3"
          key={item}
          role="listitem"
        >
          <ItemMedia className="mb-0" variant="icon">
            <CheckCircleIcon
              aria-hidden
              className="text-success"
              weight="fill"
            />
          </ItemMedia>
          <ItemDescription className="line-clamp-none">{item}</ItemDescription>
        </Item>
      ))}
    </ItemGroup>
  );
}

export function PublicHomeWorkflow({
  items,
}: {
  items: readonly WorkflowStep[];
}) {
  return (
    <ol aria-label="使用步骤" className="flex w-full flex-col gap-2">
      {items.map(([title, description], index) => (
        <Item
          asChild
          className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3"
          key={title}
        >
          <li>
            <ItemMedia className="mb-0">
              {String(index + 1).padStart(2, '0')}
            </ItemMedia>
            <ItemContent>
              <ItemTitle>{title}</ItemTitle>
              <ItemDescription className="line-clamp-none">
                {description}
              </ItemDescription>
            </ItemContent>
          </li>
        </Item>
      ))}
    </ol>
  );
}
