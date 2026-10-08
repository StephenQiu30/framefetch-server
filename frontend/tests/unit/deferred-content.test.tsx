import { act, render, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DeferredContent } from '@/components/layout/deferred-content';

describe('deferred content', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('mounts heavy content once when near the viewport and preserves it after scrolling away', () => {
    let notify!: IntersectionObserverCallback;
    const disconnect = vi.fn();
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(callback: IntersectionObserverCallback) {
          notify = callback;
        }
        observe() {}
        disconnect = disconnect;
      },
    );
    const mount = vi.fn();
    function HeavyContent() {
      useEffect(() => {
        mount();
      }, []);
      return <div>图表与精确数据</div>;
    }
    const view = render(
      <DeferredContent placeholder={<div>占位</div>}>
        <HeavyContent />
      </DeferredContent>,
    );
    const notifyVisibility = (isIntersecting: boolean) =>
      act(() =>
        notify(
          [{ isIntersecting }] as IntersectionObserverEntry[],
          {} as IntersectionObserver,
        ),
      );
    expect(mount).not.toHaveBeenCalled();
    notifyVisibility(false);
    expect(screen.queryByText('图表与精确数据')).toBeNull();
    notifyVisibility(true);
    expect(mount).toHaveBeenCalledOnce();
    notifyVisibility(false);
    expect(screen.getByText('图表与精确数据')).toBeVisible();
    view.unmount();
    expect(disconnect).toHaveBeenCalled();
  });

  it('shows explicitly requested details immediately and supports browsers without observation', () => {
    vi.stubGlobal('IntersectionObserver', undefined);
    const view = render(
      <DeferredContent eager placeholder="占位">
        指定分析记录
      </DeferredContent>,
    );
    expect(screen.getByText('指定分析记录')).toBeVisible();
    view.rerender(
      <DeferredContent placeholder="占位">指定分析记录</DeferredContent>,
    );
    expect(screen.getByText('指定分析记录')).toBeVisible();
    view.unmount();
    render(
      <DeferredContent placeholder="占位">兼容浏览器内容</DeferredContent>,
    );
    expect(screen.getByText('兼容浏览器内容')).toBeVisible();
  });
});
