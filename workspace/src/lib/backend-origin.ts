// Deployment configuration only; never derive the API target from request headers.
export function backendOrigin(): URL {
  const target = new URL(process.env.BACKEND_ORIGIN ?? 'http://127.0.0.1:8111');
  if (
    !['http:', 'https:'].includes(target.protocol) ||
    target.username ||
    target.password ||
    target.pathname !== '/' ||
    target.search ||
    target.hash
  )
    throw new Error('Invalid backend origin');
  return target;
}
