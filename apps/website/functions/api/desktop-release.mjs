import { fetchLatestReleaseArtifacts } from "../_lib/releaseArtifacts.mjs";

const FALLBACK_VERSION = "0.6.8";
const CACHE_SECONDS = 300;

/** Cloudflare Pages Function — runtime latest desktop release for /download. */
export async function onRequest() {
  const artifacts = await fetchLatestReleaseArtifacts(FALLBACK_VERSION);
  return new Response(JSON.stringify(artifacts), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": `public, max-age=${CACHE_SECONDS}`,
    },
  });
}
