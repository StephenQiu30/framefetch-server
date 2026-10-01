export function isDownloadEnabled(
  provider: API.ProviderListResponse['items'][number],
): boolean {
  return (
    provider.registered &&
    provider.extractor_exists &&
    provider.download_supported &&
    provider.status === 'unknown'
  );
}
