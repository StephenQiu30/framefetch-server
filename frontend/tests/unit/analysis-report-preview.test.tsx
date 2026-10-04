import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';

describe('analysis report Markdown reader', () => {
  it('preserves the accepted article fixture hard break, code whitespace and source digest', () => {
    const code = 'heading = "# 不是标题"\n  value = "标签：不是正文标签"\n';
    const sha =
      'ae24e0fe74f663e0ee22f2031f95fa4f17acbd718316b5dbd5977584b7862aeb';
    const { container } = render(
      <AnalysisReportPreview
        markdown={[
          '# 内置 Skill 整理验收',
          '',
          '这是一份已有文章，保留作者观点，不追加新事实。  ',
          '下一行验证两个空格的换行语义。',
          '',
          '> 原文引用：整理只改变呈现结构。',
          '',
          '| 字段 | 原值 |',
          '| --- | --- |',
          '| 状态 | 已有正文 |',
          '',
          `\`\`\`python\n${code}\`\`\``,
          '',
          `primary：输入文本；SHA-256 \`${sha}\``,
        ].join('\n')}
      />,
    );

    expect(container.querySelector('p br')).toBeInTheDocument();
    expect(container.querySelector('pre > code')?.textContent).toBe(code);
    expect(container.querySelector('blockquote')).toHaveTextContent(
      '原文引用：整理只改变呈现结构。',
    );
    expect(screen.getByRole('cell', { name: '已有正文' })).toBeInTheDocument();
    expect(screen.getByText(sha)).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('keeps explicit web links while rejecting executable, local, embedded and HTML resources', () => {
    const { container } = render(
      <AnalysisReportPreview
        markdown={[
          '[安全来源](https://example.com/reference?q=1)',
          '[本地测试来源](http://127.0.0.1:8101/source)',
          '[脚本链接](javascript:alert%281%29)',
          '[嵌入链接](data:text/html,test)',
          '[文件链接](file:///tmp/private)',
          '[相对链接](/account)',
          '![外部图像](https://example.com/image.png)',
          '<a href="https://example.com/html">HTML 链接</a>',
          '<script>alert(1)</script>',
        ].join('\n\n')}
      />,
    );

    expect(screen.getAllByRole('link')).toHaveLength(2);
    expect(screen.getByRole('link', { name: '安全来源' })).toHaveAttribute(
      'href',
      'https://example.com/reference?q=1',
    );
    for (const link of screen.getAllByRole('link')) {
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('script')).toBeNull();
    expect(
      screen.queryByRole('link', { name: /脚本|嵌入|文件|相对|HTML/ }),
    ).not.toBeInTheDocument();
  });
});
