import { act, render, screen, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it } from 'vitest';
import { markdownToEditorDocument } from '@/components/editor/document';
import { Editor, type EditorHandle } from '@/components/editor/editor';
import { sanitizeRichText } from '@/components/editor/rich-text';
import { Viewer } from '@/components/editor/viewer';
import { extractMarkdownHeadings } from '@/components/screenplay/screenplay-document-toc';

const markdown =
  '# 标题 &amp; 来源\n\n[引用][source]  \n下一行\n\n3. 第一项\n   - 子项 **加粗**\n4. 第二项\n\n- [x] 完成\n- [ ] 待办\n\n| 字段 | 值 |\n| --- | --- |\n| 代码 | `a < b` |\n\n~~~js\n  const x = "<script>";\n~~~\n\n---\n\n[source]: https://example.com/source';

async function ready() {
  await waitFor(() =>
    expect(screen.queryByRole('status')).not.toBeInTheDocument(),
  );
}

describe('official Editor.js Editor and Viewer', () => {
  it('uses official read-only blocks, including lists, checklists, tables and code', async () => {
    const { container } = render(
      <Viewer value={markdownToEditorDocument(markdown)} />,
    );
    await ready();
    expect(
      container.querySelector('.block-editor--readonly'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: '标题 & 来源' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '引用' })).toHaveAttribute(
      'href',
      'https://example.com/source',
    );
    expect(container.querySelector('.ce-paragraph br')).toBeInTheDocument();
    expect(container.querySelector('.cdx-list')).toHaveTextContent('子项 加粗');
    expect(container.querySelector('.tc-cell')).toBeInTheDocument();
    expect(container).toHaveTextContent('a < b');
    expect(container.querySelector('textarea')).toHaveValue(
      '  const x = "<script>";\n',
    );
    expect(container.querySelector('textarea')).toBeDisabled();
    expect(container.querySelector('[contenteditable="true"]')).toBeNull();
  });

  it('imports ordinary and task items as separate native list styles', async () => {
    const document = markdownToEditorDocument(
      '- 普通项目\n\n- [x] 已完成\n- [ ] 待办\n',
    );
    expect(document.blocks.map((block) => block.data.style)).toEqual([
      'unordered',
      'checklist',
    ]);
    const { container } = render(<Viewer value={document} />);
    await ready();
    expect(container.querySelectorAll('.cdx-list-unordered')).toHaveLength(1);
    expect(container.querySelectorAll('.cdx-list-checklist')).toHaveLength(1);
  });

  it('preserves heading anchors, including setext and fenced code', async () => {
    const source =
      '第一章\n===\n\n## 第二章 &amp; **人物**\n\n```md\n# 不是目录\n```';
    const headings = extractMarkdownHeadings(source);
    expect(headings.map((heading) => heading.text)).toEqual([
      '第一章',
      '第二章 & 人物',
    ]);
    render(
      <Viewer
        value={markdownToEditorDocument(source)}
        headingOffset={1}
        headingIds={headings.map((heading) => heading.id)}
      />,
    );
    await ready();
    expect(
      screen.getByRole('heading', { name: '第一章', level: 2 }),
    ).toHaveAttribute('id', headings[0].id);
    expect(
      screen.getByRole('heading', { name: '第二章 & 人物', level: 3 }),
    ).toHaveAttribute('id', headings[1].id);
  });

  it('shows literal HTML and code while disabling document links', async () => {
    const { container } = render(
      <Viewer
        links={false}
        value={markdownToEditorDocument(
          '<script>台词</script>\n\n`<b>inline</b>`\n\n[来源](https://example.com)\n\n```html\n<div>code</div>\n```',
          'text',
        )}
      />,
    );
    await ready();
    expect(container).toHaveTextContent('<script>台词</script>');
    expect(screen.getByText('<b>inline</b>')).toBeInTheDocument();
    expect(container.querySelector('textarea')).toHaveValue(
      '<div>code</div>\n',
    );
    expect(container.querySelector('script, a')).toBeNull();
  });

  it('sanitizes markup before official tools render it and keeps unknown blocks in Stub', async () => {
    const text =
      '<strong onclick="bad()">正文</strong><img src="https://example.com/track"><script>bad()</script><a href="javascript:bad()">脚本</a><a href="/local">本地</a><a href="https://example.com" onclick="bad()">来源</a>';
    const { container } = render(
      <Viewer
        value={{
          blocks: [
            { type: 'paragraph', data: { text } },
            { type: 'unknown', data: { text: '原始块' } },
          ],
        }}
      />,
    );
    await ready();
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(container.querySelector('img, script, [onclick]')).toBeNull();
    expect(container.querySelector('.ce-stub')).toBeInTheDocument();
    expect(sanitizeRichText(text)).toBe(
      '<strong>正文</strong>脚本本地<a href="https://example.com/">来源</a>',
    );
  });

  it('keeps pending edits and unknown tool data across real read-only toggles', async () => {
    const ref = createRef<EditorHandle>();
    const document = {
      blocks: [
        { type: 'paragraph', data: { text: '旧正文' } },
        { id: 'unknown-id', type: 'unknown', data: { source: '原始块' } },
      ],
    };
    const { container, rerender } = render(
      <Editor value={document} ref={ref} />,
    );
    await ready();
    const field = container.querySelector('.ce-paragraph') as HTMLElement;
    await act(async () => {
      field.innerHTML = '尚未回传的新编辑';
    });
    rerender(<Editor value={document} ref={ref} readOnly />);
    await waitFor(() =>
      expect(container.querySelector('[contenteditable="true"]')).toBeNull(),
    );
    expect(container.querySelector('.ce-paragraph')).toHaveTextContent(
      '尚未回传的新编辑',
    );
    await expect(ref.current?.save()).rejects.toThrow('只读模式不能保存正文');
    rerender(<Editor value={document} ref={ref} />);
    await waitFor(() =>
      expect(
        container.querySelector('[contenteditable="true"]'),
      ).toBeInTheDocument(),
    );
    const saved = await ref.current?.save();
    expect(saved?.blocks[0].data.text).toBe('尚未回传的新编辑');
    expect(saved?.blocks[1]).toEqual(document.blocks[1]);
  });
});
