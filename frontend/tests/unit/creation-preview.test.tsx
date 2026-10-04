import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CreationComparison } from '@/components/creation/creation-comparison';
import { CreationExports } from '@/components/creation/creation-exports';
import { CreationSafePreview } from '@/components/creation/creation-safe-preview';
import { creationRevision, creationTask } from '../helpers/creation-fixtures';
import { httpRequests, mockHttpResponses } from '../helpers/http';
import { render } from '../helpers/query-render';

describe('creation safe preview and comparison', () => {
  it('keeps untrusted HTML in an opaque sandbox with no scripts or network', () => {
    render(
      <CreationSafePreview html='<script>fetch("/api/users/me")</script><img src="https://example.com/track">' />,
    );
    const frame = screen.getByTitle('公众号安全预览');
    expect(frame).toHaveAttribute('sandbox', '');
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer');
    expect(frame.getAttribute('srcdoc')).toContain("script-src 'none'");
    expect(frame.getAttribute('srcdoc')).toContain("connect-src 'none'");
    expect(frame.getAttribute('srcdoc')).toContain('img-src data: blob:');
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('img')).toBeNull();
  });

  it('shows both bodies as text and preserves long content', () => {
    render(
      <CreationComparison
        previous="原稿数字 10"
        current="新稿数字 12 <script>"
      />,
    );
    expect(
      screen.getByRole('region', { name: '比较版本正文' }),
    ).toHaveTextContent('原稿数字 10');
    expect(
      screen.getByRole('region', { name: '当前编辑正文' }),
    ).toHaveTextContent('新稿数字 12 <script>');
    expect(document.querySelector('script')).toBeNull();
  });

  it('requires confirmation before exporting or previewing a candidate', () => {
    render(
      <CreationExports
        task={creationTask}
        formats={['html', 'md']}
        unsaved={false}
      />,
    );
    expect(screen.getByRole('button', { name: '导出 HTML' })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: '查看安全 HTML 预览' }),
    ).toBeDisabled();
    expect(httpRequests()).toHaveLength(0);
  });

  it('previews the exact confirmed revision through the authenticated binary export contract', async () => {
    mockHttpResponses(
      new Blob(['<p>确认稿内容</p><script>blocked()</script>'], {
        type: 'text/html',
      }),
    );
    render(
      <CreationExports
        task={{
          ...creationTask,
          revision: { ...creationRevision, confirmed: true },
        }}
        formats={['html']}
        unsaved={false}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '查看安全 HTML 预览' }));
    const frame = await screen.findByTitle('公众号安全预览');
    expect(frame).toHaveAttribute('sandbox', '');
    expect(frame.getAttribute('srcdoc')).toContain('确认稿内容');
    expect(httpRequests()).toHaveLength(1);
    expect(httpRequests()[0]).toMatchObject({
      url: '/api/creation/tasks/task-1/revisions/revision-1/export/html',
      method: 'GET',
      responseType: 'blob',
    });
  });
});
