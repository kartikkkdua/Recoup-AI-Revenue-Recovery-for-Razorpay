"use client";

import { useEffect, useState, useTransition } from "react";
import { AppShell } from "@/components/AppShell";
import { api, type RuleRow, type RuleOverride } from "@/lib/api";
import { cohortLabel } from "@/lib/format";
import { ErrorState } from "@/components/ErrorState";
import { Save, RotateCcw, Loader2 } from "lucide-react";

export default function RulesPage() {
  const [items, setItems] = useState<RuleRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const r = await api.rules();
      setItems(r.items);
    } catch (e: any) {
      setError(e?.message ?? "load failed");
    }
  };

  useEffect(() => { load(); }, []);

  if (error) return <AppShell><ErrorState message={error} /></AppShell>;
  if (!items) return <AppShell><div className="text-sm text-muted">Loading…</div></AppShell>;

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Retry rules</h1>
        <p className="text-sm text-muted">
          Defaults are calibrated per cohort. Override any of them — changes persist to the
          database and the strategist reads them on the next failure.
        </p>
      </div>
      <div className="space-y-3">
        {items.map((row) => (
          <RuleCard key={row.cohort} row={row} onSaved={load} />
        ))}
      </div>
    </AppShell>
  );
}

function RuleCard({ row, onSaved }: { row: RuleRow; onSaved: () => void }) {
  const d = row.default ?? { action: "—", max_attempts: 0, backoff_seconds: [], rails: [], dunning_channels: [], reason: "" };
  const base: RuleOverride = row.override ?? {
    max_attempts: d.max_attempts,
    backoff_seconds: d.backoff_seconds,
    preferred_rails: d.rails,
    dunning_channels: d.dunning_channels,
    enabled: true,
  };
  const [form, setForm] = useState<RuleOverride>(base);
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);
  const isOverridden = row.override != null;

  const dirty = JSON.stringify(form) !== JSON.stringify(base);

  const save = () => {
    setMsg(null);
    start(async () => {
      try {
        await api.updateRule(row.cohort, form);
        setMsg("saved");
        onSaved();
      } catch (e: any) { setMsg(`err: ${e?.message}`); }
    });
  };

  const reset = () => {
    setMsg(null);
    start(async () => {
      try {
        await api.resetRule(row.cohort);
        setForm({
          max_attempts: d.max_attempts,
          backoff_seconds: d.backoff_seconds,
          preferred_rails: d.rails,
          dunning_channels: d.dunning_channels,
          enabled: true,
        });
        setMsg("reset to default");
        onSaved();
      } catch (e: any) { setMsg(`err: ${e?.message}`); }
    });
  };

  return (
    <div className="card p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="font-medium">{cohortLabel(row.cohort)}</div>
          <span className="pill">{d.action}</span>
          {isOverridden && <span className="pill text-yellow-400">merchant-tuned</span>}
        </div>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
          />
          Enabled
        </label>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <NumberField
          label="Max attempts"
          value={form.max_attempts}
          onChange={(n) => setForm({ ...form, max_attempts: n })}
          min={0} max={10}
        />
        <CsvField
          label="Backoff seconds"
          value={form.backoff_seconds.join(", ")}
          onChange={(v) => setForm({ ...form, backoff_seconds: parseIntCsv(v) })}
        />
        <CsvField
          label="Preferred rails"
          value={form.preferred_rails.join(", ")}
          onChange={(v) => setForm({ ...form, preferred_rails: parseStrCsv(v) })}
        />
        <CsvField
          label="Dunning channels"
          value={form.dunning_channels.join(", ")}
          onChange={(v) => setForm({ ...form, dunning_channels: parseStrCsv(v) })}
        />
      </div>
      {d.reason && <div className="mt-3 text-xs text-muted">{d.reason}</div>}
      <div className="mt-4 flex items-center gap-2">
        <button
          onClick={save}
          disabled={pending || !dirty}
          className="inline-flex items-center gap-2 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-40"
        >
          {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          Save override
        </button>
        <button
          onClick={reset}
          disabled={pending || !isOverridden}
          className="inline-flex items-center gap-2 rounded-md border border-border bg-panel px-3 py-1.5 text-sm hover:border-accent disabled:opacity-40"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Reset to default
        </button>
        {msg && <div className="text-xs text-muted">{msg}</div>}
      </div>
    </div>
  );
}

function NumberField({
  label, value, onChange, min, max,
}: { label: string; value: number; onChange: (n: number) => void; min: number; max: number }) {
  return (
    <label className="block">
      <div className="mb-1 text-xs uppercase tracking-wider text-muted">{label}</div>
      <input
        type="number" min={min} max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="w-full rounded-md border border-border bg-panel px-3 py-1.5 text-sm outline-none focus:border-accent"
      />
    </label>
  );
}

function CsvField({
  label, value, onChange,
}: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block">
      <div className="mb-1 text-xs uppercase tracking-wider text-muted">{label}</div>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border bg-panel px-3 py-1.5 text-sm outline-none focus:border-accent"
        placeholder="comma-separated"
      />
    </label>
  );
}

function parseIntCsv(s: string): number[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean).map((x) => Number(x) || 0).filter((n) => n >= 0);
}
function parseStrCsv(s: string): string[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}
