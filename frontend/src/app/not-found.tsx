import { NotFoundActions } from '@/components/layout/not-found-actions';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';

export default function NotFound() {
  return (
    <PageEmptyNotice
      action={<NotFoundActions />}
      className="py-14 sm:py-20"
      description="这个地址可能已经移动或失效。返回上一步，或回到首页重新粘贴一个公开视频链接。"
      eyebrow="404"
      title="页面，没有找到。"
      titleAs="h1"
      titleClassName="text-4xl leading-none tracking-tight sm:text-5xl"
    />
  );
}
