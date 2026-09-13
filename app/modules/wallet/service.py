from fastapi import HTTPException

from app.core.mongo import now_utc, oid
from app.modules.wallet.repository import TransferRepository, WalletRepository, WalletTransactionRepository


class WalletService:
    def __init__(self) -> None:
        self.wallets = WalletRepository()
        self.entries = WalletTransactionRepository()
        self.transfers = TransferRepository()

    async def ensure_wallet(self, owner_type: str, owner_id: str, currency: str,
                            project_id: str | None = None) -> dict:
        currency = currency.upper()
        existing = await self.wallets.find_one(
            {"owner_type": owner_type, "owner_id": owner_id, "currency": currency}
        )
        if existing:
            return existing
        doc = await self.wallets.insert(
            {
                "owner_type": owner_type,
                "owner_id": owner_id,
                "currency": currency,
                "available": 0,
                "pending": 0,
                "reserved": 0,
                "project_id": project_id,
            }
        )
        doc["id"] = doc.pop("_id")
        return doc

    async def _move(self, wallet: dict, field: str, delta: int, tx_type: str, project_id: str | None,
                    reference_type: str = "", reference_id: str = "", description: str = "") -> dict:
        new_value = wallet.get(field, 0) + delta
        if new_value < 0:
            raise HTTPException(status_code=422, detail="Insufficient funds")
        await self.wallets.collection.update_one({"_id": oid(wallet["id"])}, {"$inc": {field: delta}})
        updated = await self.wallets.get(wallet["id"])
        await self.entries.insert(
            {
                "wallet_id": wallet["id"],
                "project_id": project_id,
                "type": tx_type,
                "amount": delta,
                "currency": wallet["currency"],
                "balance_after": updated["available"],
                "reference_type": reference_type,
                "reference_id": reference_id,
                "description": description,
            }
        )
        return updated

    async def credit(self, owner_type: str, owner_id: str, currency: str, amount: int,
                     project_id: str | None = None, reference_type: str = "", reference_id: str = "",
                     description: str = "") -> dict:
        wallet = await self.ensure_wallet(owner_type, owner_id, currency, project_id)
        return await self._move(wallet, "available", amount, "credit", project_id, reference_type, reference_id, description)

    async def debit(self, owner_type: str, owner_id: str, currency: str, amount: int,
                    project_id: str | None = None, reference_type: str = "", reference_id: str = "",
                    description: str = "") -> dict:
        wallet = await self.ensure_wallet(owner_type, owner_id, currency, project_id)
        return await self._move(wallet, "available", -amount, "debit", project_id, reference_type, reference_id, description)

    async def reserve(self, owner_type: str, owner_id: str, currency: str, amount: int,
                      project_id: str | None = None) -> dict:
        wallet = await self.ensure_wallet(owner_type, owner_id, currency, project_id)
        if wallet.get("available", 0) < amount:
            raise HTTPException(status_code=422, detail="Insufficient funds to reserve")
        await self.wallets.collection.update_one(
            {"_id": oid(wallet["id"])}, {"$inc": {"available": -amount, "reserved": amount}}
        )
        await self.entries.insert({"wallet_id": wallet["id"], "project_id": project_id, "type": "reserve",
                                   "amount": -amount, "currency": wallet["currency"],
                                   "balance_after": wallet["available"] - amount, "description": "reserve"})
        return await self.wallets.get(wallet["id"])

    async def release(self, owner_type: str, owner_id: str, currency: str, amount: int,
                      project_id: str | None = None) -> dict:
        wallet = await self.ensure_wallet(owner_type, owner_id, currency, project_id)
        if wallet.get("reserved", 0) < amount:
            raise HTTPException(status_code=422, detail="Insufficient reserved balance")
        await self.wallets.collection.update_one(
            {"_id": oid(wallet["id"])}, {"$inc": {"available": amount, "reserved": -amount}}
        )
        await self.entries.insert({"wallet_id": wallet["id"], "project_id": project_id, "type": "release",
                                   "amount": amount, "currency": wallet["currency"],
                                   "balance_after": wallet["available"] + amount, "description": "release"})
        return await self.wallets.get(wallet["id"])

    async def transfer(self, project_id: str, source_type: str, source_id: str, dest_type: str,
                       dest_id: str, amount: int, currency: str, description: str = "") -> dict:
        await self.debit(source_type, source_id, currency, amount, project_id, "transfer", dest_id, description)
        await self.credit(dest_type, dest_id, currency, amount, project_id, "transfer", source_id, description)
        doc = await self.transfers.insert(
            {
                "project_id": project_id,
                "source_type": source_type,
                "source_id": source_id,
                "destination_type": dest_type,
                "destination_id": dest_id,
                "amount": amount,
                "currency": currency.upper(),
                "status": "succeeded",
                "description": description,
            }
        )
        doc["id"] = doc.pop("_id")
        return doc

    async def balances(self, owner_type: str, owner_id: str) -> list[dict]:
        return await self.wallets.find_many({"owner_type": owner_type, "owner_id": owner_id}, limit=50)

    async def statement(self, owner_type: str, owner_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
        wallets = await self.balances(owner_type, owner_id)
        ids = [w["id"] for w in wallets]
        return await self.entries.find_many({"wallet_id": {"$in": ids}}, limit=limit, skip=skip)

    async def list_transfers(self, project_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
        return await self.transfers.find_many({"project_id": project_id}, limit=limit, skip=skip)
