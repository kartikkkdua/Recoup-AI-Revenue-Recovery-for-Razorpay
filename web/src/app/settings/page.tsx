import { AppShell } from "@/components/AppShell";
import { CopyableRow } from "@/components/CopyableRow";

export default function SettingsPage() {
  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Integrations</h1>
        <p className="text-sm text-muted">Point Razorpay at Recoup and you're live.</p>
      </div>

      <div className="card p-6">
        <div className="text-sm font-medium">Razorpay webhook</div>
        <p className="mt-1 text-sm text-muted">
          Razorpay dashboard → Settings → Webhooks → Add.
        </p>
        <div className="mt-4 space-y-2">
          <CopyableRow label="URL" value="https://<your-tunnel>/webhooks" />
          <CopyableRow label="Events" value="payment.failed, subscription.charged.failed, order.paid, payment_link.paid" />
          <CopyableRow label="Signature header" value="X-Razorpay-Signature (HMAC-SHA256)" />
        </div>
      </div>

      <div className="card mt-4 p-6">
        <div className="text-sm font-medium">API keys</div>
        <p className="mt-1 text-sm text-muted">
          Store <code className="rounded bg-black/40 px-1 py-0.5">RAZORPAY_KEY_ID</code>,{" "}
          <code className="rounded bg-black/40 px-1 py-0.5">RAZORPAY_KEY_SECRET</code>, and{" "}
          <code className="rounded bg-black/40 px-1 py-0.5">RAZORPAY_WEBHOOK_SECRET</code> in{" "}
          <code className="rounded bg-black/40 px-1 py-0.5">api/.env</code>. Recoup never persists
          them in the DB.
        </p>
      </div>

      <div className="card mt-4 p-6">
        <div className="text-sm font-medium">Notifications</div>
        <p className="mt-1 text-sm text-muted">
          Dunning currently sends via Razorpay Payment Links (SMS + email). Slack/WhatsApp channels
          plug into the strategist's <code>dunning_channels</code> list.
        </p>
      </div>
    </AppShell>
  );
}
