import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { toEditorDocument } from '@/components/editor/document';
import { sanitizeRichText } from '@/components/editor/rich-text';
import { Viewer } from '@/components/editor/viewer';
import { extractMarkdownHeadings } from '@/components/screenplay/screenplay-document-toc';

const markdown =
  '# 标题 &amp; 来源\n\n[引用][source]  \n下一行\n\n3. 第一项\n   - 子项 **加粗**\n4. 第二项\n\n- [x] 完成\n- [ ] 待办\n\n| 字段 | 值 |\n| --- | --- |\n| 代码 | `a < b` |\n\n~~~js\n  const x = "<script>";\n~~~\n\n---\n\n[source]: https://example.com/source';

describe('shared Editor.js document and Viewer', () => {
  it('renders both Markdown and native block data with the same structure', () => {
    const document = toEditorDocument(markdown);
    const { container, rerender } = render(<Viewer value={markdown} />);
    const html = container.innerHTML;
    rerender(<Viewer value={document} />);
    expect(container.innerHTML).toBe(html);
    expect(
      screen.getByRole('heading', { name: '标题 & 来源' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '引用' })).toHaveAttribute(
      'href',
      'https://example.com/source',
    );
    expect(container.querySelector('p br')).toBeInTheDocument();
    expect(container.querySelector('ol')).toHaveAttribute('start', '3');
    expect(container.querySelector('ol li ol strong')).toHaveTextContent(
      '加粗',
    );
    expect(screen.getAllByRole('checkbox')[0]).toBeChecked();
    expect(screen.getAllByRole('checkbox')[1]).not.toBeChecked();
    expect(screen.getAllByRole('checkbox')[0]).toBeDisabled();
    expect(screen.getByRole('cell', { name: 'a < b' })).toBeInTheDocument();
    expect(container.querySelector('pre > code')?.textContent).toBe(
      '  const x = "<script>";\n',
    );
  });

  it('uses actual parsed headings for anchors, including setext and fenced code', () => {
    const source =
      '第一章\n===\n\n## 第二章 &amp; **人物**\n\n```md\n# 不是目录\n```';
    const headings = extractMarkdownHeadings(source);
    expect(headings.map((heading) => heading.text)).toEqual([
      '第一章',
      '第二章 & 人物',
    ]);
    render(
      <Viewer
        value={source}
        headingOffset={1}
        headingIds={headings.map((heading) => heading.id)}
      />,
    );
    expect(
      screen.getByRole('heading', { name: '第一章', level: 2 }),
    ).toHaveAttribute('id', headings[0].id);
    expect(
      screen.getByRole('heading', { name: '第二章 & 人物', level: 3 }),
    ).toHaveAttribute('id', headings[1].id);
  });

  it('shows literal HTML without altering fenced and inline code', () => {
    const { container } = render(
      <Viewer
        htmlPolicy="text"
        value={
          '<script>台词</script>\n\n`<b>inline</b>`\n\n```html\n<div>code</div>\n```'
        }
      />,
    );
    expect(container).toHaveTextContent('<script>台词</script>');
    expect(screen.getByText('<b>inline</b>')).toBeInTheDocument();
    expect(container.querySelector('pre > code')?.textContent).toBe(
      '<div>code</div>\n',
    );
    expect(container.querySelector('script')).toBeNull();
  });

  it('strips active block HTML, unsafe URLs and remote resources before editing or reading', () => {
    const text =
      '<strong onclick="alert(1)">正文</strong><img src="https://example.com/track"><script>alert(1)</script><a href="javascript:alert(1)">脚本</a><a href="/local">本地</a><a href="https://example.com" onclick="bad()">来源</a>';
    const { container } = render(
      <Viewer value={{ blocks: [{ type: 'paragraph', data: { text } }] }} />,
    );
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(container.querySelector('img, script, [onclick]')).toBeNull();
    expect(sanitizeRichText(text)).toBe(
      '<strong>正文</strong>脚本本地<a href="https://example.com/">来源</a>',
    );
  });
});
