import { fetchAvatarObjectUrl } from "@/api/account";
import type { User } from "@/api/auth";
// Bearer-safe avatar: fetches the image as a blob → object URL (an <img src> can't
// carry the Authorization header), falling back to the name initial. Shared by the
// settings hub and the account page.
import { useEffect, useState } from "react";

export function Avatar({ user, size }: { user: User | null; size: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const avatarPath = user?.avatar_url ?? null;

  useEffect(() => {
    if (!avatarPath) {
      setUrl(null);
      return;
    }
    let objectUrl: string | null = null;
    let cancelled = false;
    fetchAvatarObjectUrl(avatarPath).then((u) => {
      if (cancelled) {
        if (u) URL.revokeObjectURL(u);
        return;
      }
      objectUrl = u;
      setUrl(u);
    });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [avatarPath]);

  const initial = (user?.display_name || user?.username || "?")
    .charAt(0)
    .toUpperCase();

  return (
    <span className="more-avatar" style={{ width: size, height: size }}>
      {url ? <img src={url} alt="头像" /> : initial}
    </span>
  );
}
