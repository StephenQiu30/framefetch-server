import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CreationOptions } from '@/components/creation/creation-options';
import { render } from '../helpers/query-render';

describe('creation processing mode after changing capability', () => {
  it('shows the format default on the first switch from article writing to editing', async () => {
    const change = vi.fn();
    const view = render(
      <CreationOptions
        skillId="article-write"
        value={{}}
        disabled={false}
        onChange={change}
      />,
    );
    expect(
      screen.getByRole('combobox', { name: '处理方式' }),
    ).toHaveTextContent('形成正文候选');
    view.rerender(
      <CreationOptions
        skillId="article-edit"
        value={{}}
        disabled={false}
        onChange={change}
      />,
    );
    expect(
      screen.getByRole('combobox', { name: '处理方式' }),
    ).toHaveTextContent('只整理格式，保留正文语义');
    fireEvent.click(screen.getByRole('combobox', { name: '处理方式' }));
    expect(
      await screen.findByRole('option', {
        name: '只整理格式，保留正文语义',
      }),
    ).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByRole('option', { name: '润色或结构重组' }));
    expect(change).toHaveBeenCalledWith({ mode: 'rewrite' });
  });
});
