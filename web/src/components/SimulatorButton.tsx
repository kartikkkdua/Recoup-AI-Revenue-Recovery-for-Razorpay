"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Play, Loader2, GitCompare } from "lucide-react";
import { api } from "@/lib/api";

export function SimulatorButton() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [count, setCount] = useState(400);
  const [msg, setMsg] = useState<string | null>(null);

  const run = (mode: "agent" | "benchmark") => {
    setMsg(null);
    start(async () => {
      try {
        if (mode === "benchmark") {
          const r = await api.runBenchmark(count);
          setMsg(`Benchmarking ${r.injected_per_mode} scenarios × 2 modes…`);
        } else {
          const r = await api.runSimulator(count, "agent");
          setMsg(`Injected ${r.injected} events (agent mode). Processing…`);
        }
        setTimeout(() => router.refresh(), 2000);
      } catch (e: any) {
        setMsg(`Failed: ${e?.message ?? "unknown error"}`);
      }
    });
  };

  return (
    <div className="flex items-center gap-2">
      <input
        type="number"
        min={1}
        max={2000}
        value={count}
        onChange={(e) => setCount(Number(e.target.value))}
        className="w-24 rounded-md border border-border bg-panel px-2 py-1.5 text-sm outline-none focus:border-accent"
      />
      <button
        onClick={() => run("agent")}
        disabled={pending}
        className="inline-flex items-center gap-2 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-60"
      >
        {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
        Run agent
      </button>
      <button
        onClick={() => run("benchmark")}
        disabled={pending}
        title="Runs the same scenarios through both agent and naive strategies"
        className="inline-flex items-center gap-2 rounded-md border border-border bg-panel px-3 py-1.5 text-sm font-medium hover:border-accent disabled:opacity-60"
      >
        <GitCompare className="h-4 w-4" />
        Benchmark vs naive
      </button>
      {msg && <div className="text-xs text-muted">{msg}</div>}
    </div>
  );
}
