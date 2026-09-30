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

const labels: Record<API.ProviderRuntimeResponse['login_state'], string> = {
  not_required: '无需登录态',
  signed_in: '登录态来源可读',
  unavailable: '暂时无法读取',
};

export function SiteSessionStatus() {
  const query = useQuery({
    queryKey: privateQueryKey('admin-site-sessions'),
    queryFn: ({ signal }) => getAdminProviderRuntime({ signal }),
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });
  return (
    <section
      aria-labelledby="site-session-heading"
      className="mt-10 flex flex-col gap-4"
    >
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
        需要登录的平台按需读取部署主机 Chrome
        的登录态。来源可读不代表平台接受会话，
        下载是否成功以实际文件为准；重新登录后请稍候再刷新。
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
              <TableHead className="whitespace-normal">站点</TableHead>
              <TableHead className="whitespace-normal">状态</TableHead>
              <TableHead className="whitespace-normal">恢复操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data.items
              .filter((item) => item.session_site)
              .map((item) => (
                <TableRow key={item.provider_key}>
                  <TableCell className="whitespace-normal [overflow-wrap:anywhere]">
                    {item.session_site}
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    <Badge variant="outline">{labels[item.login_state]}</Badge>
                  </TableCell>
                  <TableCell className="whitespace-normal [overflow-wrap:anywhere]">
                    {item.login_state === 'unavailable'
                      ? '检查本机 Chrome 登录、读取权限和登录态服务是否运行。'
                      : item.login_state === 'signed_in'
                        ? '可发起解析；若平台拒绝会话，请按实际错误重新登录或完成验证。'
                        : '公开路线不需要账号登录态。'}
                  </TableCell>
                </TableRow>
              ))}
          </TableBody>
        </Table>
      ) : null}
    </section>
  );
}
