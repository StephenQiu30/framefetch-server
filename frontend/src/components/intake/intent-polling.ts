import { isTerminalIntentStatus } from '@/components/intake/intent-status';
import { ApiError } from '@/lib/request-error';

export function intentPollingInterval(
  intent?: API.IntentResponse,
  error?: unknown,
): number | false {
  if (intent && isTerminalIntentStatus(intent.status)) return false;
  if (
    error instanceof ApiError &&
    error.status >= 400 &&
    error.status < 500 &&
    error.status !== 408 &&
    error.status !== 429
  )
    return false;
  // The deadline limits server work. A delayed terminal write or transient
  // transport failure still needs read-only reconciliation of the same intent.
  return error || (intent && Date.parse(intent.deadline) <= Date.now())
    ? 5_000
    : 2_000;
}
