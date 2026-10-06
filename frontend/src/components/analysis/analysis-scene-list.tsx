import { cn } from 'cn';
import { Button } from '@/components/ui/button';
import { Item, ItemDescription } from '@/components/ui/item';

import { formatMilliseconds } from '@/lib/format';

export default function AnalysisSceneList({
  onSelectTime,
  scenes,
}: {
  onSelectTime?: (milliseconds: number) => void;
  scenes: API.VideoAnalysisResultResponse['scenes'];
}) {
  return (
    <ol className={cn('gap-2')}>
      {scenes.map((scene) => (
        <Item
          asChild
          className="grid gap-4 sm:grid-cols-[auto_minmax(0,1fr)]"
          key={scene.id}
        >
          <li>
            <Button
              className="w-fit tabular-nums self-baseline justify-start"
              disabled={!onSelectTime}
              onClick={() => onSelectTime?.(scene.start_ms)}
              type="button"
              variant="link"
            >
              {formatMilliseconds(scene.start_ms)}
            </Button>
            <div>
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <strong>
                  场景 {scene.index} · {scene.title}
                </strong>
                <span>{scene.location}</span>
              </div>
              <ItemDescription className="line-clamp-none mt-2">
                {scene.description}
              </ItemDescription>
              <ItemDescription className="line-clamp-none mt-3">
                {scene.narrative_function}
              </ItemDescription>
              <ItemDescription className="line-clamp-none mt-3">
                视觉规则：{scene.visual_rules.join(' · ')}
              </ItemDescription>
              {scene.continuity_risks.length ? (
                <ItemDescription className="line-clamp-none mt-2">
                  连续性风险：{scene.continuity_risks.join(' · ')}
                </ItemDescription>
              ) : null}
            </div>
          </li>
        </Item>
      ))}
    </ol>
  );
}
