import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import AnalysisVideoResult, {
  isVideoAnalysisResult,
} from '@/components/analysis/analysis-video-result';

const report: API.StructuredReportResultResponse = {
  kind: 'structured_report',
  language: 'zh-CN',
  title: '短视频包装方案',
  summary: '开头 3 秒的动作最抓人。',
  sections: [
    {
      id: 'titles',
      heading: '标题备选',
      body: '三条标题分别强调冲突、结果和悬念。',
      items: ['他只用了 3 秒', '<img src=x onerror=alert(1)>'],
      evidence: [],
    },
    {
      id: 'hook',
      heading: '开头钩子',
      body: '第一帧已经出现关键动作。',
      items: [],
      evidence: [{ start_ms: 0, end_ms: 3_000, note: '起跳' }],
    },
  ],
  limitations: ['未核验音频内容'],
  media: { duration_ms: 60_000, container: 'mp4', size_bytes: 4_096 },
};

describe('structured report result', () => {
  it('is classified as a video result', () => {
    expect(isVideoAnalysisResult(report)).toBe(true);
    expect(isVideoAnalysisResult(null)).toBe(false);
  });

  it('renders sections, items, evidence and limitations as plain text', () => {
    const onSelectTime = vi.fn();
    const { container } = render(
      <AnalysisVideoResult onSelectTime={onSelectTime} result={report} />,
    );

    expect(screen.getByText('标题备选')).toBeTruthy();
    expect(screen.getByText('他只用了 3 秒')).toBeTruthy();
    // Model output is text: the injected tag is shown, never parsed.
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeTruthy();
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('未核验音频内容')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /查看视频依据/ }));
    expect(onSelectTime).toHaveBeenCalledWith(0);
  });
});
