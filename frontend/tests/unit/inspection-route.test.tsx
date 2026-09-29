import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import InspectionRoute from '@/components/intake/inspection-route';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ApiError } from '@/lib/request-error';
import {
  galleryInspection,
  inspection,
  job,
  sourceDiscovery,
  videoCollectionInspection,
} from '../fixtures/download-fixtures';
import { intentFixture } from '../fixtures/intent-fixtures';
import {
  httpRequests,
  mockHttpError,
  mockHttpResponses,
} from '../helpers/http';
import { render } from '../helpers/query-render';

const push = vi.fn();
const replace = vi.fn();
vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({ user: { id: 'intent-test-owner' } }),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
function renderRoute(query: string) {
  window.history.replaceState({}, '', `/downloads/new?${query}`);
  return render(
    <TooltipProvider>
      <InspectionRoute />
    </TooltipProvider>,
  );
}

describe('inspection result route', () => {
  beforeEach(() => {
    push.mockReset();
    replace.mockReset();
  });

  it('keeps the reusable fixed frame and opens the download detail after creating a job', async () => {
    mockHttpResponses(inspection, job());
    renderRoute(`inspectionId=${inspection.id}`);
    expect(await screen.findByText(inspection.title)).toBeVisible();
    expect(
      document.querySelector('[data-slot="media-result-frame"]'),
    ).toBeInTheDocument();
    const cards = document.querySelectorAll(
      '[data-slot="media-result"] > [data-slot="card"]',
    );
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveClass('ring-0');
    expect(cards[1]).toHaveClass('ring-0');
    expect(
      cards[0].querySelector('[data-slot="card-header"]'),
    ).toContainElement(
      screen.getByRole('heading', { name: inspection.title, level: 2 }),
    );
    expect(
      cards[1].querySelector('[data-slot="card-footer"]'),
    ).toContainElement(screen.getByRole('button', { name: '创建下载任务' }));
    expect(screen.getByRole('button', { name: '创建下载任务' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: '创建下载任务' }));
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(`/downloads/detail?jobId=${job().id}`),
    );
    expect(httpRequests().map((request) => request.url)).toEqual([
      `/api/inspections/${inspection.id}`,
      '/api/downloads',
    ]);
  });

  it('keeps blocked media on the result page without a download action', async () => {
    mockHttpResponses({
      ...inspection,
      access_decision: 'blocked',
      formats: [],
    });
    renderRoute(`inspectionId=${inspection.id}`);
    expect(await screen.findByText('当前不可下载')).toBeVisible();
    expect(
      screen.queryByRole('button', { name: '创建下载任务' }),
    ).not.toBeInTheDocument();
  });

  it('keeps image and video collections available as ZIP results on their own page', async () => {
    mockHttpResponses(galleryInspection);
    const first = renderRoute(`inspectionId=${galleryInspection.id}`);
    expect(
      await screen.findByRole('heading', {
        name: galleryInspection.title,
        level: 2,
      }),
    ).toBeVisible();
    expect(screen.getAllByText(/3 张原图/u).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '创建下载任务' })).toBeEnabled();
    first.unmount();

    mockHttpResponses(videoCollectionInspection);
    renderRoute(`inspectionId=${videoCollectionInspection.id}`);
    expect(
      await screen.findByRole('heading', {
        name: videoCollectionInspection.title,
        level: 2,
      }),
    ).toBeVisible();
    expect(screen.getAllByText(/2 个视频/u).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '创建下载任务' })).toBeEnabled();
  });

  it('routes a source requiring an owned file back to the upload intake', async () => {
    mockHttpResponses({
      ...inspection,
      access_decision: 'export_required',
      formats: [],
      user_action: '请上传自有文件。',
    });
    renderRoute(`inspectionId=${inspection.id}`);
    fireEvent.click(
      await screen.findByRole('button', { name: '上传自有 MP4' }),
    );
    expect(push).toHaveBeenCalledWith('/');
    expect(
      screen.queryByRole('button', { name: '创建下载任务' }),
    ).not.toBeInTheDocument();
  });

  it('keeps discovery selection on the result page and replaces it with the selected inspection', async () => {
    mockHttpResponses(sourceDiscovery, inspection);
    renderRoute(`discoveryId=${sourceDiscovery.id}`);
    expect(await screen.findByText(sourceDiscovery.title)).toBeVisible();
    fireEvent.click(screen.getAllByRole('button', { name: '选择并查看' })[0]);
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        `/downloads/new?inspectionId=${inspection.id}`,
      ),
    );
    expect(httpRequests()[1].data).toMatchObject({
      source: {
        kind: 'discovered_item',
        discovery_id: sourceDiscovery.id,
        item_ref: sourceDiscovery.items[0].item_ref,
      },
    });
  });

  it('refreshes an expired result through its original intent and returns to home parsing status', async () => {
    mockHttpError(new ApiError(410, 'resource_expired', 'expired', '已过期。'));
    mockHttpResponses(
      intentFixture({ status: 'queued', inspection_id: null, version: 3 }),
    );
    renderRoute(`inspectionId=${inspection.id}&intentId=${intentFixture().id}`);
    fireEvent.click(await screen.findByRole('button', { name: '更新结果' }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/'));
    expect(sessionStorage.getItem('framefetch-active-intent')).toBe(
      JSON.stringify({ owner: 'intent-test-owner', id: intentFixture().id }),
    );
    expect(httpRequests().map((request) => request.url)).toEqual([
      `/api/inspections/${inspection.id}`,
      `/api/download-intents/${intentFixture().id}/refresh`,
    ]);
    sessionStorage.removeItem('framefetch-active-intent');
  });
});
