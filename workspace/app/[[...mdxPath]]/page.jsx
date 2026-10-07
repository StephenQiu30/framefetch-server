import { Mermaid } from '@theguild/remark-mermaid/mermaid';
import { notFound } from 'next/navigation';
import { compileMdx } from 'nextra/compile';
import { evaluate } from 'nextra/evaluate';
import { cache } from 'react';
import { readContentFile } from '@/lib/workspace/content';
import remarkRepoLinks from '../../lib/remark-repo-links.mjs';
import { useMDXComponents as getMDXComponents } from '../../mdx-components';


// 正文、目录和搜索都在请求时读取同一份挂载内容，不缓存旧页面或旧 404。
export const dynamic = 'force-dynamic';

const loadPage = cache(async (route) => {
  const segments = route ? route.split('/') : undefined;
  const file = await readContentFile(segments);
  if (!file) notFound();
  const rawJs = await compileMdx(file.source, {
    filePath: `content/${file.path}`,
    isPageImport: true,
    search: true,
    defaultShowCopyCode: true,
    mdxOptions: { format: 'detect', remarkPlugins: [remarkRepoLinks] },
  });
  // 运行时编译不经过 Nextra 的页面导入，需要显式提供 MDX 引用的组件。
  const components = getMDXComponents({ Mermaid });
  return { file, ...evaluate(rawJs, components) };
});

export async function generateMetadata({ params }) {
  const { metadata } = await loadPage((await params).mdxPath?.join('/') ?? '');
  return metadata;
}

const Wrapper = getMDXComponents().wrapper;

export default async function Page(props) {
  const params = await props.params;
  const {
    default: MDXContent,
    toc,
    metadata,
    file,
  } = await loadPage(params.mdxPath?.join('/') ?? '');
  return (
    <Wrapper toc={toc} metadata={metadata} sourceCode={file.source}>
      <MDXContent {...props} params={params} />
    </Wrapper>
  );
}
