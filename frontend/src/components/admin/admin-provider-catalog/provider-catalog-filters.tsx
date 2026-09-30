'use client';

import { MagnifyingGlassIcon } from '@phosphor-icons/react';

import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export type CatalogVisibility = 'all' | 'visible' | 'hidden';

type ProviderCatalogFiltersProps = {
  query: string;
  visibility: CatalogVisibility;
  onQueryChange: (value: string) => void;
  onVisibilityChange: (value: CatalogVisibility) => void;
};

export function ProviderCatalogFilters({
  query,
  visibility,
  onQueryChange,
  onVisibilityChange,
}: ProviderCatalogFiltersProps) {
  return (
    <FieldGroup className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Field>
        <FieldLabel htmlFor="provider-catalog-search">搜索平台</FieldLabel>
        <InputGroup>
          <InputGroupAddon>
            <MagnifyingGlassIcon aria-hidden />
          </InputGroupAddon>
          <InputGroupInput
            id="provider-catalog-search"
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="搜索名称或目录键"
            type="search"
            value={query}
          />
        </InputGroup>
      </Field>
      <Field>
        <FieldLabel htmlFor="provider-catalog-visibility">公开状态</FieldLabel>
        <Select
          onValueChange={(value) =>
            onVisibilityChange(value as CatalogVisibility)
          }
          value={visibility}
        >
          <SelectTrigger className="w-full" id="provider-catalog-visibility">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="visible">公开显示</SelectItem>
              <SelectItem value="hidden">已隐藏</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </Field>
    </FieldGroup>
  );
}
