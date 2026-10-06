import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';

export function MissingScreenplayDocument() {
  return (
    <div className="inner-page">
      <PageNavigation fallbackHref="/documents" />
      <PageHeader title="剧本文档" />
      <PageEmptyNotice
        className="mt-8"
        description="请返回剧本文档列表，选择一个仍可访问的文档。"
        title="剧本文档不存在"
        titleAs="h2"
      />
    </div>
  );
}
