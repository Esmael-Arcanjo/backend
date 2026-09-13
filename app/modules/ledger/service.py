"""Immutable double-entry ledger. Entries are append-only; corrections use reversals."""

import uuid

from fastapi import HTTPException

from app.core.mongo import now_utc
from app.modules.ledger.repository import LedgerRepository


class LedgerService:
    def __init__(self) -> None:
        self.repo = LedgerRepository()

    async def post(self, project_id: str, currency: str, reference_type: str, reference_id: str,
                   lines: list[dict], description: str = "") -> str:
        """lines: [{account, account_type, direction, amount}] — debits must equal credits."""
        debits = sum(l["amount"] for l in lines if l["direction"] == "debit")
        credits = sum(l["amount"] for l in lines if l["direction"] == "credit")
        if debits != credits:
            raise HTTPException(status_code=422, detail=f"Unbalanced ledger entry: {debits} != {credits}")
        group = str(uuid.uuid4())
        docs = [
            {
                "project_id": project_id,
                "transaction_group": group,
                "account": l["account"],
                "account_type": l["account_type"],
                "direction": l["direction"],
                "amount": int(l["amount"]),
                "currency": currency.upper(),
                "reference_type": reference_type,
                "reference_id": reference_id,
                "description": l.get("description", description),
                "metadata": l.get("metadata", {}),
                "created_at": now_utc(),
            }
            for l in lines
        ]
        await self.repo.collection.insert_many(docs)
        return group

    async def reverse(self, project_id: str, transaction_group: str, reason: str = "reversal") -> str:
        entries = await self.repo.find_many({"project_id": project_id, "transaction_group": transaction_group}, limit=200)
        if not entries:
            raise HTTPException(status_code=404, detail="Ledger group not found")
        group = str(uuid.uuid4())
        docs = [
            {
                "project_id": project_id,
                "transaction_group": group,
                "account": e["account"],
                "account_type": e["account_type"],
                "direction": "credit" if e["direction"] == "debit" else "debit",
                "amount": e["amount"],
                "currency": e["currency"],
                "reference_type": e["reference_type"],
                "reference_id": e["reference_id"],
                "description": reason,
                "reversal_of": transaction_group,
                "created_at": now_utc(),
            }
            for e in entries
        ]
        await self.repo.collection.insert_many(docs)
        return group

    async def list_entries(self, project_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
        return await self.repo.find_many({"project_id": project_id}, limit=limit, skip=skip)

    async def trial_balance(self, project_id: str) -> list[dict]:
        pipeline = [
            {"$match": {"project_id": project_id}},
            {
                "$group": {
                    "_id": {"account": "$account", "currency": "$currency"},
                    "debit": {"$sum": {"$cond": [{"$eq": ["$direction", "debit"]}, "$amount", 0]}},
                    "credit": {"$sum": {"$cond": [{"$eq": ["$direction", "credit"]}, "$amount", 0]}},
                }
            },
        ]
        rows = await self.repo.aggregate(pipeline)
        return [
            {
                "account": r["_id"]["account"],
                "currency": r["_id"]["currency"],
                "debit": r["debit"],
                "credit": r["credit"],
                "balance": r["credit"] - r["debit"],
            }
            for r in rows
        ]
