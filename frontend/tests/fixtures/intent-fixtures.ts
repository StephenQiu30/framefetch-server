export function intentFixture(
  overrides: Partial<API.IntentResponse> = {},
): API.IntentResponse {
  return {
    id: '44444444-4444-4444-8444-444444444444',
    version: 2,
    status: 'ready',
    reason_code: null,
    failure: null,
    next_action: 'none',
    deadline: new Date(Date.now() + 180_000).toISOString(),
    inspection_id: '11111111-1111-4111-8111-111111111111',
    job_id: null,
    ...overrides,
  };
}
