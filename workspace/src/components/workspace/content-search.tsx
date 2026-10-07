'use client';

import Link from 'next/link';
import { useEffect, useId, useRef, useState } from 'react';
import type { ContentSearchResult } from '@/lib/workspace/content';

export function ContentSearch() {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<ContentSearchResult[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('ready');
  const [active, setActive] = useState(-1);
  const [revision, setRevision] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();

  useEffect(() => {
    const changed = () => setRevision((value) => value + 1);
    window.addEventListener('workspace-content-changed', changed);
    return () =>
      window.removeEventListener('workspace-content-changed', changed);
  }, []);

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (
        target.isContentEditable ||
        /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)
      )
        return;
      if (
        event.key === '/' ||
        (event.key === 'k' && (event.metaKey || event.ctrlKey))
      ) {
        event.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);

  useEffect(() => {
    if (!open || !query.trim()) {
      setResults([]);
      setStatus('ready');
      return;
    }
    const controller = new AbortController();
    setStatus('loading');
    setActive(-1);
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/search?q=${encodeURIComponent(query)}`, {
          cache: 'no-store',
          signal: controller.signal,
        });
        if (!response.ok) throw new Error('search_failed');
        const data = (await response.json()) as ContentSearchResult[];
        if (!controller.signal.aborted) {
          setResults(data);
          setStatus('ready');
        }
      } catch {
        if (!controller.signal.aborted) {
          setResults([]);
          setStatus('error');
        }
      }
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, open, revision]);

  const visible = open && Boolean(query.trim());
  return (
    <div
      className="workspace-search"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <input
        ref={input}
        type="search"
        role="combobox"
        aria-label="搜索文档"
        placeholder="搜索文档…"
        value={query}
        aria-expanded={visible}
        aria-controls={`${id}-results`}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${id}-${active}` : undefined}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            setOpen(false);
            setActive(-1);
          }
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            setOpen(true);
            setActive((index) => {
              if (!results.length) return -1;
              const down = event.key === 'ArrowDown';
              if (index < 0) return down ? 0 : results.length - 1;
              return (index + (down ? 1 : -1) + results.length) % results.length;
            });
          }
          if (event.key === 'Enter' && active >= 0 && status === 'ready') {
            event.preventDefault();
            document.getElementById(`${id}-${active}`)?.click();
          }
        }}
      />
      {visible && (
        <div className="workspace-search-results">
          <p role="status" className="text-muted-foreground text-sm">
            {status === 'loading'
              ? '正在搜索…'
              : status === 'error'
                ? '搜索失败，请重新输入或稍后重试。'
                : results.length
                  ? `${results.length} 条结果`
                  : '没有找到相关内容'}
          </p>
          <ul id={`${id}-results`} role="listbox" aria-label="文档搜索结果">
            {status === 'ready' &&
              results.map((result, index) => (
                <li key={result.url} role="none">
                  <Link
                    id={`${id}-${index}`}
                    href={result.url}
                    role="option"
                    aria-selected={active === index}
                    prefetch={false}
                    onClick={() => setOpen(false)}
                  >
                    <span className="font-medium">{result.title}</span>
                    <span className="text-muted-foreground text-sm">
                      {result.excerpt}
                    </span>
                  </Link>
                </li>
              ))}
          </ul>
        </div>
      )}
    </div>
  );
}
