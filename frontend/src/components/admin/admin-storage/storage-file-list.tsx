import { Trash } from '@phosphor-icons/react';
import {
  type BulkDeleteOptions,
  BulkDeleteSelection,
} from '@/components/layout/bulk-delete-selection';
import { DataTable } from '@/components/layout/data-table';
import { TableDateTime } from '@/components/layout/table-date-time';
import { Button } from '@/components/ui/button';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from '@/components/ui/item';

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
              className:
                'w-full whitespace-normal [overflow-wrap:anywhere] lg:w-2/5',
              cell: (item) => (
                <ItemGroup>
                  <Item size="xs">
                    <ItemContent className="min-w-0">
                      <ItemTitle
                        className="w-full line-clamp-2 [overflow-wrap:anywhere]"
                        title={item.name}
                      >
                        {item.name}
                      </ItemTitle>
                      <ItemDescription className="[overflow-wrap:anywhere] lg:hidden">
                        上传人：{item.uploader_username ?? '未知上传人'}
                      </ItemDescription>
                      <ItemDescription className="lg:hidden">
                        {storageCategoryLabels[item.category]} ·{' '}
                        {formatStorageSize(item.size_bytes)} ·{' '}
                        {item.object_count} 个对象
                      </ItemDescription>
                      <ItemDescription className="lg:hidden">
                        <time dateTime={item.created_at}>
                          {formatStorageDate(item.created_at)}
                        </time>
                      </ItemDescription>
                    </ItemContent>
                  </Item>
                </ItemGroup>
              ),
            },
            {
              id: '上传人',
              header: '上传人',
              className:
                'hidden whitespace-normal [overflow-wrap:anywhere] lg:table-cell lg:w-1/6',
              cell: (item) => item.uploader_username ?? '未知上传人',
            },
            {
              id: '类型',
              header: '类型',
              className: 'hidden whitespace-nowrap lg:table-cell',
              cell: (item) => <> {storageCategoryLabels[item.category]} </>,
            },
            {
              id: '对象数',
              header: '对象数',
              className:
                'hidden text-right whitespace-nowrap tabular-nums lg:table-cell',
              cell: (item) => <> {item.object_count} </>,
            },
            {
              id: '创建时间',
              header: '创建时间',
              className: 'hidden whitespace-nowrap tabular-nums lg:table-cell',
              cell: (item) => <TableDateTime value={item.created_at} />,
            },
            {
              id: '大小',
              header: '大小',
              className:
                'hidden text-right whitespace-nowrap tabular-nums lg:table-cell',
              cell: (item) => <> {formatStorageSize(item.size_bytes)} </>,
            },
            {
              id: '操作',
              header: '操作',
              hideable: false,
              className: 'text-right whitespace-nowrap',
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
