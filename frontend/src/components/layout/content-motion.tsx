'use client';

import { useGSAP } from '@gsap/react';
import gsap from 'gsap';

gsap.registerPlugin(useGSAP);

const targets =
  '[data-slot="page-header"], [data-motion-group] > *, [data-motion-item], [data-slot="tabs-content"], [data-recent-download-item]';

export default function ContentMotion({
  scope,
  contentKey,
}: {
  scope: HTMLElement;
  contentKey: string;
}) {
  useGSAP(
    () => {
      const media = gsap.matchMedia();
      media.add('(prefers-reduced-motion: no-preference)', (mediaContext) => {
        const seen = new WeakSet<Element>();
        const observed = new Set<Element>();
        let active = true;
        // Observer callbacks belong to this media context so changing the
        // motion preference also reverts every animation they create.
        const animate = mediaContext.add('reveal', (elements: Element[]) => {
          if (!active) return;
          const fresh = elements.filter((element) => {
            if (seen.has(element) || !scope.contains(element)) return false;
            seen.add(element);
            return !element.contains(document.activeElement);
          });
          if (!fresh.length) return;
          gsap.from(fresh, {
            opacity: 0.85,
            y: 6,
            duration: 0.28,
            stagger: { amount: 0.12 },
            ease: 'power2.out',
            clearProps: 'opacity,transform',
          });
        });
        const viewport =
          typeof IntersectionObserver === 'undefined'
            ? null
            : new IntersectionObserver((entries) => {
                const visible = entries
                  .filter((entry) => entry.isIntersecting)
                  .map((entry) => entry.target);
                for (const element of visible) {
                  viewport?.unobserve(element);
                  observed.delete(element);
                }
                animate(visible);
              });
        const scan = (root: Element) => {
          const candidates = [
            ...(root.matches(targets) ? [root] : []),
            ...root.querySelectorAll(targets),
          ];
          const elements = candidates.filter((element) => {
            const parentTarget = element.parentElement?.closest(targets);
            return (
              scope.contains(element) &&
              element !== scope &&
              !seen.has(element) &&
              !observed.has(element) &&
              !element.closest(
                '[hidden], [aria-hidden="true"], [data-slot="route-loading"]',
              ) &&
              !(parentTarget && root.contains(parentTarget))
            );
          });
          if (!viewport) animate(elements);
          else
            for (const element of elements) {
              observed.add(element);
              viewport.observe(element);
            }
        };
        const mutations = new MutationObserver((records) => {
          if (!active) return;
          if (records.some((record) => record.removedNodes.length)) {
            for (const element of observed) {
              if (!scope.contains(element)) {
                viewport?.unobserve(element);
                observed.delete(element);
              }
            }
          }
          for (const record of records) {
            if (
              record.type === 'attributes' &&
              record.target instanceof Element
            )
              scan(record.target);
            else
              for (const node of record.addedNodes)
                if (node instanceof Element) scan(node);
          }
        });
        mutations.observe(scope, {
          childList: true,
          subtree: true,
          attributes: true,
          attributeFilter: ['aria-hidden', 'data-state', 'hidden'],
        });
        scan(scope);
        return () => {
          active = false;
          mutations.disconnect();
          viewport?.disconnect();
          observed.clear();
        };
      });
      return () => media.revert();
    },
    { scope, dependencies: [contentKey], revertOnUpdate: true },
  );
  return null;
}
