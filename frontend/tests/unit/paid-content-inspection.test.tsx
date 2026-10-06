import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import InspectionWorkspace from '@/components/intake/inspection-workspace';
import { inspection } from '../fixtures/download-fixtures';

describe('paid content inspection', () => {
  it('keeps the media title and metadata aligned to the left', () => {
    render(
      <InspectionWorkspace
        busy={false}
        inspection={inspection}
        onChange={vi.fn()}
        onCreate={vi.fn()}
        onUseUpload={vi.fn()}
        selectedId={inspection.formats[0].id}
      />,
    );

    expect(
      screen.getByRole('heading', { name: inspection.title, level: 1 }),
    ).toBeVisible();
    expect(screen.getByRole('region', { name: '媒体信息' })).toContainElement(
      screen.getByRole('heading', { name: inspection.title }),
    );
    expect(screen.getByLabelText('媒体规格').tagName).toBe('DL');
    expect(screen.getByText('最高画质')).toBeVisible();
    expect(screen.getByLabelText('下载规格')).toHaveAttribute('readonly');
    expect(screen.getByRole('combobox', { name: '保存格式' })).toBeDisabled();
    expect(screen.queryByRole('tab', { name: '仅音频' })).toBeNull();
    expect(screen.queryByText('推荐')).toBeNull();
  });

  it.each([
    ['content_preview_only', '仅提供试看内容'],
    ['content_supporter_only', '充电专属内容'],
    ['content_paid_only', '付费内容暂不支持下载'],
    ['content_export_required', '尚未提供文件导出授权'],
    ['content_access_metadata_invalid', '内容权益信息无法确认'],
  ])('explains %s without exposing stale formats', (reason, title) => {
    render(
      <InspectionWorkspace
        busy={false}
        inspection={{
          ...inspection,
          access_decision: 'blocked',
          restriction_reason: reason,
          user_action: '请通过官方平台观看。',
        }}
        onChange={vi.fn()}
        onCreate={vi.fn()}
        onUseUpload={vi.fn()}
        selectedId={inspection.formats[0].id}
      />,
    );
    expect(screen.getByRole('heading', { name: title })).toBeVisible();
    expect(screen.getByText('请通过官方平台观看。')).toBeVisible();
    expect(screen.queryByText('1080p MP4')).not.toBeInTheDocument();
    expect(screen.queryByText('当前清晰度')).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
