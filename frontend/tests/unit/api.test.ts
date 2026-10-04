import { describe, expect, it } from 'vitest';
import {
  createProviderCatalogEntry,
  deleteProviderCatalogEntry,
  deleteUser,
  getDownloadAnalytics as getAdminDownloadAnalytics,
  listProviderCatalogEntries,
  listUsers,
  updateProviderCatalogEntry,
  updateUserAccess,
} from '@/api/admin';
import { cancelAnalysis, getAnalysis } from '@/api/analyses';
import {
  getCurrentUser,
  loginUser as login,
  logoutUser as logout,
  registerUser as register,
} from '@/api/auth';
import {
  getDocumentImport as getScreenplayDocument,
  listDocuments as listScreenplayDocuments,
} from '@/api/documents';
import {
  cancelDownload,
  createDownload,
  getDownload,
  getDownloadHistory,
  issueDownloadUrl,
} from '@/api/downloads';
import {
  getInspection,
  inspectMedia as inspectDiscoveredItem,
  inspectMedia,
} from '@/api/inspections';
import { createSourceDiscovery } from '@/api/sourceDiscoveries';
import { getLiveness, getReadiness } from '@/api/system';
import { updateCurrentUser } from '@/api/users';
import { analysisJob } from '../fixtures/analysis-fixtures';
import {
  documentId,
  screenplayDocument,
  screenplayDocumentPage,
} from '../fixtures/document-fixtures';
import {
  inspection,
  job,
  sourceDiscovery,
} from '../fixtures/download-fixtures';
import { httpRequests, mockHttpResponses } from '../helpers/http';

describe('typed API client', () => {
  it('covers email registration, opaque session restore and logout endpoints', async () => {
    const user = {
      id: '11111111-1111-4111-8111-111111111111',
      username: 'video_user',
      email: 'user@example.com',
      role: 'user' as const,
      created_at: '2026-08-09T10:00:00Z',
      updated_at: '2026-08-09T10:00:00Z',
    };
    mockHttpResponses(user, user, user, undefined);

    await register({
      verification_code: '123456',
      username: user.username,
      email: user.email,
      password: 'strong-pass-123',
    });
    await login({ email: user.email, password: 'strong-pass-123' });
    await getCurrentUser();
    await logout();

    expect(httpRequests().map(({ url }) => url)).toEqual([
      '/api/auth/register',
      '/api/auth/login',
      '/api/auth/me',
      '/api/auth/logout',
    ]);
  });

  it('uses same-origin download endpoints and idempotency headers', async () => {
    mockHttpResponses(inspection, job());
    await inspectMedia(
      { source: { kind: 'public_url', url: 'https://media.example/owned' } },
      {
        headers: { 'Idempotency-Key': 'inspect-key' },
        timeout: 180_000,
      },
    );
    await createDownload(
      {
        inspection_id: inspection.id,
        format_id: inspection.formats[0].id,
      },
      {
        headers: { 'Idempotency-Key': 'download-key' },
      },
    );

    expect(httpRequests()).toMatchObject([
      {
        url: '/api/inspections',
        method: 'POST',
        headers: expect.objectContaining({ 'Idempotency-Key': 'inspect-key' }),
        timeout: 180_000,
      },
      {
        url: '/api/downloads',
        method: 'POST',
        headers: expect.objectContaining({ 'Idempotency-Key': 'download-key' }),
      },
    ]);
    expect(httpRequests()[1]?.data).toEqual({
      inspection_id: inspection.id,
      format_id: inspection.formats[0].id,
    });
    expect(httpRequests()[0]?.data).toEqual({
      source: { kind: 'public_url', url: 'https://media.example/owned' },
    });
  });

  it('uses owner-scoped article discovery and item inspection contracts', async () => {
    mockHttpResponses(sourceDiscovery, inspection);

    await createSourceDiscovery(
      {
        kind: 'wechat_official_account_article',
        url: 'https://mp.weixin.qq.com/s/article_123',
      },
      {
        headers: { 'Idempotency-Key': 'discover-key' },
        timeout: 30_000,
      },
    );
    await inspectDiscoveredItem(
      {
        source: {
          kind: 'discovered_item',
          discovery_id: sourceDiscovery.id,
          item_ref: sourceDiscovery.items[0].item_ref,
        },
      },
      {
        headers: { 'Idempotency-Key': 'inspect-item-key' },
        timeout: 30_000,
      },
    );

    expect(httpRequests()).toMatchObject([
      {
        url: '/api/source-discoveries',
        method: 'POST',
        headers: { 'Idempotency-Key': 'discover-key' },
      },
      {
        url: '/api/inspections',
        method: 'POST',
        headers: { 'Idempotency-Key': 'inspect-item-key' },
      },
    ]);
  });

  it('covers inspection, download, cancel, file and health endpoints', async () => {
    mockHttpResponses(
      inspection,
      job('running'),
      job('cancelled'),
      {
        filename: 'Owned video.mp4',
        url: 'https://objects.example/token',
        expires_at: '2026-08-06T10:05:00Z',
      },
      { status: 'ok' },
      { status: 'ok', service: 'api' },
    );
    await getInspection({ inspection_id: encodeURIComponent(inspection.id) });
    await getDownload({ job_id: encodeURIComponent(job().id) });
    await cancelDownload({ job_id: encodeURIComponent(job().id) });
    await issueDownloadUrl(
      {
        job_id: encodeURIComponent(job().id),
        preview: false,
      },
      {
        headers: { 'X-FrameFetch-Download-Client': 'local-web' },
      },
    );
    await getLiveness();
    await getReadiness();

    expect(httpRequests().map(({ url }) => url)).toEqual([
      `/api/inspections/${inspection.id}`,
      `/api/downloads/${job().id}`,
      `/api/downloads/${job().id}/cancel`,
      `/api/downloads/${job().id}/download-url`,
      '/health/live',
      '/health/ready',
    ]);
    expect(httpRequests()[3]).toMatchObject({
      headers: { 'X-FrameFetch-Download-Client': 'local-web' },
    });
  });

  it('forwards typed pagination and filters to the download history endpoint', async () => {
    const history = {
      items: [],
      page: 2,
      page_size: 20,
      summary: { active: 1, failed: 2, succeeded: 10, total: 41 },
      total: 41,
    };
    mockHttpResponses(history);

    await expect(
      getDownloadHistory({
        page: 2,
        page_size: 20,
        search: 'Owned video',
        status: 'succeeded',
      }),
    ).resolves.toEqual(history);
    expect(httpRequests()[0]).toMatchObject({
      method: 'GET',
      params: {
        page: 2,
        page_size: 20,
        search: 'Owned video',
        status: 'succeeded',
      },
      url: '/api/downloads/history',
    });
  });

  it('uses owner-scoped screenplay document list and detail endpoints', async () => {
    mockHttpResponses(screenplayDocumentPage(), screenplayDocument());

    await expect(
      listScreenplayDocuments({ page: 2, page_size: 20 }),
    ).resolves.toEqual(screenplayDocumentPage());
    await expect(
      getScreenplayDocument({ document_id: encodeURIComponent(documentId) }),
    ).resolves.toEqual(screenplayDocument());

    expect(httpRequests()).toMatchObject([
      {
        method: 'GET',
        params: { page: 2, page_size: 20 },
        url: '/api/documents',
      },
      { method: 'GET', url: `/api/documents/${documentId}` },
    ]);
  });

  it('loads administrator download analytics for the selected period', async () => {
    const result = {
      period_days: 30,
      start: '2026-07-12',
      end: '2026-08-10',
      summary: {
        total: 0,
        succeeded: 0,
        failed: 0,
        cancelled: 0,
        active: 0,
        unique_users: 0,
        downloaded_bytes: 0,
        average_duration_seconds: 0,
        success_rate: 0,
      },
      daily: [],
      sources: [],
    };
    mockHttpResponses(result);

    await expect(getAdminDownloadAnalytics({ days: 30 })).resolves.toEqual(
      result,
    );
    expect(httpRequests()[0]).toMatchObject({
      method: 'GET',
      params: { days: 30 },
      url: '/api/admin/downloads/analytics',
    });
  });

  it('reads and cancels historical owner-scoped analyses', async () => {
    mockHttpResponses(analysisJob('running'), analysisJob('cancelled'));
    await getAnalysis({ analysis_id: analysisJob().id });
    await cancelAnalysis({ analysis_id: analysisJob().id });
    expect(httpRequests()).toMatchObject([
      { url: `/api/analyses/${analysisJob().id}`, method: 'GET' },
      { url: `/api/analyses/${analysisJob().id}/cancel`, method: 'POST' },
    ]);
  });

  it('covers profile and administrator user management endpoints', async () => {
    const managedUser = {
      id: '11111111-1111-4111-8111-111111111111',
      username: 'video_user',
      email: 'user@example.com',
      role: 'user' as const,
      is_active: true,
      created_at: '2026-08-09T10:00:00Z',
      updated_at: '2026-08-09T10:00:00Z',
    };
    mockHttpResponses(
      managedUser,
      { items: [managedUser], page: 1, page_size: 20, total: 1 },
      { ...managedUser, role: 'admin' },
      undefined,
    );

    await updateCurrentUser({ username: 'video_user' });
    await listUsers({ page: 1, page_size: 20, role: 'user' });
    await updateUserAccess(
      { user_id: encodeURIComponent(managedUser.id) },
      { role: 'admin' },
    );
    await deleteUser({ user_id: encodeURIComponent(managedUser.id) });

    expect(httpRequests()).toMatchObject([
      {
        url: '/api/users/me',
        method: 'PATCH',
        data: { username: 'video_user' },
      },
      {
        url: '/api/admin/users',
        method: 'GET',
        params: { page: 1, page_size: 20, role: 'user' },
      },
      {
        url: `/api/admin/users/${managedUser.id}`,
        method: 'PATCH',
        data: { role: 'admin' },
      },
      {
        url: `/api/admin/users/${managedUser.id}`,
        method: 'DELETE',
      },
    ]);
  });

  it('covers administrator platform catalog endpoints', async () => {
    const entry = {
      key: 'youtube',
      display_name: 'YouTube',
      sort_order: 10,
      is_visible: true,
      system_registered: true,
      system_status: 'verified' as const,
      created_at: '2026-08-12T10:00:00Z',
      updated_at: '2026-08-12T10:00:00Z',
    };
    mockHttpResponses(
      { items: [entry] },
      entry,
      { ...entry, display_name: 'YouTube Video' },
      undefined,
    );

    await listProviderCatalogEntries();
    await createProviderCatalogEntry({
      key: entry.key,
      display_name: entry.display_name,
      sort_order: entry.sort_order,
      is_visible: entry.is_visible,
    });
    await updateProviderCatalogEntry(
      { provider_key: encodeURIComponent(entry.key) },
      {
        display_name: 'YouTube Video',
      },
    );
    await deleteProviderCatalogEntry({
      provider_key: encodeURIComponent(entry.key),
    });

    expect(httpRequests().slice(-4)).toMatchObject([
      { url: '/api/admin/providers', method: 'GET' },
      {
        url: '/api/admin/providers',
        method: 'POST',
        data: {
          key: 'youtube',
          display_name: 'YouTube',
          sort_order: 10,
          is_visible: true,
        },
      },
      {
        url: '/api/admin/providers/youtube',
        method: 'PATCH',
        data: { display_name: 'YouTube Video' },
      },
      { url: '/api/admin/providers/youtube', method: 'DELETE' },
    ]);
  });
});
