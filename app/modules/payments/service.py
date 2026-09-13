"""LEAMSE Payments — proprietary payment engine. No external gateway involved.

All amounts are integers in the currency minor unit. Authorization/capture/refund
lifecycle is settled through the immutable double-entry ledger and wallets.
"""

from fastapi import HTTPException

from app.core.money import platform_fee, split_amounts
from app.core.security import random_token
from app.modules.ledger.service import LedgerService
from app.modules.payments.repository import (
    ChargeRepository,
    FeeRepository,
    PaymentIntentRepository,
    PaymentLinkRepository,
    RefundRepository,
    SettlementRepository,
    TransactionRepository,
)
from app.modules.payments.schema import PaymentIntentCreate, PaymentMethod
from app.modules.wallet.service import WalletService
from app.modules.webhooks.service import WebhookService

DECLINE_SUFFIXES = ("0002", "0341")


class PaymentEngine:
    """Authorization decision engine of LEAMSE Payments."""

    @staticmethod
    def authorize(amount: int, method: PaymentMethod) -> dict:
        number = (method.card_number or "").replace(" ", "")
        risk = 10
        if method.type == "card":
            if len(number) < 12:
                return {"approved": False, "reason": "invalid_number", "risk_score": 99}
            if number.endswith(DECLINE_SUFFIXES):
                return {"approved": False, "reason": "card_declined", "risk_score": 85}
            risk = 20 if amount > 500000 else 8
        elif method.type in ("pix", "boleto", "bank_transfer"):
            risk = 5
        return {"approved": True, "reason": "approved", "risk_score": risk}

    @staticmethod
    def fingerprint(method: PaymentMethod) -> dict:
        number = (method.card_number or "").replace(" ", "")
        return {
            "type": method.type,
            "last4": number[-4:] if number else None,
            "brand": "leamse_card" if method.type == "card" else method.type,
            "holder_name": method.holder_name,
        }


class PaymentService:
    def __init__(self) -> None:
        self.intents = PaymentIntentRepository()
        self.charges = ChargeRepository()
        self.refunds = RefundRepository()
        self.fees = FeeRepository()
        self.transactions = TransactionRepository()
        self.settlements = SettlementRepository()
        self.links = PaymentLinkRepository()
        self.ledger = LedgerService()
        self.wallets = WalletService()
        self.webhooks = WebhookService()

    async def create_intent(self, project_id: str, payload: PaymentIntentCreate) -> dict:
        doc = await self.intents.insert(
            {
                "project_id": project_id,
                "amount": payload.amount,
                "currency": payload.currency.upper(),
                "status": "requires_payment_method",
                "capture_method": payload.capture_method,
                "description": payload.description,
                "customer_id": payload.customer_id,
                "order_id": payload.order_id,
                "splits": [s.model_dump() for s in payload.splits],
                "metadata": payload.metadata,
                "client_secret": f"pi_secret_{random_token(18)}",
            }
        )
        doc["id"] = doc.pop("_id")
        return doc

    async def get_intent(self, project_id: str, intent_id: str) -> dict:
        intent = await self.intents.get(intent_id, extra={"project_id": project_id})
        if not intent:
            raise HTTPException(status_code=404, detail="Payment intent not found")
        return intent

    async def create_charge(self, project_id: str, organization_id: str, intent_id: str,
                            method: PaymentMethod) -> dict:
        intent = await self.get_intent(project_id, intent_id)
        if intent["status"] in ("succeeded", "canceled"):
            raise HTTPException(status_code=409, detail="Payment intent already finalized")
        decision = PaymentEngine.authorize(intent["amount"], method)
        fee = platform_fee(intent["amount"])
        charge = await self.charges.insert(
            {
                "project_id": project_id,
                "payment_intent_id": intent_id,
                "amount": intent["amount"],
                "amount_captured": 0,
                "amount_refunded": 0,
                "currency": intent["currency"],
                "status": "authorized" if decision["approved"] else "failed",
                "payment_method": PaymentEngine.fingerprint(method),
                "failure_reason": None if decision["approved"] else decision["reason"],
                "fee": fee,
                "net": intent["amount"] - fee,
                "risk_score": decision["risk_score"],
            }
        )
        charge_id = charge.pop("_id")
        charge["id"] = charge_id
        if not decision["approved"]:
            await self.intents.update(intent_id, {"status": "failed", "charge_id": charge_id})
            await self.webhooks.dispatch(project_id, "payment.failed", {"charge_id": charge_id, "intent_id": intent_id,
                                                                        "reason": decision["reason"]})
            return charge
        await self.intents.update(
            intent_id,
            {"status": "requires_capture" if intent["capture_method"] == "manual" else "processing",
             "charge_id": charge_id},
        )
        if intent["capture_method"] == "automatic":
            return await self.capture(project_id, organization_id, charge_id, None)
        return charge

    async def capture(self, project_id: str, organization_id: str, charge_id: str,
                      amount: int | None) -> dict:
        charge = await self.charges.get(charge_id, extra={"project_id": project_id})
        if not charge:
            raise HTTPException(status_code=404, detail="Charge not found")
        if charge["status"] not in ("authorized",):
            raise HTTPException(status_code=409, detail=f"Charge cannot be captured in status {charge['status']}")
        capture_amount = amount or charge["amount"]
        if capture_amount > charge["amount"]:
            raise HTTPException(status_code=422, detail="Capture amount exceeds authorized amount")
        fee = platform_fee(capture_amount)
        net = capture_amount - fee
        intent = await self.intents.get(charge["payment_intent_id"])
        splits = (intent or {}).get("splits") or []
        lines = [
            {"account": f"customer:{(intent or {}).get('customer_id') or 'guest'}",
             "account_type": "customer", "direction": "debit", "amount": capture_amount},
            {"account": "platform:leamse_fees", "account_type": "platform", "direction": "credit", "amount": fee},
        ]
        distributions = split_amounts(net, splits) if splits else []
        if distributions:
            for d in distributions:
                lines.append({"account": f"seller:{d['destination']}", "account_type": "seller",
                              "direction": "credit", "amount": d["amount"]})
        else:
            lines.append({"account": f"organization:{organization_id}", "account_type": "organization",
                          "direction": "credit", "amount": net})
        group = await self.ledger.post(project_id, charge["currency"], "charge", charge_id, lines,
                                      description="charge captured")
        if distributions:
            for d in distributions:
                await self.wallets.credit("seller", d["destination"], charge["currency"], d["amount"],
                                          project_id, "charge", charge_id, "split payout")
        else:
            await self.wallets.credit("organization", organization_id, charge["currency"], net,
                                      project_id, "charge", charge_id, "charge captured")
        await self.fees.insert({"project_id": project_id, "charge_id": charge_id, "amount": fee,
                                "currency": charge["currency"], "type": "platform_fee"})
        updated = await self.charges.update(charge_id, {"status": "captured", "amount_captured": capture_amount,
                                                        "fee": fee, "net": net, "ledger_group": group})
        await self.intents.update(charge["payment_intent_id"], {"status": "succeeded"})
        await self.transactions.insert({"project_id": project_id, "type": "charge", "amount": capture_amount,
                                        "fee": fee, "net": net, "currency": charge["currency"],
                                        "status": "succeeded", "reference_id": charge_id,
                                        "splits": distributions})
        await self.webhooks.dispatch(project_id, "payment.succeeded",
                                     {"charge_id": charge_id, "amount": capture_amount,
                                      "currency": charge["currency"], "net": net, "fee": fee})
        return updated

    async def refund(self, project_id: str, organization_id: str, charge_id: str,
                     amount: int | None, reason: str) -> dict:
        charge = await self.charges.get(charge_id, extra={"project_id": project_id})
        if not charge:
            raise HTTPException(status_code=404, detail="Charge not found")
        if charge["status"] not in ("captured", "partially_refunded"):
            raise HTTPException(status_code=409, detail="Only captured charges can be refunded")
        refundable = charge["amount_captured"] - charge.get("amount_refunded", 0)
        if refundable <= 0:
            raise HTTPException(status_code=409, detail="Charge is already fully refunded")
        refund_amount = amount or refundable
        if refund_amount > refundable:
            raise HTTPException(status_code=422, detail="Refund amount exceeds refundable amount")
        fee_back = platform_fee(refund_amount)
        lines = [
            {"account": f"customer:guest", "account_type": "customer", "direction": "credit", "amount": refund_amount},
            {"account": "platform:leamse_fees", "account_type": "platform", "direction": "debit", "amount": fee_back},
            {"account": f"organization:{organization_id}", "account_type": "organization", "direction": "debit",
             "amount": refund_amount - fee_back},
        ]
        group = await self.ledger.post(project_id, charge["currency"], "refund", charge_id, lines, "refund")
        await self.wallets.debit("organization", organization_id, charge["currency"], refund_amount - fee_back,
                                 project_id, "refund", charge_id, reason)
        refund = await self.refunds.insert({"project_id": project_id, "charge_id": charge_id,
                                            "amount": refund_amount, "currency": charge["currency"],
                                            "reason": reason, "status": "succeeded", "ledger_group": group})
        refund["id"] = refund.pop("_id")
        total_refunded = charge.get("amount_refunded", 0) + refund_amount
        await self.charges.update(charge_id, {
            "amount_refunded": total_refunded,
            "status": "refunded" if total_refunded >= charge["amount_captured"] else "partially_refunded",
        })
        await self.transactions.insert({"project_id": project_id, "type": "refund", "amount": -refund_amount,
                                        "fee": -fee_back, "net": -(refund_amount - fee_back),
                                        "currency": charge["currency"], "status": "succeeded",
                                        "reference_id": charge_id})
        await self.webhooks.dispatch(project_id, "refund.created", {"charge_id": charge_id, "amount": refund_amount})
        return refund

    async def cancel_intent(self, project_id: str, intent_id: str) -> dict:
        intent = await self.get_intent(project_id, intent_id)
        if intent["status"] in ("succeeded",):
            raise HTTPException(status_code=409, detail="Cannot cancel a succeeded intent")
        return await self.intents.update(intent_id, {"status": "canceled"})

    async def list_intents(self, project_id: str, limit: int = 50, skip: int = 0, status: str | None = None) -> list[dict]:
        query: dict = {"project_id": project_id}
        if status:
            query["status"] = status
        return await self.intents.find_many(query, limit=limit, skip=skip)

    async def list_charges(self, project_id: str, limit: int = 50, skip: int = 0, status: str | None = None) -> list[dict]:
        query: dict = {"project_id": project_id}
        if status:
            query["status"] = status
        return await self.charges.find_many(query, limit=limit, skip=skip)

    async def list_refunds(self, project_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
        return await self.refunds.find_many({"project_id": project_id}, limit=limit, skip=skip)

    async def list_transactions(self, project_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
        return await self.transactions.find_many({"project_id": project_id}, limit=limit, skip=skip)

    async def create_payment_link(self, project_id: str, payload: dict) -> dict:
        token = random_token(12)
        doc = await self.links.insert({**payload, "project_id": project_id, "token": token,
                                       "currency": payload["currency"].upper(), "status": "active"})
        doc["id"] = doc.pop("_id")
        doc["url"] = f"/checkout/{token}"
        return doc

    async def list_payment_links(self, project_id: str) -> list[dict]:
        links = await self.links.find_many({"project_id": project_id}, limit=100)
        for l in links:
            l["url"] = f"/checkout/{l['token']}"
        return links

    async def get_payment_link(self, token: str) -> dict:
        link = await self.links.find_one({"token": token, "status": "active"})
        if not link:
            raise HTTPException(status_code=404, detail="Payment link not found")
        link["url"] = f"/checkout/{token}"
        return link

    async def settle(self, project_id: str, currency: str) -> dict:
        pipeline = [
            {"$match": {"project_id": project_id, "currency": currency.upper(), "type": "charge"}},
            {"$group": {"_id": None, "gross": {"$sum": "$amount"}, "fees": {"$sum": "$fee"}, "net": {"$sum": "$net"}}},
        ]
        rows = await self.transactions.aggregate(pipeline)
        totals = rows[0] if rows else {"gross": 0, "fees": 0, "net": 0}
        doc = await self.settlements.insert({"project_id": project_id, "currency": currency.upper(),
                                             "gross": totals.get("gross", 0), "fees": totals.get("fees", 0),
                                             "net": totals.get("net", 0), "status": "paid"})
        doc["id"] = doc.pop("_id")
        return doc
