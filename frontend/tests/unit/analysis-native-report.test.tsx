import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AnalysisNativeReport from '@/components/analysis/analysis-native-report';

const { exportReport } = vi.hoisted(() => ({ exportReport: vi.fn() }));
vi.mock('@/api/analyses', () => ({ exportAnalysisNativeReport: exportReport }));
vi.mock('@/components/analysis/analysis-report-download-link', () => ({
  default: ({
    children,
    format,
  }: {
    children: React.ReactNode;
    format: string;
  }) => <a href={`report.${format}`}>{children}</a>,
}));

function view(artifacts: { format: string }[]) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AnalysisNativeReport analysisId="owned-report" artifacts={artifacts} />
    </QueryClientProvider>,
  );
}

describe('saved native report artifacts', () => {
  beforeEach(() => vi.clearAllMocks());

  it('does not advertise absent files or request a preview', () => {
    view([{ format: 'markdown' }, { format: 'docx' }]);
    expect(
      screen.queryByRole('region', { name: '文件与排版' }),
    ).not.toBeInTheDocument();
    expect(exportReport).not.toHaveBeenCalled();
  });

  it('offers a bundle without fetching article HTML', () => {
    view([{ format: 'zip' }]);
    expect(
      screen.getByRole('link', { name: '下载原生拉片包' }),
    ).toHaveAttribute('href', 'report.zip');
    expect(exportReport).not.toHaveBeenCalled();
  });

  it('isolates native HTML without same-origin or script permissions', async () => {
    exportReport.mockResolvedValue({
      text: async () => '<div id="output">保存正文<script>bad()</script></div>',
    });
    view([{ format: 'html' }]);
    fireEvent.click(
      await screen.findByRole('button', { name: '查看公众号排版预览' }),
    );
    const frame = await screen.findByTitle('公众号原生排版预览');
    expect(frame).toHaveAttribute('sandbox', '');
    expect(frame).toHaveAttribute('referrerPolicy', 'no-referrer');
    expect(frame.getAttribute('srcdoc')).toContain(
      "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
    );
    expect(
      screen.getByRole('button', { name: '复制公众号正文' }),
    ).toBeEnabled();
    expect(exportReport).toHaveBeenCalledWith(
      { analysis_id: 'owned-report', report_format: 'html' },
      expect.objectContaining({ responseType: 'blob' }),
    );
  });
});
