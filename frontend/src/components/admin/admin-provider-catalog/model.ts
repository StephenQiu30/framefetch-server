type EditorMode = 'create' | 'edit';

export type CatalogEditorState = {
  mode: EditorMode | null;
  key: string;
  displayName: string;
  sortOrder: string;
  visible: boolean;
  systemRegistered: boolean;
  error: string;
  saving: boolean;
};

export type CatalogDeleteState = {
  target: API.ProviderCatalogEntryResponse | null;
  error: string;
  deleting: boolean;
};

export type CatalogResultState = {
  items: API.ProviderCatalogEntryResponse[];
  loading: boolean;
  error: string;
};

export const EMPTY_EDITOR: CatalogEditorState = {
  mode: null,
  key: '',
  displayName: '',
  sortOrder: '100',
  visible: true,
  systemRegistered: false,
  error: '',
  saving: false,
};
