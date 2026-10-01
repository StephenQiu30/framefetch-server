export function resolveTarget(value: string | null): URL | null {
  const expected = storageOrigin();
  if (!value || !expected) return null;
  try {
    const target = new URL(value);
    if (
      target.origin !== expected ||
      target.username ||
      target.password ||
      target.hash ||
      target.searchParams.get('X-Amz-Algorithm') !== 'AWS4-HMAC-SHA256' ||
      !target.searchParams.has('X-Amz-Signature')
    ) {
      return null;
    }
    return target;
  } catch {
    return null;
  }
}

function storageOrigin(): string | null {
  return configuredStorageOrigin(
    process.env.MINIO_PUBLIC_ENDPOINT,
    process.env.MINIO_PUBLIC_SECURE === 'true',
  );
}

export function internalStorageTarget(target: URL): URL {
  const origin = configuredStorageOrigin(
    process.env.MINIO_ENDPOINT,
    process.env.MINIO_INTERNAL_SECURE === 'true',
  );
  if (!origin) return target;
  return new URL(`${target.pathname}${target.search}`, origin);
}

function configuredStorageOrigin(
  configuredEndpoint: string | undefined,
  secure: boolean,
): string | null {
  const endpoint = configuredEndpoint?.trim();
  if (!endpoint) return null;
  try {
    const origin = new URL(`${secure ? 'https' : 'http'}://${endpoint}`);
    if (
      !origin.hostname ||
      origin.username ||
      origin.password ||
      origin.pathname !== '/' ||
      origin.search ||
      origin.hash
    ) {
      return null;
    }
    return origin.origin;
  } catch {
    return null;
  }
}
