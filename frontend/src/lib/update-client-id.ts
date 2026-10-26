// getRandomValues is available on plain HTTP aliases; randomUUID requires a secure context.
export function createUpdateClientId(
  source: Pick<Crypto, "getRandomValues"> = globalThis.crypto
): string {
  const bytes = source.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")
}
