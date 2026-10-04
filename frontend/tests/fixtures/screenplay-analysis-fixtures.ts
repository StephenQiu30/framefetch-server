const screenplayAnalysisResult: API.ScreenplayAnalysisResultResponse = {
  kind: 'screenplay_analysis',
  language: 'zh-CN',
  title: '午夜来客',
  logline: '剪辑师必须在天亮前找回一段被删除的结局素材。',
  synopsis: '林舟在封闭的剪辑室追查素材失踪原因，并重新面对自己的选择。',
  structure: {
    acts: [
      {
        id: 'act-1',
        title: '第一幕',
        description: '建立素材失踪与时间压力。',
      },
    ],
    turning_points: [
      {
        id: 'turn-1',
        title: '硬盘重新亮起',
        description: '外部故障转为人物主动选择。',
      },
    ],
    pacing_summary: '前段信息清楚，第二场的决定可以留出更长停顿。',
  },
  characters: [
    {
      id: 'character-1',
      name: '林舟',
      goal: '找回结局素材',
      conflict: '害怕面对自己删除素材的原因',
      arc: '从逃避转向承认选择',
    },
  ],
  scenes: [
    {
      id: 'result-scene-1',
      source_scene_id: 'scene-0001',
      purpose: '建立任务与时限',
      conflict: '素材缺失且备份不可用',
      turn: '林舟发现删除记录来自自己账号',
      pacing: '紧凑',
      findings: ['动作线清楚', '可以强化时钟声音'],
    },
  ],
  dialogue_findings: [
    {
      id: 'dialogue-1',
      title: '对白信息略直白',
      description: '可让林舟通过操作和停顿表达犹豫。',
    },
  ],
  strengths: [
    {
      id: 'strength-1',
      title: '目标明确',
      description: '首场迅速建立寻找素材的行动目标。',
    },
  ],
  priority_revisions: [
    {
      id: 'revision-1',
      title: '强化人物选择',
      description: '在转折后增加林舟主动恢复素材的动作。',
    },
  ],
};

const screenplayRewriteResult: API.ScreenplayRewriteResultResponse = {
  kind: 'screenplay_rewrite',
  source_language: 'zh-CN',
  target_language: 'en-US',
  source_scene_count: 2,
  output_scene_count: 2,
  glossary: [
    { source: '林舟', target: 'Lin Zhou', category: 'character' },
    { source: '剪辑室', target: 'editing suite', category: 'location' },
  ],
  change_summary: ['统一人物名译法。', '保留场景标题与动作行格式。'],
};

export function screenplayAnalysisJob(
  kind: 'analysis' | 'rewrite',
  status: API.AnalysisResponse['status'] = 'succeeded',
): API.AnalysisResponse {
  const result =
    kind === 'analysis' ? screenplayAnalysisResult : screenplayRewriteResult;
  return {
    id: '77777777-7777-4777-8777-777777777777',
    run_id: '88888888-8888-4888-8888-888888888888',
    run_no: 1,
    run_trigger: 'initial',
    version: status === 'queued' ? 0 : 2,
    skill_id:
      kind === 'analysis' ? 'screenplay-analysis' : 'screenplay-rewrite',
    output_language: kind === 'analysis' ? 'zh-CN' : 'en-US',
    input_kind: 'screenplay',
    result_contract:
      kind === 'analysis' ? 'screenplay-analysis' : 'screenplay-rewrite',
    status,
    stage: status === 'running' ? 'analyzing' : null,
    progress: status === 'succeeded' ? 100 : 20,
    attempt: status === 'queued' ? 0 : 1,
    error_code: status === 'failed' ? 'analysis_cli_failed' : null,
    created_at: '2026-08-14T12:00:00Z',
    updated_at: '2026-08-14T12:01:00Z',
    finished_at: status === 'succeeded' ? '2026-08-14T12:01:00Z' : null,
    result: status === 'succeeded' ? result : null,
    report_markdown:
      status === 'succeeded'
        ? kind === 'analysis'
          ? '# 午夜来客\n\n## 结构分析\n\n分析正文。\n'
          : '# Midnight Visitor\n\n## Rewritten screenplay\n\nINT. EDITING SUITE - NIGHT\n'
        : null,
    current_report_id:
      status === 'succeeded' ? '99999999-9999-4999-8999-999999999999' : null,
    report:
      status === 'succeeded'
        ? {
            id: '99999999-9999-4999-8999-999999999999',
            status: 'available',
            renderer_version: 'analysis-report',
            content_sha256: 'a'.repeat(64),
            published_at: '2026-08-14T12:01:00Z',
            artifacts: [
              {
                format: 'markdown',
                media_type: 'text/markdown; charset=utf-8',
                size_bytes: 256,
                sha256: 'b'.repeat(64),
              },
              {
                format: 'docx',
                media_type:
                  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                size_bytes: 512,
                sha256: 'c'.repeat(64),
              },
            ],
          }
        : null,
  };
}
