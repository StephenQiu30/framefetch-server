'use client';

/** The preview has no identity, scripts, navigation or external resources. */
export function CreationSafePreview({ html }: { html: string }) {
  const policy = [
    "default-src 'none'",
    "script-src 'none'",
    "style-src 'unsafe-inline'",
    'img-src data: blob:',
    'font-src data:',
    "connect-src 'none'",
    "frame-src 'none'",
    "form-action 'none'",
    "base-uri 'none'",
  ].join('; ');
  const source = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="${policy}"></head><body>${html}</body></html>`;
  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">
        安全预览显示正文结构，图片请在资源包中核对。外部资源与脚本被禁用；目标编辑器中的排版需要另外核验。
      </p>
      <iframe
        className="min-h-96 w-full"
        title="公众号安全预览"
        srcDoc={source}
        sandbox=""
        referrerPolicy="no-referrer"
      />
    </div>
  );
}
