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
    <ItemGroup className="gap-3">
      {items.map(([eyebrow, title, description]) => (
        <Item key={title} variant="muted" role="listitem">
          <ItemContent>
            <Badge className="w-fit" variant="secondary">
              {eyebrow}
            </Badge>
            <ItemTitle>
              <h3>{title}</h3>
            </ItemTitle>
            <ItemDescription className="line-clamp-none">
              {description}
            </ItemDescription>
          </ItemContent>
        </Item>
      ))}
    </ItemGroup>
  );
}
export function PublicHomeSafeguards({ items }: { items: readonly string[] }) {
  return (
    <ItemGroup className="gap-3">
      {items.map((item) => (
        <Item
          className="flex-nowrap items-start"
          key={item}
          variant="muted"
          role="listitem"
        >
          <ItemMedia variant="icon">
            <CheckCircleIcon aria-hidden />
          </ItemMedia>
          <ItemContent>
            <ItemDescription className="line-clamp-none">
              {item}
            </ItemDescription>
          </ItemContent>
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
    <ol aria-label="使用步骤" className="flex flex-col gap-3">
      {items.map(([title, description], index) => (
        <Item asChild key={title}>
          <li>
            <ItemMedia>
              <Badge variant="secondary">
                {String(index + 1).padStart(2, '0')}
              </Badge>
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
