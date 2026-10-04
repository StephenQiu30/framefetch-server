import { PageEmptyNotice } from '@/components/layout/page-empty-notice';

export function CreationComparison({
  previous,
  current,
}: {
  previous: string;
  current: string;
}) {
  if (previous === current) {
    return (
      <PageEmptyNotice
        compact
        title="正文没有变化"
        description="当前编辑内容与所选版本一致。结构化内容仍请在对应编辑区核对。"
      />
    );
  }
  return (
    <div className="grid min-w-0 gap-6 lg:grid-cols-2">
      <section aria-label="比较版本正文" className="min-w-0">
        <h3 className="font-medium">比较版本</h3>
        <pre className="mt-3 whitespace-pre-wrap break-words font-sans text-sm leading-6">
          {previous || '（空正文）'}
        </pre>
      </section>
      <section aria-label="当前编辑正文" className="min-w-0">
        <h3 className="font-medium">当前编辑内容</h3>
        <pre className="mt-3 whitespace-pre-wrap break-words font-sans text-sm leading-6">
          {current || '（空正文）'}
        </pre>
      </section>
    </div>
  );
}
