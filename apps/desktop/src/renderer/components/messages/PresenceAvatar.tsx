/** Avatar with an optional online presence green dot (IM 在线态). */
export function PresenceAvatar({
  label,
  sizeClass,
  textClass,
  online = false,
}: {
  label: string;
  sizeClass: string;
  textClass: string;
  online?: boolean;
}) {
  return (
    <span
      className={`relative flex shrink-0 items-center justify-center rounded-full bg-primary/10 font-medium text-primary ${sizeClass}`}
    >
      <span className={textClass}>{label}</span>
      {online && (
        <span
          aria-label="在线"
          className="absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full bg-success ring-2 ring-background"
        />
      )}
    </span>
  );
}
