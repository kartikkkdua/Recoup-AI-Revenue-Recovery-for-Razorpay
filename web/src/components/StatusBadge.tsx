const MAP: Record<string, string> = {
  recovered: "border-good/40 text-good",
  lost: "border-bad/40 text-bad",
  skipped: "border-warn/40 text-warn",
  in_progress: "border-accent/40 text-accent",
  pending: "border-muted/40 text-muted",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = MAP[status] ?? "border-border text-muted";
  return <span className={`pill ${cls}`}>{status.replace("_", " ")}</span>;
}
