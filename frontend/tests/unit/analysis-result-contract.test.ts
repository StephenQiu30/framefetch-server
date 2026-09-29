import { describe, expect, it } from 'vitest';

type PublicResult = NonNullable<API.AnalysisResponse['result']>;

function resultMetric(result: PublicResult): number {
  switch (result.kind) {
    case 'video_visual_analysis':
      return result.shot_count;
    case 'video_article':
      return result.sections.length;
    case 'screenplay_analysis':
      return result.scenes.length;
    case 'screenplay_rewrite':
      return result.output_scene_count;
    case 'structured_report':
      return result.sections.length;
    default: {
      const exhaustive: never = result;
      return exhaustive;
    }
  }
}

describe('analysis result OpenAPI union', () => {
  it('keeps every public result branch exhaustively discriminated', () => {
    expect(typeof resultMetric).toBe('function');
  });

  it('does not expose rewrite chunks in the generated public response', () => {
    type RewriteHasChunks =
      'chunks' extends keyof API.ScreenplayRewriteResultResponse ? true : false;
    const rewriteHasChunks: RewriteHasChunks = false;

    expect(rewriteHasChunks).toBe(false);
  });
});
