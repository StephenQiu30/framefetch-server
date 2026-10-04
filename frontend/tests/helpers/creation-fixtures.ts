export const creationRevision: API.CreationRevisionResponse = {
  id: 'revision-1',
  number: 1,
  parent_revision_id: null,
  text: '原稿有一条已观察事实。',
  data: {
    pages: [{ id: 'page-1', title: '标题', body: '卡片正文' }],
    source_metadata: { source: 'original' },
  },
  sha256: 'a'.repeat(64),
  confirmed: false,
  created_at: '2026-10-04T08:00:00Z',
};

export const creationMaterial: API.CreationMaterialResponse = {
  id: 'material-1',
  project_id: 'project-1',
  kind: 'text',
  title: '原创材料',
  rights_statement: '本人原创，用于本次整理',
  artifact_id: null,
  document_id: null,
  source_url: null,
  current_revision: {
    ...creationRevision,
    id: 'material-revision-1',
    text: '明确观察到的数据只有十次。',
    confirmed: true,
  },
  created_at: '2026-10-04T08:00:00Z',
  updated_at: '2026-10-04T08:00:00Z',
};

export const creationTask: API.CreationTaskResponse = {
  id: 'task-1',
  project_id: 'project-1',
  skill_id: 'article-edit',
  status: 'awaiting_confirmation',
  material_revision_ids: ['material-revision-1'],
  options: { mode: 'format' },
  budget: { max_calls: 4, max_tokens: 16_000, timeout_seconds: 600 },
  usage: {
    calls_reserved: 0,
    calls_used: 0,
    tokens_reserved: 0,
    cost_minor_reserved: 0,
    unknown_operations: 0,
  },
  output_language: 'zh-CN',
  attempt: 1,
  revision: creationRevision,
  stale: false,
  limitations: [],
  error_code: null,
  created_at: '2026-10-04T08:00:00Z',
  updated_at: '2026-10-04T08:00:00Z',
};

export const creationSkill: API.CreationSkillResponse = {
  id: 'article-edit',
  code: 'CAP-13',
  name: '文章编辑与格式整理',
  route: 'article',
  priority: 'P0',
  execution_kind: 'local',
  input_kinds: ['article'],
  export_formats: ['md', 'docx'],
  method_version: 'test-method',
  method_sha256: 'b'.repeat(64),
  available: true,
  limitations: [],
};
