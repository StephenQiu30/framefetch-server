import { generateStaticParamsFor, importPage } from 'nextra/pages';
import { EditLink } from '@/components/workspace/edit-link';
import { useMDXComponents as getMDXComponents } from '../../mdx-components';

type PageProps = { params: Promise<{ mdxPath?: string[] }> };

export const generateStaticParams = generateStaticParamsFor('mdxPath');

export async function generateMetadata({ params }: PageProps) {
  const { metadata } = await importPage((await params).mdxPath);
  return metadata;
}

const Wrapper = getMDXComponents().wrapper;

export default async function Page(props: PageProps) {
  const params = await props.params;
  const {
    default: MDXContent,
    toc,
    metadata,
    sourceCode,
  } = await importPage(params.mdxPath);
  const filePath =
    typeof metadata.filePath === 'string'
      ? metadata.filePath.replace(/^content\//, '')
      : undefined;
  return (
    <Wrapper toc={toc} metadata={metadata} sourceCode={sourceCode}>
      {filePath?.endsWith('.md') && <EditLink path={filePath} />}
      <MDXContent {...props} params={params} />
    </Wrapper>
  );
}
