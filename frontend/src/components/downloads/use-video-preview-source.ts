import { useCallback, useEffect, useState } from 'react';
import { issueDownloadUrl } from '@/api/downloads';
import { displayError } from '@/lib/request-error';

export function useVideoPreviewSource(downloadId: string) {
  const [filename, setFilename] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    void requestVersion;
    let disposed = false;
    setLoading(true);
    setError(null);
    setFilename(null);

    void issueDownloadUrl(
      {
        job_id: encodeURIComponent(downloadId),
        preview: true,
      },
      {
        headers: { 'X-Framefetch-Download-Client': 'local-web' },
      },
    )
      .then((result) => {
        if (!disposed) {
          setSource(result.url);
          setFilename(result.filename);
        }
      })
      .catch((reason) => {
        if (!disposed) setError(displayError(reason));
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });

    return () => {
      disposed = true;
    };
  }, [downloadId, requestVersion]);

  const reload = useCallback(() => {
    setSource(null);
    setRequestVersion((current) => current + 1);
  }, []);

  const reportPlaybackError = useCallback(() => {
    setSource(null);
    setError('预览地址已失效，或当前浏览器不支持该视频格式。');
  }, []);

  return { filename, error, loading, reload, reportPlaybackError, source };
}
