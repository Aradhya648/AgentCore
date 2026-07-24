import { BASE_URL } from "@/api/client";
// IM avatar circle: public user avatar URLs work as bare <img src> (no Bearer).
// Missing / broken images fall back to the name initial — same pattern as desktop
// ChatAvatar, plus onError so we can try `/v1/users/{id}/avatar` without a
// prior "has avatar" flag (ChatParticipant has no avatar_url).
import { useState } from "react";

/** Resolve a backend-relative avatar path for <img src>. */
export function avatarSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith("/") ? `${BASE_URL}${url}` : url;
}

/** Public avatar path for a user id (404 when unset — ImAvatar falls back). */
export function userAvatarPath(userId: string): string {
  return `/v1/users/${userId}/avatar`;
}

/** First character for a fallback avatar (CJK-safe). */
export function avatarInitial(name: string): string {
  return Array.from(name.trim())[0]?.toUpperCase() ?? "?";
}

export function ImAvatar({
  name,
  url,
  className = "im-avatar",
}: {
  name: string;
  url?: string | null;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  // url 变化时在渲染期重置加载失败标记（React「adjust state on prop change」
  // 模式，替代仅为重置而挂的 effect）。
  const [prevUrl, setPrevUrl] = useState(url);
  if (prevUrl !== url) {
    setPrevUrl(url);
    setFailed(false);
  }

  const src = avatarSrc(url);
  if (src && !failed) {
    return (
      <img
        className={className}
        src={src}
        alt=""
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <span className={className} aria-hidden>
      {avatarInitial(name)}
    </span>
  );
}
