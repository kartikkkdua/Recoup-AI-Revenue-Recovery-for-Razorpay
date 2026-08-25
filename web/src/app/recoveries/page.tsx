import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { cohortLabel, inr, relTime } from "@/lib/format";
import { ErrorState } from "@/components/ErrorState";

export const dynamic = "force-dynamic";

export default async function RecoveriesPage({
  searchParams,
}: { searchParams: { status?: string; cohort?: string } }) {
  try {
    const list = await api.recoveries({ limit: 100, status: searchParams.status, cohort: searchParams.cohort });
    return (
      <AppShell>
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Recoveries</h1>
          <p className="text-sm text-muted">Every failed payment, and what the agent decided to do about it.</p>
        </div>
        <FilterBar current={searchParams} />
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-white/[0.03] text-left text-xs uppercase tracking-wider text-muted">
              <tr>
                <th className="px-4 py-3">When</th>
                <th className="px-4 py-3">Cohort</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Recovered</th>
                <th className="px-4 py-3">Attempts</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {list.items.length === 0 && (
                <tr><td colSpan={7} className="p-10 text-center text-sm text-muted">
                  No recoveries match this filter.
                </td></tr>
              )}
              {list.items.map((r) => (
                <tr key={r.id} className="hover:bg-white/[0.02]">
                  <td className="px-4 py-3 text-muted">{relTime(r.created_at)}</td>
                  <td className="px-4 py-3">{cohortLabel(r.cohort)}</td>
                  <td className="px-4 py-3 money">{inr(r.amount_paise)}</td>
                  <td className={`px-4 py-3 money ${r.recovered_paise > 0 ? "text-good" : "text-muted"}`}>
                    {inr(r.recovered_paise)}
                  </td>
                  <td className="px-4 py-3">{r.attempts}</td>
                  <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                  <td className="px-4 py-3 text-right">
                    <Link href={`/recoveries/${r.id}`} className="text-accent hover:underline">Inspect →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AppShell>
    );
  } catch {
    return <AppShell><ErrorState message="Backend not reachable." /></AppShell>;
  }
}

function FilterBar({ current }: { current: { status?: string; cohort?: string } }) {
  const statuses = ["recovered", "lost", "skipped", "in_progress"];
  return (
    <div className="mb-4 flex flex-wrap gap-2">
      <Link href="/recoveries" className={`pill ${!current.status ? "border-accent text-accent" : ""}`}>All</Link>
      {statuses.map((s) => (
        <Link key={s} href={`/recoveries?status=${s}`}
              className={`pill ${current.status === s ? "border-accent text-accent" : ""}`}>
          {s.replace("_", " ")}
        </Link>
      ))}
    </div>
  );
}
