/**
 * Normalize IPC binary payloads to Uint8Array.
 * Structured clone may deliver ArrayBuffer or another TypedArray view instead of Uint8Array.
 */
export function coerceIpcBytes(bytes: unknown): Uint8Array | null {
  if (bytes instanceof Uint8Array) return bytes;
  if (bytes instanceof ArrayBuffer) return new Uint8Array(bytes);
  if (ArrayBuffer.isView(bytes)) {
    const view = bytes as ArrayBufferView;
    return new Uint8Array(view.buffer, view.byteOffset, view.byteLength);
  }
  return null;
}
