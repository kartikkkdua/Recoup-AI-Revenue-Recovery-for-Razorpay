"""Thin Razorpay client wrapper.

Sandbox mode is forced when the caller marks the call as simulated (used by the
scenario generator so a benchmark run never depends on live Razorpay availability
or a real customer). Real webhook flow still hits the real API.
"""
from __future__ import annotations

import secrets
from typing import Any

from app.config import settings
from app.reliability import razorpay_circuit


class CircuitOpenError(RuntimeError):
    pass


class RazorpayClient:
    def __init__(self) -> None:
        self.sandbox = settings.razorpay_key_id == "rzp_test_placeholder"
        self._client = None
        if not self.sandbox:
            import razorpay

            self._client = razorpay.Client(
                auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
            )

    def _use_sandbox(self, simulated: bool) -> bool:
        return simulated or self.sandbox or not self._client

    async def create_payment_link(
        self,
        *,
        amount_paise: int,
        currency: str,
        customer: dict,
        simulated: bool = False,
        rail_hint: str | None = None,
    ) -> dict:
        if self._use_sandbox(simulated):
            return {
                "id": f"plink_sim_{secrets.token_hex(6)}",
                "short_url": f"https://rzp.io/i/sim_{secrets.token_hex(4)}",
                "amount": amount_paise,
                "currency": currency,
                "status": "created",
                "rail_hint": rail_hint,
                "sandbox": True,
            }
        if not await razorpay_circuit.before_call():
            raise CircuitOpenError("razorpay circuit open — payment_link.create refused")
        try:
            result = self._client.payment_link.create(
                {
                    "amount": amount_paise,
                    "currency": currency,
                    "customer": customer,
                    "notify": {"email": True, "sms": True},
                    "reminder_enable": True,
                }
            )
            await razorpay_circuit.on_success()
            return result
        except Exception:
            await razorpay_circuit.on_failure()
            raise

    async def retry_order(
        self,
        *,
        order_id: str,
        amount_paise: int,
        simulated: bool = False,
    ) -> dict:
        if self._use_sandbox(simulated):
            return {
                "id": f"order_sim_{secrets.token_hex(6)}",
                "source_order_id": order_id,
                "amount": amount_paise,
                "status": "created",
                "sandbox": True,
            }
        if not await razorpay_circuit.before_call():
            raise CircuitOpenError("razorpay circuit open — order.create refused")
        try:
            result = self._client.order.create({"amount": amount_paise, "currency": "INR"})
            await razorpay_circuit.on_success()
            return result
        except Exception:
            await razorpay_circuit.on_failure()
            raise

    async def send_whatsapp_nudge(
        self, *, customer: dict, amount_paise: int, short_url: str, simulated: bool = False
    ) -> dict:
        # No real WhatsApp yet — always sandboxed. Kept as a stub so the agent
        # can record the action in the audit trail and account for its cost.
        return {
            "id": f"wa_sim_{secrets.token_hex(6)}",
            "channel": "whatsapp",
            "to": customer.get("contact"),
            "amount": amount_paise,
            "short_url": short_url,
            "sandbox": True,
        }

    async def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        if self._use_sandbox(False):
            return {"id": payment_id, "status": "unknown", "sandbox": True}
        return self._client.payment.fetch(payment_id)


client = RazorpayClient()
