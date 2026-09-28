'use client';

import { useQuery } from '@tanstack/react-query';
import { getAdminProviderRuntime } from '@/api/admin';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { privateQueryKey } from '@/lib/query-keys';

const labels: Record<API.ProviderRuntimeResponse['session_state'], string> = {
  not_configured: '未配置',
  seeded: '等待首次验证',
  verifying: '正在验证',
  ready: '登录状态已验证',
  degraded: '等待自动恢复',
  reseed_required: '需要重新登录',
  revoked: '已撤销',
};

function time(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—';
}

export function SiteSessionStatus() {
  const query = useQuery({
    queryKey: privateQueryKey('admin-site-sessions'),
    queryFn: ({ signal }) => getAdminProviderRuntime({ signal }),
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });
  return (
    <section aria-labelledby="site-session-heading" className="mt-10 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 id="site-session-heading">平台会话</h2>
        <Button
          variant="outline"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          刷新会话状态
        </Button>
      </div>
      <p>
        解析使用部署者配置的登录状态。系统自动检查与维护会话；平台要求重新登录时，需要部署者完成登录并重新导入。
      </p>
      {query.isPending ? <p role="status">正在读取会话状态…</p> : null}
      {query.isError ? (
        <PageErrorNotice
          title="会话状态暂时不可用"
          message="无法读取最新状态，请重试。"
          onRetry={() => void query.refetch()}
        />
      ) : null}
      {query.data ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>站点</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>最近验证</TableHead>
              <TableHead>下次检查</TableHead>
              <TableHead>恢复操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data.items
              .filter((item) => item.session_site)
              .map((item) => (
                <TableRow key={item.provider_key}>
                  <TableCell>{item.session_site}</TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {item.session_state === 'ready' && !item.context_available
                        ? '等待运行环境验证'
                        : labels[item.session_state]}
                    </Badge>
                  </TableCell>
                  <TableCell>{time(item.session_verified_at)}</TableCell>
                  <TableCell>{time(item.session_next_check_at)}</TableCell>
                  <TableCell>
                    {['not_configured', 'reseed_required', 'revoked'].includes(
                      item.session_state,
                    )
                      ? '在部署主机登录该站点，然后运行站点会话导入命令。'
                      : item.session_state === 'degraded'
                        ? '系统将自动重试；持续失败时检查平台验证要求与网络出口。'
                        : '自动维护中'}
                  </TableCell>
                </TableRow>
              ))}
          </TableBody>
        </Table>
      ) : null}
    </section>
  );
}
