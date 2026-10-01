import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DownloadWorkspace from '@/components/intake/download-workspace';
import { PUBLIC_INPUT_REQUIRED } from '@/components/intake/public-input';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import {
  inspection,
  reportedDouyinShareMessage,
  sourceDiscovery,
} from '../fixtures/download-fixtures';
import { intentFixture } from '../fixtures/intent-fixtures';
import { httpRequests, mockHttpResponses } from '../helpers/http';
import { render } from '../helpers/query-render';

const push = vi.fn();
vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({ user: { id: 'intent-test-owner', role: 'user' } }),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
vi.mock('@/components/providers/use-provider-statuses', () => ({
  useProviderStatuses: () => ({
    data: { items: [] },
    error: null,
    loading: false,
    retry: vi.fn(),
  }),
}));

function renderWorkspace() {
  return render(
    <TooltipProvider>
      <DownloadWorkspace />
      <Toaster position="bottom-right" />
    </TooltipProvider>,
  );
}
function submit(input: string) {
  fireEvent.change(screen.getByLabelText('公开视频地址'), {
    target: { value: input },
  });
  fireEvent.click(screen.getByRole('button', { name: '解析媒体' }));
}

describe('home parsing route', () => {
  beforeEach(() => {
    push.mockReset();
    window.history.replaceState({}, '', '/');
  });

  it('keeps the empty homepage focused on intake', () => {
    renderWorkspace();
    expect(screen.getByLabelText('公开视频地址')).toBeVisible();
    expect(screen.getByRole('tab', { name: '本地视频' })).toBeEnabled();
    expect(document.querySelector('[data-slot="media-result"]')).toBeNull();
    expect(
      document.querySelector('[data-slot="inspection-result"]'),
    ).toBeNull();
  });

  it('rejects blank input locally', () => {
    renderWorkspace();
    fireEvent.click(screen.getByRole('button', { name: '解析媒体' }));
    expect(screen.getByText(PUBLIC_INPUT_REQUIRED)).toBeVisible();
    expect(httpRequests()).toHaveLength(0);
  });

  it('passes the complete share message and opens the result route without showing the result on home', async () => {
    mockHttpResponses(intentFixture(), inspection);
    renderWorkspace();
    submit(reportedDouyinShareMessage);
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(
        `/downloads/new?inspectionId=${inspection.id}&intentId=${intentFixture().id}`,
      ),
    );
    expect(httpRequests()[0].data).toEqual({
      input: reportedDouyinShareMessage,
    });
    expect(document.querySelector('[data-slot="media-result"]')).toBeNull();
    expect(screen.queryByText(inspection.title)).not.toBeInTheDocument();
  });

  it('opens article discovery on its own page', async () => {
    mockHttpResponses(sourceDiscovery);
    renderWorkspace();
    submit('https://mp.weixin.qq.com/s/example');
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(
        `/downloads/new?discoveryId=${sourceDiscovery.id}`,
      ),
    );
    expect(
      document.querySelector('[data-slot="source-discovery-result"]'),
    ).toBeNull();
  });

  it('does not resurrect an old failed record as a homepage parse notification', async () => {
    const failed = intentFixture({
      status: 'failed',
      reason_code: 'login_required',
      inspection_id: null,
    });
    sessionStorage.setItem(
      'framefetch-active-intent',
      JSON.stringify({ owner: 'intent-test-owner', id: failed.id }),
    );
    mockHttpResponses(failed);
    renderWorkspace();
    await waitFor(() => expect(httpRequests()).toHaveLength(1));
    expect(screen.queryByText('本次解析未完成')).not.toBeInTheDocument();
    expect(screen.getByLabelText('公开视频地址')).toBeVisible();
  });
});
