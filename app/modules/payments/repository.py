from app.core.repository import BaseRepository


class PaymentIntentRepository(BaseRepository):
    collection_name = "payment_intents"


class ChargeRepository(BaseRepository):
    collection_name = "charges"


class RefundRepository(BaseRepository):
    collection_name = "refunds"


class FeeRepository(BaseRepository):
    collection_name = "fees"


class TransactionRepository(BaseRepository):
    collection_name = "transactions"


class SettlementRepository(BaseRepository):
    collection_name = "settlements"


class PaymentLinkRepository(BaseRepository):
    collection_name = "payment_links"
