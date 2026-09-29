export enum ProviderSupportStatusCode {
  Unknown = 'unknown',
  Verified = 'verified',
  Degraded = 'degraded',
  AccessRequired = 'access_required',
  RateLimited = 'rate_limited',
  Blocked = 'blocked',
  Disabled = 'disabled',
  Unsupported = 'unsupported',
}

export enum ProviderAccessStateCode {
  PublicProbe = 'public_probe',
  PublicReady = 'public_ready',
  AuthorizationRequired = 'authorization_required',
  OperatorProbe = 'operator_probe',
  OperatorReady = 'operator_ready',
  Degraded = 'degraded',
  Blocked = 'blocked',
  Disabled = 'disabled',
  Unsupported = 'unsupported',
}

const READY_ACCESS_STATES = new Set<API.ProviderAccessState>([
  ProviderAccessStateCode.PublicReady,
  ProviderAccessStateCode.OperatorReady,
]);

const UNAVAILABLE_STATUSES = new Set<API.ProviderSupportStatus>([
  ProviderSupportStatusCode.AccessRequired,
  ProviderSupportStatusCode.Degraded,
  ProviderSupportStatusCode.RateLimited,
  ProviderSupportStatusCode.Blocked,
  ProviderSupportStatusCode.Disabled,
  ProviderSupportStatusCode.Unsupported,
]);

export function isCurrentlyAvailable(
  provider: API.ProviderListResponse['items'][number],
): boolean {
  return (
    provider.download_available &&
    READY_ACCESS_STATES.has(provider.access_state) &&
    !UNAVAILABLE_STATUSES.has(provider.status)
  );
}
