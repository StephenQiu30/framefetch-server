import { vi } from 'vitest';

const nativeRandomValues = crypto.getRandomValues.bind(crypto);

export function stubCryptoUuids(...uuids: string[]) {
  const values = uuids.map(uuidBytes);
  let index = 0;
  const getRandomValues = vi.fn((target: Uint8Array) => {
    // Editor.js also generates short block IDs; only UUID requests consume this fixture sequence.
    if (target.byteLength !== 16) return nativeRandomValues(target);
    const value = values[Math.min(index, values.length - 1)];
    index += 1;
    target.set(value);
    return target;
  });
  vi.stubGlobal('crypto', {
    getRandomValues,
    randomUUID: vi.fn(() => uuids[0]),
  });
  return getRandomValues;
}

function uuidBytes(uuid: string): Uint8Array {
  const hex = uuid.replaceAll('-', '');
  if (!/^[0-9a-f]{32}$/i.test(hex)) throw new Error('invalid test UUID');
  return Uint8Array.from(
    Array.from({ length: 16 }, (_, index) =>
      Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16),
    ),
  );
}
