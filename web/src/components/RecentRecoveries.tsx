import Link from "next/link";
import type { RecoveryListItem } from "@/lib/api";
import { cohortLabel, inr, relTime } from "@/lib/format";
import { StatusBadge } from "./StatusBadge";

export function RecentRecoveries({ items }: { items: RecoveryListItem[] }) {
  return (
    <div className="card p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <div>
          <div className="text-sm font-medium">Recent recoveries</div>
          <div className="text-xs text-muted">Last 10 events</div>
        </div>
        <Link href="/recoveries" className="text-xs text-accent hover:underline">View all</Link>
      </div>
      <div className="divide-y divide-border">
        {items.length === 0 && (
          <div className="py-8 text-center text-sm text-muted">Nothing yet.</div>
        )}
        {items.map((r) => (
          <Link key={r.id} href={`/recoveries/${r.id}`} className="flex items-center justify-between py-3 text-sm hover:bg-white/5">
            <div className="min-w-0">
              <div className="truncate">{cohortLabel(r.cohort)}</div>
              <div className="text-xs text-muted">{relTime(r.created_at)}</div>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <div className="money">{inr(r.amount_paise)}</div>
              <StatusBadge status={r.status} />
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
