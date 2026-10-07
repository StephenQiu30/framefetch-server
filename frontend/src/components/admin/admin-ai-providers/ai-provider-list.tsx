import {
  ArrowRight,
  Cloud,
  Key,
  PencilSimple,
  Robot,
  TerminalWindow,
  Trash,
} from '@phosphor-icons/react';
import {
  type BulkDeleteOptions,
  BulkDeleteSelection,
} from '@/components/layout/bulk-delete-selection';
import { type DataColumn, DataTable } from '@/components/layout/data-table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from '@/components/ui/item';
import {
  isDirectApiEngine,
  isLocalCodexProvider,
  providerEngineLabel,
} from './model';

export function ExecutionRoute({
  active,
}: {
  active: API.AiProviderProfileResponse;
}) {
  return (
    <div className="mt-5 flex flex-wrap items-center gap-2">
      <RouteNode icon={<Robot />} label="本机 Agent" />
      <ArrowRight aria-hidden />
      <RouteNode
        icon={<TerminalWindow />}
        label={
          isDirectApiEngine(active.engine)
            ? providerEngineLabel(active.engine)
            : `${providerEngineLabel(active.engine)} CLI`
        }
      />
      <ArrowRight aria-hidden />
      <RouteNode
        icon={active.auth_mode === 'api_key' ? <Cloud /> : <Key />}
        label={
          active.auth_mode === 'api_key'
            ? active.base_url || 'API 服务'
            : '当前用户登录'
        }
      />
    </div>
  );
}

function ProviderRowColumns(
  onActivate: (item: API.AiProviderProfileResponse) => void,
  onDelete: (item: API.AiProviderProfileResponse) => void,
  onEdit: (item: API.AiProviderProfileResponse) => void,
): DataColumn<API.AiProviderProfileResponse>[] {
  return [
    {
      id: '服务',
      header: '服务',
      hideable: false,
      className: 'w-full whitespace-normal [overflow-wrap:anywhere] lg:w-1/3',
      cell: (item) => {
        const localCodex = isLocalCodexProvider(item.key);
        return (
          <div className="flex min-w-0 flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <ItemTitle className="line-clamp-none">
                <h3>{item.display_name}</h3>
              </ItemTitle>
              {item.is_active ? (
                <Badge variant="default">当前线路</Badge>
              ) : null}
              {localCodex ? <Badge variant="secondary">系统兜底</Badge> : null}
            </div>
            <ItemDescription className="line-clamp-none break-all">
              {item.key}
            </ItemDescription>
            <ItemDescription className="line-clamp-none break-all lg:hidden">
              {providerEngineLabel(item.engine)} · {item.model} ·{' '}
              {connectionLabel(item)}
            </ItemDescription>
          </div>
        );
      },
    },
    {
      id: '模型与连接',
      header: '模型与连接',
      className:
        'hidden whitespace-normal [overflow-wrap:anywhere] lg:table-cell lg:w-1/3',
      cell: (item) => {
        return (
          <div className="flex min-w-0 flex-col gap-1">
            <span className="break-all">{item.model}</span>
            <span className="break-all">{connectionLabel(item)}</span>
          </div>
        );
      },
    },
    {
      id: '执行引擎',
      header: '执行引擎',
      className: 'hidden whitespace-nowrap lg:table-cell',
      cell: (item) => {
        return (
          <Badge variant="secondary">{providerEngineLabel(item.engine)}</Badge>
        );
      },
    },
    {
      id: '操作',
      header: '操作',
      hideable: false,
      className: 'text-right whitespace-nowrap',
      cell: (item) => {
        const localCodex = isLocalCodexProvider(item.key);
        return (
          <div className="flex flex-wrap items-center justify-end gap-2">
            {!item.is_active ? (
              <Button
                onClick={() => onActivate(item)}
                size="default"
                variant="outline"
              >
                启用
              </Button>
            ) : null}
            <Button
              aria-label={`编辑 ${item.display_name}`}
              onClick={() => onEdit(item)}
              size="icon"
              variant="ghost"
            >
              <PencilSimple aria-hidden />
            </Button>
            <Button
              aria-label={`删除 ${item.display_name}`}
              disabled={item.is_active || localCodex}
              onClick={() => onDelete(item)}
              size="icon"
              title={localCodex ? '系统兜底线路不可删除' : undefined}
              variant="ghost"
            >
              <Trash aria-hidden />
            </Button>
          </div>
        );
      },
    },
  ];
}

function connectionLabel(item: API.AiProviderProfileResponse) {
  return item.auth_mode === 'host_login'
    ? '本机账号登录'
    : `${item.base_url || '未配置地址'} · ${item.credential_configured ? '凭据已配置' : '缺少凭据'}`;
}

export function ProviderTable({
  bulk,
  items,
  onActivate,
  onDelete,
  onEdit,
}: {
  bulk?: BulkDeleteOptions;
  items: API.AiProviderProfileResponse[];
  onActivate: (item: API.AiProviderProfileResponse) => void;
  onDelete: (item: API.AiProviderProfileResponse) => void;
  onEdit: (item: API.AiProviderProfileResponse) => void;
}) {
  return (
    <BulkDeleteSelection
      ids={items
        .filter((item) => !item.is_active && !isLocalCodexProvider(item.key))
        .map((item) => item.key)}
      options={bulk}
    >
      <DataTable<API.AiProviderProfileResponse>
        data={items}
        getRowId={(item) => item.key}
        getRowLabel={(item) => item.display_name}
        caption="AI Provider 配置列表"
        columns={ProviderRowColumns(onActivate, onDelete, onEdit)}
      />
    </BulkDeleteSelection>
  );
}

function RouteNode({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <Item className="min-w-0 w-auto flex-nowrap" size="xs" variant="muted">
      <ItemMedia aria-hidden variant="icon">
        {icon}
      </ItemMedia>
      <ItemContent className="min-w-0">
        <ItemTitle className="break-all">{label}</ItemTitle>
      </ItemContent>
    </Item>
  );
}
