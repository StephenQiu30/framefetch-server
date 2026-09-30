import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import { Progress } from '@/components/ui/progress';
import { Spinner } from '@/components/ui/spinner';

export function HomeStartup() {
  return (
    <Empty aria-atomic="true" aria-live="polite" data-home-boot role="status">
      <EmptyMedia variant="icon">
        <Spinner aria-hidden role="presentation" />
      </EmptyMedia>
      <EmptyHeader data-home-boot-copy>
        <EmptyTitle>正在确认当前会话</EmptyTitle>
        <EmptyDescription>
          工作区准备完成后，只呈现与你登录状态匹配的页面。
        </EmptyDescription>
      </EmptyHeader>
      <Progress
        aria-label="正在确认当前会话"
        className="max-w-md"
        data-home-boot-line
        value={null}
      />
    </Empty>
  );
}
