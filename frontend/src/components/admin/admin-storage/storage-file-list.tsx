import { Trash } from '@phosphor-icons/react';
import {
  type BulkDeleteOptions,
  BulkDeleteSelection,
} from '@/components/layout/bulk-delete-selection';
import { DataTable } from '@/components/layout/data-table';
import { Button } from '@/components/ui/button';

import {
  formatStorageDate,
  formatStorageSize,
  storageCategoryLabels,
} from './model';

export function StorageFileList({
  bulk,
  items,
  onDelete,
}: {
  bulk?: BulkDeleteOptions;
  items: API.StoredFileResponse[];
  onDelete: (item: API.StoredFileResponse) => void;
}) {
  return (
    <BulkDeleteSelection
      ids={items.map((item) => `${item.category}:${item.id}`)}
      options={bulk}
    >
      <div className="min-w-0">
        <DataTable<API.StoredFileResponse>
          data={items}
          getRowId={(item) => `${item.category}:${item.id}`}
          getRowLabel={(item) => item.name}
          caption="持久文件列表"
          columns={[
            {
              id: '文件',
              header: '文件',
              hideable: false,
              className: 'whitespace-normal',
              cell: (item) => (
                <div className="flex min-w-0 flex-col gap-1">
                  <span className="line-clamp-2 break-all" title={item.name}>
                    {item.name}
                  </span>
                  <span className="text-xs text-muted-foreground md:hidden">
                    {storageCategoryLabels[item.category]} ·{' '}
                    {formatStorageSize(item.size_bytes)} · {item.object_count}{' '}
                    个对象
                  </span>
                  <time
                    className="text-xs text-muted-foreground md:hidden"
                    dateTime={item.created_at}
                  >
                    {formatStorageDate(item.created_at)}
                  </time>
                </div>
              ),
            },
            {
              id: '类型',
              header: '类型',
              className: 'hidden md:table-cell',
              cell: (item) => <> {storageCategoryLabels[item.category]} </>,
            },
            {
              id: '对象数',
              header: '对象数',
              className: 'hidden text-right tabular-nums md:table-cell',
              cell: (item) => <> {item.object_count} </>,
            },
            {
              id: '创建时间',
              header: '创建时间',
              className: 'hidden tabular-nums md:table-cell',
              cell: (item) => <> {formatStorageDate(item.created_at)} </>,
            },
            {
              id: '大小',
              header: '大小',
              className: 'hidden text-right tabular-nums md:table-cell',
              cell: (item) => <> {formatStorageSize(item.size_bytes)} </>,
            },
            {
              id: '操作',
              header: '操作',
              hideable: false,
              className: 'text-right',
              cell: (item) => (
                <>
                  <Button
                    aria-label={`删除文件 ${item.name}`}
                    onClick={() => onDelete(item)}
                    size="icon"
                    type="button"
                    variant="ghost"
                  >
                    <Trash aria-hidden />
                  </Button>
                </>
              ),
            },
          ]}
        />
      </div>
    </BulkDeleteSelection>
  );
}
