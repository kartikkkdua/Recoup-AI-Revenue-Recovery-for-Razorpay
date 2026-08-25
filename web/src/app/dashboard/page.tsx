import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import { HeadlineMetrics } from "@/components/HeadlineMetrics";
import { CohortTable } from "@/components/CohortTable";
import { RecentRecoveries } from "@/components/RecentRecoveries";
import { SimulatorButton } from "@/components/SimulatorButton";
import { ComparisonPanel } from "@/components/ComparisonPanel";
import { ReliabilityStrip } from "@/components/ReliabilityStrip";
import { LiveTicker } from "@/components/LiveTicker";
import { DriftAlerts } from "@/components/DriftAlerts";
import { ErrorState } from "@/components/ErrorState";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  try {
    const [summary, compare, cohorts, list, reliability, drift] = await Promise.all([
      api.summary(24 * 30),
      api.compare(24 * 30),
      api.cohorts(24 * 30, "agent"),
      api.recoveries({ limit: 10 }),
      api.reliability(),
      api.driftAlerts().catch(() => ({ alerts: [] as any[] })),
    ]);
    return (
      <AppShell>
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
            <p className="text-sm text-muted">Last 30 days · sandbox data</p>
          </div>
          <SimulatorButton />
        </div>
        <div className="mb-4">
          <LiveTicker />
        </div>
        <HeadlineMetrics summary={summary} />
        <div className="mt-6">
          <ReliabilityStrip r={reliability} />
        </div>
        <div className="mt-6">
          <ComparisonPanel compare={compare} />
        </div>
        {drift.alerts.length > 0 && (
          <div className="mt-6">
            <DriftAlerts alerts={drift.alerts as any} />
          </div>
        )}
        <div className="mt-6 grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <CohortTable rows={cohorts.cohorts} />
          </div>
          <RecentRecoveries items={list.items} />
        </div>
      </AppShell>
    );
  } catch (e) {
    return (
      <AppShell>
        <ErrorState message="Backend not reachable. Start the API: `uvicorn app.main:app --reload` in ./api" />
      </AppShell>
    );
  }
}
