import {
  ArrowClockwise,
  PlugsConnected,
  Plus,
  WarningCircle,
} from '@phosphor-icons/react';
import { useState } from 'react';
import type { BulkDeleteOptions } from '@/components/layout/bulk-delete-selection';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import {
  DEFAULT_PAGE_SIZE,
  PagePagination,
} from '@/components/layout/page-pagination';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ItemDescription, ItemTitle } from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';

import { ExecutionRoute, ProviderTable } from './ai-provider-list';

type Props = {
  bulk?: BulkDeleteOptions;
  agentAvailable: boolean;
  error: string;
  items: API.AiProviderProfileResponse[];
  loading: boolean;
  onActivate: (item: API.AiProviderProfileResponse) => void;
  onCreate: () => void;
  onDelete: (item: API.AiProviderProfileResponse) => void;
  onEdit: (item: API.AiProviderProfileResponse) => void;
  onRetry: () => void;
};

export function AiProviderScreen({
  bulk,
  agentAvailable,
  error,
  items,
  loading,
  onActivate,
  onCreate,
  onDelete,
  onEdit,
  onRetry,
}: Props) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const currentPage = Math.min(
    page,
    Math.max(1, Math.ceil(items.length / pageSize)),
  );
  const visible = items.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );
  const active = items.find((item) => item.is_active);
  return (
    <div aria-busy={loading} className="flex flex-col gap-8">
      <div>
        <PageNavigation fallbackHref="/" />
        <PageHeader
          action={
            <Button onClick={onCreate}>
              <Plus aria-hidden data-icon="inline-start" />
              新增 AI 服务
            </Button>
          }
          description="默认使用服务端本机 Codex；可在这里新增并启用第三方 API。切换后从下一次分析任务生效，无需修改环境文件。"
          title="AI 服务"
        />
      </div>

      {error ? (
        items.length === 0 ? (
          <PageErrorNotice
            message={error}
            onRetry={onRetry}
            retryLabel="重新加载"
            title="暂时无法读取 AI 服务"
          />
        ) : (
          <FeedbackNotice
            action={
              <Button onClick={onRetry} size="default" variant="outline">
                <ArrowClockwise aria-hidden data-icon="inline-start" />
                重新加载
              </Button>
            }
            description={error}
            title="操作未完成"
            tone="error"
          />
        )
      ) : null}

      <div>
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <ItemDescription className="line-clamp-none">
              当前执行链路
            </ItemDescription>
            <ItemTitle className="line-clamp-none">
              <h2 className="mt-1" id="active-ai-route">
                Agent 与模型连接状态
              </h2>
            </ItemTitle>
          </div>
          <Badge variant={agentAvailable ? 'default' : 'destructive'}>
            {agentAvailable ? 'Agent 在线' : 'Agent 离线'}
          </Badge>
        </div>
        <div>
          {loading && !active ? (
            <Skeleton className="h-20 w-full" />
          ) : active ? (
            <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <ItemTitle className="line-clamp-none">
                    <h3>{active.display_name}</h3>
                  </ItemTitle>
                  <Badge variant="default">已启用</Badge>
                  <Badge variant="secondary">
                    {active.auth_mode === 'host_login'
                      ? '免 Key'
                      : 'Key 已加密'}
                  </Badge>
                </div>
                <ExecutionRoute active={active} />
              </div>
              <div className="lg:text-right">
                <ItemDescription className="line-clamp-none">
                  模型
                </ItemDescription>
                <ItemDescription className="line-clamp-none mt-1">
                  {active.model}
                </ItemDescription>
              </div>
            </div>
          ) : (
            <ItemDescription className="line-clamp-none">
              尚未启用 Provider。新增配置后将其设为当前线路。
            </ItemDescription>
          )}
        </div>
        {!agentAvailable ? (
          <Alert className="mt-3">
            <WarningCircle aria-hidden />
            <AlertTitle>分析 Agent 暂时离线</AlertTitle>
            <AlertDescription>
              配置仍然有效，新的分析任务会先进入可靠队列，待 Agent
              恢复后继续处理。请检查宿主机分析 Worker、Codex
              登录、数据库与消息队列。
            </AlertDescription>
          </Alert>
        ) : null}
      </div>

      <div>
        <div className="mb-5 flex items-center justify-between gap-4">
          <ItemTitle className="line-clamp-none">
            <h2 id="ai-provider-list">Provider 配置</h2>
          </ItemTitle>
        </div>
        <div className="flex flex-col gap-1">
          {loading && items.length === 0 ? (
            ['one', 'two', 'three'].map((key) => (
              <div key={key}>
                <Skeleton className="h-14 w-full" />
              </div>
            ))
          ) : items.length > 0 ? (
            <ProviderTable
              bulk={
                bulk
                  ? {
                      ...bulk,
                      scope: JSON.stringify([
                        bulk.scope,
                        currentPage,
                        pageSize,
                      ]),
                    }
                  : undefined
              }
              items={visible}
              onActivate={onActivate}
              onDelete={onDelete}
              onEdit={onEdit}
            />
          ) : error ? null : (
            <PageEmptyNotice
              action={
                <Button onClick={onCreate} type="button">
                  <Plus aria-hidden data-icon="inline-start" />
                  新增第一个 AI 服务
                </Button>
              }
              compact
              description="新增并启用一个 AI Provider 后，分析任务会从这里选择执行线路。"
              icon={<PlugsConnected aria-hidden />}
              title="还没有 AI 服务配置"
            />
          )}
        </div>
        {items.length > 0 ? (
          <PagePagination
            ariaLabel="AI 配置分页"
            page={currentPage}
            pageSize={pageSize}
            pages={Math.ceil(items.length / pageSize)}
            busy={loading}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        ) : null}
      </div>
    </div>
  );
}
