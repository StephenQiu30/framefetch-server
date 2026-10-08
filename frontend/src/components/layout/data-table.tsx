'use client';

import { SlidersHorizontal } from '@phosphor-icons/react';
import {
  type CellContext,
  type ColumnDef,
  columnVisibilityFeature,
  type RowData,
  rowSelectionFeature,
  tableFeatures,
  useTable,
} from '@tanstack/react-table';
import { cn } from 'cn';
import type { ReactNode } from 'react';
import { useBulkTableSelection } from '@/components/layout/bulk-delete-selection';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

const features = tableFeatures({
  columnVisibilityFeature,
  rowSelectionFeature,
});

export type DataColumn<T> = {
  id: string;
  header: string;
  cell: (item: T) => ReactNode;
  className?: string;
  hideable?: boolean;
};
export type TableSelection = {
  ids: string[];
  busy: boolean;
  toggle: (id: string, checked: boolean) => void;
  eligible?: (id: string) => boolean;
};

/** shadcn Data Table composition. The server owns ordering, filtering and pagination. */
export function DataTable<T extends RowData>({
  data,
  columns,
  caption,
  getRowId,
  getRowLabel,
  selection: suppliedSelection,
  className,
  toolbar,
}: {
  data: T[];
  columns: DataColumn<T>[];
  caption: string;
  getRowId: (item: T) => string;
  getRowLabel?: (item: T) => string;
  selection?: TableSelection;
  className?: string;
  toolbar?: ReactNode;
}) {
  const bulkSelection = useBulkTableSelection();
  const selection = suppliedSelection ?? bulkSelection;
  const table = useTable<typeof features, T>({
    features,
    data,
    getRowId,
    columns: columns.map(
      (column, index): ColumnDef<typeof features, T> => ({
        id: column.id,
        header: column.header,
        cell: renderDataCell,
        meta: { render: column.cell },
        enableHiding: index > 0 && column.hideable !== false,
      }),
    ),
    state: {
      rowSelection: Object.fromEntries(
        (selection?.ids ?? []).map((id) => [id, true as const]),
      ),
    },
    enableRowSelection: (row) =>
      !!selection && !selection.busy && (selection.eligible?.(row.id) ?? true),
    onRowSelectionChange: (updater) => {
      if (!selection || selection.busy) return;
      const previous = Object.fromEntries(
        selection.ids.map((id) => [id, true as const]),
      );
      const next = typeof updater === 'function' ? updater(previous) : updater;
      for (const item of data) {
        const id = getRowId(item);
        if ((selection.eligible?.(id) ?? true) && !!previous[id] !== !!next[id])
          selection.toggle(id, !!next[id]);
      }
    },
  });
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {/* Bulk actions take a row only while they have content. */}
      <div
        className="flex flex-wrap items-center gap-3 empty:hidden"
        data-slot="table-toolbar"
      >
        {toolbar ?? bulkSelection?.toolbar}
      </div>
      <div className="min-w-0">
        <Table className={cn('table-borderless', className)}>
          <TableCaption className="sr-only">{caption}</TableCaption>
          <TableHeader>
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id}>
                {selection ? (
                  <TableHead className="w-min">
                    <Checkbox
                      aria-label="选择本页可操作记录"
                      checked={
                        table.getIsAllRowsSelected() ||
                        (table.getIsSomeRowsSelected() && 'indeterminate')
                      }
                      disabled={
                        selection.busy ||
                        !table
                          .getRowModel()
                          .rows.some((row) => row.getCanSelect())
                      }
                      onCheckedChange={(value) =>
                        table.toggleAllRowsSelected(value === true)
                      }
                    />
                  </TableHead>
                ) : null}
                {group.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    className={cn(
                      'whitespace-nowrap',
                      columns.find((column) => column.id === header.column.id)
                        ?.className,
                    )}
                  >
                    {header.isPlaceholder ? null : (
                      <table.FlexRender header={header} />
                    )}
                  </TableHead>
                ))}
                <TableHead className="hidden w-min text-right sm:table-cell">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="显示列"
                      >
                        <SlidersHorizontal aria-hidden />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuGroup>
                        {table
                          .getAllLeafColumns()
                          .filter((column) => column.getCanHide())
                          .map((column) => (
                            <DropdownMenuCheckboxItem
                              key={column.id}
                              checked={column.getIsVisible()}
                              disabled={
                                column.getIsVisible() &&
                                table.getVisibleLeafColumns().length === 1
                              }
                              onCheckedChange={(value) =>
                                column.toggleVisibility(!!value)
                              }
                            >
                              {
                                columns.find((item) => item.id === column.id)
                                  ?.header
                              }
                            </DropdownMenuCheckboxItem>
                          ))}
                      </DropdownMenuGroup>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableHead>
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                data-motion-item
                data-state={row.getIsSelected() ? 'selected' : undefined}
              >
                {selection ? (
                  <TableCell className="w-min">
                    <Checkbox
                      aria-label={`选择 ${getRowLabel?.(row.original) ?? row.id}`}
                      checked={row.getIsSelected()}
                      disabled={!row.getCanSelect()}
                      onCheckedChange={(value) =>
                        row.toggleSelected(value === true)
                      }
                    />
                  </TableCell>
                ) : null}
                {row.getVisibleCells().map((cell) => (
                  <TableCell
                    key={cell.id}
                    className={cn(
                      'whitespace-normal',
                      columns.find((column) => column.id === cell.column.id)
                        ?.className,
                    )}
                  >
                    <table.FlexRender cell={cell} />
                  </TableCell>
                ))}
                <TableCell aria-hidden className="hidden w-min sm:table-cell" />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// Stable component identity preserves focus when a dialog updates its parent list.
function renderDataCell<T extends RowData>({
  row,
  column,
}: CellContext<typeof features, T>) {
  const meta = column.columnDef.meta as { render: (item: T) => ReactNode };
  return meta.render(row.original);
}
