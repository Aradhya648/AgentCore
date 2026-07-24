/** Demo-tape director REST helpers. */

export function authHeaders(cookieHeader, csrf) {
  return {
    "Content-Type": "application/json",
    Cookie: cookieHeader,
    ...(csrf ? { "X-CSRF-Token": csrf } : {}),
  };
}

export async function director(api, cookieHeader, csrf, cid, method, path, body) {
  const url = `${api}/v1/demo-tape/director/${cid}${path}`;
  const res = await fetch(url, {
    method,
    headers: authHeaders(cookieHeader, csrf),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* plain */
  }
  if (!res.ok) {
    throw new Error(`director ${method} ${path} → ${res.status}: ${text.slice(0, 300)}`);
  }
  return json;
}

export async function waitStatus(
  api,
  cookieHeader,
  csrf,
  cid,
  pred,
  { timeoutMs = 60_000, label = "status" } = {},
) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < timeoutMs) {
    last = await director(api, cookieHeader, csrf, cid, "GET", "/status");
    if (pred(last)) return last;
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`timeout waiting ${label}; last=${JSON.stringify(last)}`);
}
