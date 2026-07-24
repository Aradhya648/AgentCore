export function SectionHeader({
  id,
  label,
  sublabel,
}: {
  id?: string;
  label: string;
  sublabel?: string;
}) {
  return (
    <div id={id} className="scroll-mt-28 pt-6 pb-2">
      {sublabel ? (
        <>
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <h3 className="mt-1 text-xl font-semibold leading-snug text-foreground">
            {sublabel}
          </h3>
        </>
      ) : (
        <h3 className="text-xl font-semibold leading-snug text-foreground">
          {label}
        </h3>
      )}
    </div>
  );
}
