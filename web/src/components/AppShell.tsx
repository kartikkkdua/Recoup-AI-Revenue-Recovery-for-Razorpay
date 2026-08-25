import Link from "next/link";
import { Activity, GaugeCircle, ListChecks, Settings, Sliders, Calculator, Repeat } from "lucide-react";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: GaugeCircle },
  { href: "/recoveries", label: "Recoveries", icon: ListChecks },
  { href: "/subscriptions", label: "Subscriptions", icon: Repeat },
  { href: "/rules", label: "Rules", icon: Sliders },
  { href: "/roi", label: "ROI", icon: Calculator },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 border-r border-border bg-panel md:flex md:flex-col">
        <Link href="/" className="flex items-center gap-2 px-5 py-5">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent/20 text-accent">
            <Activity className="h-4 w-4" />
          </div>
          <div className="text-sm font-semibold tracking-tight">Recoup</div>
        </Link>
        <nav className="flex-1 px-2 py-2">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-white/5 hover:text-text"
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          ))}
        </nav>
        <div className="border-t border-border px-4 py-3 text-xs text-muted">
          Sandbox mode
        </div>
      </aside>
      <main className="flex-1 overflow-x-hidden">
        <div className="mx-auto max-w-6xl px-6 py-8">{children}</div>
      </main>
    </div>
  );
}
