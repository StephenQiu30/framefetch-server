import { type RefObject, useEffect, useState } from 'react';

/** Activate once, including elements inside scroll containers or hidden tabs. */
export function useNearViewport(ref: RefObject<Element | null>, eager = false) {
  const [activated, setActivated] = useState(eager);
  useEffect(() => {
    if (eager) {
      setActivated(true);
      return;
    }
    if (activated || !ref.current) return;
    if (typeof IntersectionObserver === 'undefined') {
      setActivated(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setActivated(true);
        observer.disconnect();
      },
      { rootMargin: '160px 0px' },
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [activated, eager, ref]);
  return eager || activated;
}
