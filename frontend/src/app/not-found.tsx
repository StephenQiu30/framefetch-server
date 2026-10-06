import { NotFoundActions } from '@/components/layout/not-found-actions';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';

export default function NotFound() {
  return (
    <div className="inner-page flex flex-col gap-8">
      <div>
        <PageNavigation fallbackHref="/" />
        <PageHeader title="页面，没有找到。" description="404" />
      </div>
      <PageEmptyNotice
        action={<NotFoundActions />}
        description="这个地址可能已经移动或失效。返回上一步，或回到首页重新粘贴一个公开视频链接。"
        title="试试其他入口"
      />
    </div>
  );
}
