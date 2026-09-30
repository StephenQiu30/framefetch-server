import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { HistorySearchForm } from '@/components/intake/history-search-form';

function renderForm() {
  const onApply = vi.fn();
  render(
    <HistorySearchForm
      query="测试"
      from="2026-09-20"
      to="2026-09-23"
      hasFilters
      onApply={onApply}
      onReset={vi.fn()}
    />,
  );
  return onApply;
}

describe('history date filters', () => {
  it('keeps dates as drafts until submit and clears an end before the new start', () => {
    const onApply = renderForm();
    fireEvent.click(
      screen.getByRole('button', { name: '开始日期：2026年9月20日' }),
    );
    fireEvent.click(
      screen.getByRole('button', { name: /2026年9月24日 星期四$/ }),
    );
    expect(onApply).not.toHaveBeenCalled();
    expect(
      screen.getByRole('button', { name: '结束日期：选择日期' }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));
    expect(onApply).toHaveBeenCalledWith({
      q: '测试',
      from: '2026-09-24',
      to: '',
    });
  });

  it('clears unsaved title and date drafts even when the URL date filters stay empty', () => {
    const onApply = renderForm();
    fireEvent.change(screen.getByRole('textbox', { name: '内容标题' }), {
      target: { value: '未提交的搜索' },
    });
    fireEvent.click(screen.getByRole('button', { name: '清除筛选' }));
    expect(screen.getByRole('textbox', { name: '内容标题' })).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));
    expect(onApply).toHaveBeenCalledWith({ q: '', from: '', to: '' });
  });

  it('prevents an end date before the draft start and permits clearing dates', () => {
    const onApply = renderForm();
    fireEvent.click(
      screen.getByRole('button', { name: '结束日期：2026年9月23日' }),
    );
    const dialog = screen.getByRole('dialog', { name: '结束日期' });
    expect(
      within(dialog).getByRole('button', { name: '2026年9月19日 星期六' }),
    ).toBeDisabled();
    fireEvent.click(within(dialog).getByRole('button', { name: '清除日期' }));
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));
    expect(onApply).toHaveBeenCalledWith({
      q: '测试',
      from: '2026-09-20',
      to: '',
    });
  });
});
