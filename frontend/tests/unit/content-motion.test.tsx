import { act, render, screen, waitFor } from '@testing-library/react';
import gsap from 'gsap';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ContentMotion from '@/components/layout/content-motion';

function Cards({
  contentKey = 'one',
  late = false,
}: {
  contentKey?: string;
  late?: boolean;
}) {
  const [scope, setScope] = useState<HTMLElement | null>(null);
  return (
    <>
      <div data-recent-download-item>其他区块</div>
      <section ref={setScope}>
        <div data-recent-download-item>下载记录</div>
        {late ? <header data-slot="page-header">异步标题</header> : null}
        {scope ? <ContentMotion scope={scope} contentKey={contentKey} /> : null}
      </section>
    </>
  );
}

function setMotionPreference(allowed: boolean) {
  vi.stubGlobal('IntersectionObserver', undefined);
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (media) =>
      ({
        media,
        matches: allowed,
        addListener: vi.fn(),
        removeListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );
}

describe('shared content motion', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('reveals offscreen content on intersection and ignores callbacks after unmount', () => {
    setMotionPreference(true);
    let intersect!: IntersectionObserverCallback;
    const disconnect = vi.fn();
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(callback: IntersectionObserverCallback) {
          intersect = callback;
        }
        observe() {}
        unobserve() {}
        disconnect = disconnect;
      },
    );
    const from = vi.spyOn(gsap, 'from');
    const view = render(<Cards />);
    const card = screen.getByText('下载记录');
    expect(from).not.toHaveBeenCalled();
    const notify = () =>
      intersect(
        [
          {
            target: card,
            isIntersecting: true,
            intersectionRatio: 1,
            boundingClientRect: card.getBoundingClientRect(),
            intersectionRect: card.getBoundingClientRect(),
            rootBounds: null,
            time: 0,
          },
        ],
        {} as IntersectionObserver,
      );
    act(notify);
    expect(gsap.getTweensOf(card)).toHaveLength(1);
    view.unmount();
    act(notify);
    expect(from).toHaveBeenCalledOnce();
    expect(disconnect).toHaveBeenCalled();
    expect(card.style.transform).toBe('');
  });

  it('reverts active motion when the user enables reduced motion', () => {
    let allowed = true;
    vi.stubGlobal('IntersectionObserver', undefined);
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (media) =>
        ({
          media,
          matches: allowed,
          addListener: vi.fn(),
          removeListener: vi.fn(),
        }) as unknown as MediaQueryList,
    );
    render(<Cards />);
    const card = screen.getByText('下载记录');
    expect(gsap.getTweensOf(card)).toHaveLength(1);
    allowed = false;
    act(() => gsap.matchMediaRefresh());
    expect(gsap.getTweensOf(card)).toHaveLength(0);
    expect(card.style.opacity).toBe('');
    expect(card.style.transform).toBe('');
  });
  it('keeps records visible without animating when reduced motion is requested', () => {
    setMotionPreference(false);
    const from = vi.spyOn(gsap, 'from');
    render(<Cards />);
    expect(from).not.toHaveBeenCalled();
    expect(screen.getByText('下载记录')).toBeVisible();
    expect(screen.getByText('下载记录')).not.toHaveAttribute('style');
  });

  it('animates asynchronously mounted page content once', async () => {
    setMotionPreference(true);
    const from = vi.spyOn(gsap, 'from');
    const view = render(<Cards />);
    view.rerender(<Cards late />);
    await waitFor(() =>
      expect(gsap.getTweensOf(screen.getByText('异步标题'))).toHaveLength(1),
    );
    expect(from).toHaveBeenCalledTimes(2);
    view.rerender(<Cards late />);
    expect(from).toHaveBeenCalledTimes(2);
  });

  it('reveals late content within a tab panel that has already appeared', async () => {
    setMotionPreference(true);
    const view = render(<Cards />);
    const scope = view.container.querySelector('section');
    const panel = document.createElement('div');
    panel.dataset.slot = 'tabs-content';
    act(() => {
      scope?.append(panel);
    });
    await waitFor(() => expect(gsap.getTweensOf(panel)).toHaveLength(1));
    const heading = document.createElement('header');
    heading.dataset.slot = 'page-header';
    act(() => {
      panel.append(heading);
    });
    await waitFor(() => expect(gsap.getTweensOf(heading)).toHaveLength(1));
  });

  it('scopes motion to its records, avoids replay on updates and cleans up on unmount', () => {
    setMotionPreference(true);
    const from = vi.spyOn(gsap, 'from');
    const view = render(<Cards />);
    const card = screen.getByText('下载记录');
    expect(gsap.getTweensOf(card)).toHaveLength(1);
    expect(gsap.getTweensOf(screen.getByText('其他区块'))).toHaveLength(0);
    view.rerender(<Cards />);
    expect(from).toHaveBeenCalledOnce();
    view.unmount();
    expect(gsap.getTweensOf(card)).toHaveLength(0);
    expect(card.style.opacity).toBe('');
    expect(card.style.transform).toBe('');
  });
});
