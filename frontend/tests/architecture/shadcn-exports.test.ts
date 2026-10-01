import { describe, expect, it } from 'vitest';
import * as Alert from '@/components/ui/alert';
import * as AlertDialog from '@/components/ui/alert-dialog';
import * as Avatar from '@/components/ui/avatar';
import * as Badge from '@/components/ui/badge';
import * as Breadcrumb from '@/components/ui/breadcrumb';
import * as Calendar from '@/components/ui/calendar';
import * as Card from '@/components/ui/card';
import * as Chart from '@/components/ui/chart';
import * as Command from '@/components/ui/command';
import * as Dialog from '@/components/ui/dialog';
import * as DropdownMenu from '@/components/ui/dropdown-menu';
import * as Field from '@/components/ui/field';
import * as InputGroup from '@/components/ui/input-group';
import * as Item from '@/components/ui/item';
import * as Kbd from '@/components/ui/kbd';
import * as NavigationMenu from '@/components/ui/navigation-menu';
import * as Pagination from '@/components/ui/pagination';
import * as Popover from '@/components/ui/popover';
import * as Select from '@/components/ui/select';
import * as Table from '@/components/ui/table';
import * as Tabs from '@/components/ui/tabs';
import * as Toggle from '@/components/ui/toggle';
import * as Tooltip from '@/components/ui/tooltip';

// Complete public APIs from the approved c08aad0d component baseline.
// Unused subcomponents remain available for composition and CLI upgrades.
const components = [
  {
    name: 'alert-dialog',
    module: AlertDialog,
    exports:
      'AlertDialog AlertDialogAction AlertDialogCancel AlertDialogContent AlertDialogDescription AlertDialogFooter AlertDialogHeader AlertDialogMedia AlertDialogOverlay AlertDialogPortal AlertDialogTitle AlertDialogTrigger'.split(
        ' ',
      ),
  },
  {
    name: 'alert',
    module: Alert,
    exports: 'Alert AlertAction AlertDescription AlertTitle'.split(' '),
  },
  {
    name: 'avatar',
    module: Avatar,
    exports:
      'Avatar AvatarBadge AvatarFallback AvatarGroup AvatarGroupCount AvatarImage'.split(
        ' ',
      ),
  },
  { name: 'badge', module: Badge, exports: 'Badge badgeVariants'.split(' ') },
  {
    name: 'breadcrumb',
    module: Breadcrumb,
    exports:
      'Breadcrumb BreadcrumbEllipsis BreadcrumbItem BreadcrumbLink BreadcrumbList BreadcrumbPage BreadcrumbSeparator'.split(
        ' ',
      ),
  },
  {
    name: 'calendar',
    module: Calendar,
    exports: 'Calendar CalendarDayButton'.split(' '),
  },
  {
    name: 'card',
    module: Card,
    exports:
      'Card CardAction CardContent CardDescription CardFooter CardHeader CardTitle'.split(
        ' ',
      ),
  },
  {
    name: 'chart',
    module: Chart,
    exports:
      'ChartContainer ChartLegend ChartLegendContent ChartStyle ChartTooltip ChartTooltipContent'.split(
        ' ',
      ),
  },
  {
    name: 'command',
    module: Command,
    exports:
      'Command CommandDialog CommandEmpty CommandGroup CommandInput CommandItem CommandList CommandSeparator CommandShortcut'.split(
        ' ',
      ),
  },
  {
    name: 'dialog',
    module: Dialog,
    exports:
      'Dialog DialogClose DialogContent DialogDescription DialogFooter DialogHeader DialogOverlay DialogPortal DialogTitle DialogTrigger'.split(
        ' ',
      ),
  },
  {
    name: 'dropdown-menu',
    module: DropdownMenu,
    exports:
      'DropdownMenu DropdownMenuCheckboxItem DropdownMenuContent DropdownMenuGroup DropdownMenuItem DropdownMenuLabel DropdownMenuPortal DropdownMenuRadioGroup DropdownMenuRadioItem DropdownMenuSeparator DropdownMenuShortcut DropdownMenuSub DropdownMenuSubContent DropdownMenuSubTrigger DropdownMenuTrigger'.split(
        ' ',
      ),
  },
  {
    name: 'field',
    module: Field,
    exports:
      'Field FieldContent FieldDescription FieldError FieldGroup FieldLabel FieldLegend FieldSeparator FieldSet FieldTitle'.split(
        ' ',
      ),
  },
  {
    name: 'input-group',
    module: InputGroup,
    exports:
      'InputGroup InputGroupAddon InputGroupButton InputGroupInput InputGroupText InputGroupTextarea'.split(
        ' ',
      ),
  },
  {
    name: 'item',
    module: Item,
    exports:
      'Item ItemActions ItemContent ItemDescription ItemFooter ItemGroup ItemHeader ItemMedia ItemSeparator ItemTitle'.split(
        ' ',
      ),
  },
  { name: 'kbd', module: Kbd, exports: 'Kbd KbdGroup'.split(' ') },
  {
    name: 'navigation-menu',
    module: NavigationMenu,
    exports:
      'NavigationMenu NavigationMenuContent NavigationMenuIndicator NavigationMenuItem NavigationMenuLink NavigationMenuList NavigationMenuTrigger NavigationMenuViewport navigationMenuTriggerStyle'.split(
        ' ',
      ),
  },
  {
    name: 'pagination',
    module: Pagination,
    exports:
      'Pagination PaginationContent PaginationEllipsis PaginationItem PaginationLink PaginationNext PaginationPrevious'.split(
        ' ',
      ),
  },
  {
    name: 'popover',
    module: Popover,
    exports:
      'Popover PopoverAnchor PopoverContent PopoverDescription PopoverHeader PopoverTitle PopoverTrigger'.split(
        ' ',
      ),
  },
  {
    name: 'select',
    module: Select,
    exports:
      'Select SelectContent SelectGroup SelectItem SelectLabel SelectScrollDownButton SelectScrollUpButton SelectSeparator SelectTrigger SelectValue'.split(
        ' ',
      ),
  },
  {
    name: 'table',
    module: Table,
    exports:
      'Table TableBody TableCaption TableCell TableFooter TableHead TableHeader TableRow'.split(
        ' ',
      ),
  },
  {
    name: 'tabs',
    module: Tabs,
    exports: 'Tabs TabsContent TabsList TabsTrigger tabsListVariants'.split(
      ' ',
    ),
  },
  {
    name: 'toggle',
    module: Toggle,
    exports: 'Toggle toggleVariants'.split(' '),
  },
  {
    name: 'tooltip',
    module: Tooltip,
    exports: 'Tooltip TooltipContent TooltipProvider TooltipTrigger'.split(' '),
  },
];

describe('shadcn component export contracts', () => {
  it.each(components)(
    '$name retains its complete public API',
    ({ module, exports }) => {
      for (const name of exports) {
        expect(module, name).toHaveProperty(name);
        expect((module as Record<string, unknown>)[name], name).toBeDefined();
      }
    },
  );
});
