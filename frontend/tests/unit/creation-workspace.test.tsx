import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CreationWorkspace from '@/components/creation/creation-workspace';
import { httpClient } from '@/lib/request';
import { ApiError } from '@/lib/request-error';
import {
  creationMaterial,
  creationSkill,
  creationTask,
} from '../helpers/creation-fixtures';
import { httpRequests } from '../helpers/http';
import { render } from '../helpers/query-render';

describe('creation workspace submission journey', () => {
  it('uses confirmed selected revisions and retains one request intent after an uncertain creation response', async () => {
    let attempts = 0;
    const queued = {
      ...creationTask,
      status: 'queued' as const,
      revision: null,
    };
    vi.mocked(httpClient.request).mockImplementation(async (config) => {
      let data: unknown;
      if (config.url === '/api/creation/skills') data = [creationSkill];
      else if (config.url === '/api/creation/projects')
        data = [
          {
            id: 'project-1',
            title: '原创内容',
            description: '',
            created_at: '2026-10-04T08:00:00Z',
            updated_at: '2026-10-04T08:00:00Z',
          },
        ];
      else if (config.url === '/api/creation/materials')
        data = [creationMaterial];
      else if (
        config.url === '/api/creation/tasks' &&
        config.method === 'POST'
      ) {
        attempts += 1;
        if (attempts === 1)
          throw new ApiError(
            0,
            'request_failed',
            '网络结果不明',
            '创建结果尚未确认，请核对后再重试。',
          );
        data = queued;
      } else if (config.url === '/api/creation/tasks')
        data = attempts >= 2 ? [queued] : [];
      else if (config.url === '/api/creation/tasks/task-1') data = queued;
      else throw new Error(`Unexpected request: ${config.url}`);
      return { data: { code: 'ok', message: 'OK', data } } as never;
    });
    render(<CreationWorkspace />);
    fireEvent.click(await screen.findByRole('checkbox', { name: '原创材料' }));
    fireEvent.mouseDown(screen.getByRole('tab', { name: '新建任务' }), {
      button: 0,
      ctrlKey: false,
    });
    expect(screen.getByRole('button', { name: '开始所选任务' })).toBeDisabled();
    fireEvent.click(
      screen.getByRole('checkbox', { name: /我已确认任务、材料/ }),
    );
    fireEvent.click(screen.getByRole('button', { name: '开始所选任务' }));
    await screen.findByText('操作未完成');
    fireEvent.click(screen.getByRole('button', { name: '开始所选任务' }));
    await waitFor(() => expect(attempts).toBe(2));
    const submissions = httpRequests().filter(
      (request) =>
        request.url === '/api/creation/tasks' && request.method === 'POST',
    );
    expect(submissions[0].headers?.['Idempotency-Key']).toEqual(
      submissions[1].headers?.['Idempotency-Key'],
    );
    expect(submissions[0].data).toMatchObject({
      material_revision_ids: ['material-revision-1'],
      skill_id: 'article-edit',
      options: { mode: 'format' },
    });
    expect(await screen.findByText('等待处理')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '任务与版本' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });
});
